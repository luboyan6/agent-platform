from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import httpx
import pytest

from weknora_mcp.search import InvalidSearchRequest, SearchError, WeKnoraSearch

from .conftest import KB_ID, OTHER_KB_ID


def _hit(**overrides: object) -> dict[str, object]:
    return {
        "id": "chunk-1",
        "knowledge_id": "document-1",
        "knowledge_base_id": KB_ID,
        "knowledge_title": "操作手册",
        "knowledge_filename": "manual.md",
        "content": "重启前先保存。",
        "score": 0.8,
        "chunk_index": 3,
        **overrides,
    }


@pytest.mark.asyncio
async def test_knowledge_search_contract_auth_and_citations(settings) -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/knowledge-search"
        assert request.url.params.get("resource_urls") == "handle"
        assert request.headers["X-API-Key"] == "test-api-secret"
        assert request.headers["X-Tenant-ID"] == "tenant-1"
        assert json.loads(request.content) == {"query": "如何重启", "knowledge_base_ids": [KB_ID]}
        return httpx.Response(200, json={"success": True, "data": [_hit(), _hit()]})

    result = await WeKnoraSearch(settings, transport=httpx.MockTransport(handle)).search("  如何重启  ", top_k=3)

    assert result.searched_knowledge_base_ids == (KB_ID,)
    assert len(result.results) == 1
    assert result.results[0].content == "重启前先保存。"
    assert result.results[0].citation == f"weknora:{KB_ID}:document-1:chunk-1"
    assert result.results[0].title == "操作手册"
    assert result.results[0].filename == "manual.md"


@pytest.mark.asyncio
async def test_space_key_omits_the_optional_tenant_header(settings) -> None:
    settings = replace(settings, tenant_id=None)

    async def handle(request: httpx.Request) -> httpx.Response:
        assert "X-Tenant-ID" not in request.headers
        return httpx.Response(200, json={"success": True, "data": []})

    result = await WeKnoraSearch(settings, transport=httpx.MockTransport(handle)).search("q")

    assert result.results == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "top_k", "knowledge_base_ids"),
    [
        (" ", 5, None),
        ("q" * 4001, 5, None),
        ("q", 0, None),
        ("q", 11, None),
        ("q", True, None),
        ("q", 5, []),
        ("q", 5, [OTHER_KB_ID]),
    ],
)
async def test_invalid_input_never_reaches_upstream(settings, query, top_k, knowledge_base_ids) -> None:
    async def forbidden(_: httpx.Request) -> httpx.Response:
        pytest.fail("invalid request reached WeKnora")

    with pytest.raises(InvalidSearchRequest):
        await WeKnoraSearch(settings, transport=httpx.MockTransport(forbidden)).search(query, top_k, knowledge_base_ids)


@pytest.mark.asyncio
async def test_multi_kb_results_are_interleaved_and_requested_ids_are_deduplicated(settings) -> None:
    settings = replace(settings, knowledge_base_ids=(KB_ID, OTHER_KB_ID))
    calls: list[str] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        knowledge_base_id = json.loads(request.content)["knowledge_base_ids"][0]
        calls.append(knowledge_base_id)
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": [
                    _hit(id=f"{knowledge_base_id}-1", knowledge_base_id=knowledge_base_id),
                    _hit(id=f"{knowledge_base_id}-2", knowledge_base_id=knowledge_base_id),
                ],
            },
        )

    result = await WeKnoraSearch(settings, transport=httpx.MockTransport(handle)).search(
        "q", 3, [KB_ID, KB_ID, OTHER_KB_ID]
    )

    assert calls == [KB_ID, OTHER_KB_ID]
    assert [item.knowledge_base_id for item in result.results] == [KB_ID, OTHER_KB_ID, KB_ID]


@pytest.mark.asyncio
async def test_empty_results_and_content_truncation_are_explicit(settings) -> None:
    payload: dict[str, object] = {"success": True, "data": None}

    async def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    search = WeKnoraSearch(settings, transport=httpx.MockTransport(handle))
    assert (await search.search("q")).results == ()

    payload["data"] = [_hit(content="x" * 9000)]
    result = await search.search("q")
    assert len(result.results[0].content) == 4000
    assert result.results[0].truncated is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "payload"),
    [
        (401, {"error": "test-api-secret"}),
        (403, {}),
        (500, {}),
        (302, {}),
        (200, {"success": False, "error": "test-api-secret"}),
        (200, {"success": True}),
        (200, {"success": True, "data": "wrong"}),
        (200, {"success": True, "data": [{}]}),
        (200, {"success": True, "data": [_hit(content=" \t")]}),
        (200, None),
    ],
)
async def test_upstream_errors_fail_closed_without_echoing_payload_or_credentials(
    settings, status: int, payload: object
) -> None:
    async def handle(_: httpx.Request) -> httpx.Response:
        if payload is None:
            return httpx.Response(status, content=b"not-json:test-api-secret")
        return httpx.Response(status, json=payload, headers={"location": "https://elsewhere.invalid"})

    with pytest.raises(SearchError) as exc_info:
        await WeKnoraSearch(settings, transport=httpx.MockTransport(handle)).search("q")

    message = str(exc_info.value)
    assert "test-api-secret" not in message
    assert "not-json" not in message
    assert "WeKnora" in message


@pytest.mark.asyncio
async def test_cross_kb_result_is_rejected(settings) -> None:
    async def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True, "data": [_hit(knowledge_base_id=OTHER_KB_ID)]})

    with pytest.raises(SearchError, match="WeKnora"):
        await WeKnoraSearch(settings, transport=httpx.MockTransport(handle)).search("q")


@pytest.mark.asyncio
async def test_result_without_knowledge_base_identity_is_rejected(settings) -> None:
    hit = _hit()
    del hit["knowledge_base_id"]

    async def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True, "data": [hit]})

    with pytest.raises(SearchError, match="invalid search result"):
        await WeKnoraSearch(settings, transport=httpx.MockTransport(handle)).search("q")


class _OversizedStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b"x" * (2 * 1024 * 1024)
        yield b"x"


@pytest.mark.asyncio
async def test_response_limit_is_enforced_while_streaming_without_content_length(settings) -> None:
    async def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_OversizedStream())

    with pytest.raises(SearchError, match="too large"):
        await WeKnoraSearch(settings, transport=httpx.MockTransport(handle)).search("q")


@pytest.mark.asyncio
async def test_total_deadline_cancels_a_stalled_upstream(settings) -> None:
    never = asyncio.Event()

    async def handle(_: httpx.Request) -> httpx.Response:
        await never.wait()
        raise AssertionError("unreachable")

    settings = replace(settings, request_timeout_seconds=0.01)
    with pytest.raises(SearchError, match="timed out"):
        await WeKnoraSearch(settings, transport=httpx.MockTransport(handle)).search("q")


@pytest.mark.asyncio
async def test_transport_timeout_is_reported_as_timeout(settings) -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("secret upstream detail", request=request)

    with pytest.raises(SearchError, match="timed out") as exc_info:
        await WeKnoraSearch(settings, transport=httpx.MockTransport(handle)).search("q")

    assert "secret upstream detail" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


@pytest.mark.asyncio
async def test_connection_failure_is_sanitized(settings) -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("secret network detail", request=request)

    with pytest.raises(SearchError, match="request failed") as exc_info:
        await WeKnoraSearch(settings, transport=httpx.MockTransport(handle)).search("q")

    assert "secret network detail" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


@pytest.mark.asyncio
async def test_one_failed_knowledge_base_fails_the_complete_multi_kb_search(settings) -> None:
    settings = replace(settings, knowledge_base_ids=(KB_ID, OTHER_KB_ID))

    async def handle(request: httpx.Request) -> httpx.Response:
        knowledge_base_id = json.loads(request.content)["knowledge_base_ids"][0]
        if knowledge_base_id == OTHER_KB_ID:
            return httpx.Response(403, json={"error": "secret partial failure"})
        return httpx.Response(200, json={"success": True, "data": [_hit()]})

    with pytest.raises(SearchError, match="HTTP 403") as exc_info:
        await WeKnoraSearch(settings, transport=httpx.MockTransport(handle)).search("q")

    assert "secret partial failure" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_upstream_concurrency_is_bounded(settings) -> None:
    knowledge_base_ids = tuple(f"{index:08d}-1111-4111-8111-111111111111" for index in range(8))
    settings = replace(settings, knowledge_base_ids=knowledge_base_ids)
    release = asyncio.Event()
    active = 0
    maximum_active = 0

    async def handle(request: httpx.Request) -> httpx.Response:
        nonlocal active, maximum_active
        knowledge_base_id = json.loads(request.content)["knowledge_base_ids"][0]
        active += 1
        maximum_active = max(maximum_active, active)
        if active == settings.max_concurrency:
            release.set()
        await release.wait()
        active -= 1
        return httpx.Response(
            200, json={"success": True, "data": [_hit(id=knowledge_base_id, knowledge_base_id=knowledge_base_id)]}
        )

    result = await WeKnoraSearch(settings, transport=httpx.MockTransport(handle)).search("q", 8)

    assert len(result.results) == 8
    assert maximum_active == settings.max_concurrency
