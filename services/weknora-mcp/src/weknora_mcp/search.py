"""Bounded, read-only client for WeKnora's knowledge-search endpoint."""

from __future__ import annotations

import asyncio
import json
import math
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx

from weknora_mcp.config import Settings


class InvalidSearchRequest(ValueError):
    """Raised before I/O when model-controlled search input is invalid."""


class SearchError(RuntimeError):
    """Sanitized error raised when WeKnora cannot provide complete evidence."""


@dataclass(frozen=True)
class SearchResult:
    citation: str
    knowledge_base_id: str
    knowledge_id: str
    chunk_id: str
    title: str | None
    filename: str | None
    content: str
    score: float | None
    chunk_index: int | None
    truncated: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "citation": self.citation,
            "knowledge_base_id": self.knowledge_base_id,
            "knowledge_id": self.knowledge_id,
            "chunk_id": self.chunk_id,
            "title": self.title,
            "filename": self.filename,
            "content": self.content,
            "score": self.score,
            "chunk_index": self.chunk_index,
            "truncated": self.truncated,
        }


@dataclass(frozen=True)
class SearchResponse:
    searched_knowledge_base_ids: tuple[str, ...]
    results: tuple[SearchResult, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "searched_knowledge_base_ids": list(self.searched_knowledge_base_ids),
            "results": [result.to_dict() for result in self.results],
        }


class WeKnoraSearch:
    """Validate, execute, and project WeKnora retrieval into a small contract."""

    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._settings = settings
        self._transport = transport

    async def search(
        self,
        query: str,
        top_k: int = 5,
        knowledge_base_ids: list[str] | None = None,
    ) -> SearchResponse:
        normalized_query = _validate_query(query)
        normalized_top_k = _validate_top_k(top_k)
        selected_ids = _select_knowledge_base_ids(knowledge_base_ids, self._settings.knowledge_base_ids)

        headers = {"X-API-Key": self._settings.weknora_api_key}
        if self._settings.tenant_id is not None:
            headers["X-Tenant-ID"] = self._settings.tenant_id

        timeout = httpx.Timeout(self._settings.request_timeout_seconds)
        try:
            async with asyncio.timeout(self._settings.request_timeout_seconds):
                async with httpx.AsyncClient(
                    base_url=self._settings.weknora_base_url,
                    headers=headers,
                    timeout=timeout,
                    follow_redirects=False,
                    trust_env=False,
                    transport=self._transport,
                ) as client:
                    per_knowledge_base = await self._fetch_all(client, normalized_query, selected_ids)
        except TimeoutError:
            raise SearchError("WeKnora search timed out") from None
        except httpx.HTTPError:
            raise SearchError("WeKnora search request failed") from None

        interleaved = _interleave(per_knowledge_base, normalized_top_k)
        return SearchResponse(searched_knowledge_base_ids=selected_ids, results=tuple(interleaved))

    async def _fetch_all(
        self,
        client: httpx.AsyncClient,
        query: str,
        knowledge_base_ids: tuple[str, ...],
    ) -> list[list[SearchResult]]:
        semaphore = asyncio.Semaphore(self._settings.max_concurrency)

        async def fetch(knowledge_base_id: str) -> list[SearchResult]:
            async with semaphore:
                return await self._fetch_one(client, query, knowledge_base_id)

        tasks = [asyncio.create_task(fetch(knowledge_base_id)) for knowledge_base_id in knowledge_base_ids]
        try:
            return list(await asyncio.gather(*tasks))
        except BaseException:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    async def _fetch_one(self, client: httpx.AsyncClient, query: str, knowledge_base_id: str) -> list[SearchResult]:
        try:
            async with client.stream(
                "POST",
                "/knowledge-search",
                params={"resource_urls": "handle"},
                json={"query": query, "knowledge_base_ids": [knowledge_base_id]},
            ) as response:
                if response.status_code != 200:
                    raise SearchError(f"WeKnora search failed with HTTP {response.status_code}")
                body = await _read_bounded_response(response, self._settings.response_limit_bytes)
        except SearchError:
            raise
        except httpx.TimeoutException:
            raise SearchError("WeKnora search timed out") from None
        except httpx.HTTPError:
            raise SearchError("WeKnora search request failed") from None

        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise SearchError("WeKnora returned an invalid JSON response") from None
        return _parse_response(payload, knowledge_base_id, self._settings.max_content_characters)


async def _read_bounded_response(response: httpx.Response, limit: int) -> bytes:
    raw_length = response.headers.get("content-length")
    if raw_length is not None:
        try:
            content_length = int(raw_length)
        except ValueError:
            raise SearchError("WeKnora returned an invalid response length") from None
        if content_length < 0 or content_length > limit:
            raise SearchError("WeKnora response is too large")

    body = bytearray()
    async for chunk in response.aiter_bytes():
        if len(body) + len(chunk) > limit:
            raise SearchError("WeKnora response is too large")
        body.extend(chunk)
    return bytes(body)


def _validate_query(query: str) -> str:
    if not isinstance(query, str):
        raise InvalidSearchRequest("query must be a string")
    normalized = query.strip()
    if not normalized:
        raise InvalidSearchRequest("query must not be empty")
    if len(normalized) > 4000:
        raise InvalidSearchRequest("query must contain at most 4000 characters")
    return normalized


def _validate_top_k(top_k: int) -> int:
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 10:
        raise InvalidSearchRequest("top_k must be an integer between 1 and 10")
    return top_k


def _select_knowledge_base_ids(requested: list[str] | None, allowed: tuple[str, ...]) -> tuple[str, ...]:
    if requested is None:
        return allowed
    if not isinstance(requested, list) or not requested:
        raise InvalidSearchRequest("knowledge_base_ids must be a non-empty list when provided")

    selected: list[str] = []
    for raw_id in requested:
        if not isinstance(raw_id, str):
            raise InvalidSearchRequest("knowledge_base_ids must contain UUID strings")
        try:
            normalized = str(UUID(raw_id))
        except ValueError as exc:
            raise InvalidSearchRequest("knowledge_base_ids must contain UUID strings") from exc
        if normalized not in allowed:
            raise InvalidSearchRequest("knowledge_base_ids contains an unapproved knowledge base")
        if normalized not in selected:
            selected.append(normalized)
    if len(selected) > 8:
        raise InvalidSearchRequest("knowledge_base_ids may contain at most 8 knowledge bases")
    return tuple(selected)


def _parse_response(payload: Any, knowledge_base_id: str, max_content_characters: int) -> list[SearchResult]:
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise SearchError("WeKnora returned an unsuccessful response")
    if "data" not in payload:
        raise SearchError("WeKnora returned an invalid result list")
    data = payload.get("data")
    if data is None:
        return []
    if not isinstance(data, list):
        raise SearchError("WeKnora returned an invalid result list")

    results: list[SearchResult] = []
    seen_chunks: set[str] = set()
    for item in data:
        result = _parse_result(item, knowledge_base_id, max_content_characters)
        if result.chunk_id not in seen_chunks:
            seen_chunks.add(result.chunk_id)
            results.append(result)
    return results


def _parse_result(item: Any, knowledge_base_id: str, max_content_characters: int) -> SearchResult:
    if not isinstance(item, dict):
        raise SearchError("WeKnora returned an invalid search result")
    chunk_id = _required_result_text(item, "id")
    knowledge_id = _required_result_text(item, "knowledge_id")
    content = _required_result_text(item, "content")

    returned_knowledge_base_id = _required_result_text(item, "knowledge_base_id")
    if returned_knowledge_base_id != knowledge_base_id:
        raise SearchError("WeKnora returned a result outside the requested knowledge base")

    title = _optional_result_text(item, "knowledge_title")
    filename = _optional_result_text(item, "knowledge_filename")
    score = _optional_score(item.get("score"))
    chunk_index = _optional_chunk_index(item.get("chunk_index"))
    truncated = len(content) > max_content_characters
    bounded_content = content[:max_content_characters]

    return SearchResult(
        citation=f"weknora:{knowledge_base_id}:{knowledge_id}:{chunk_id}",
        knowledge_base_id=knowledge_base_id,
        knowledge_id=knowledge_id,
        chunk_id=chunk_id,
        title=title,
        filename=filename,
        content=bounded_content,
        score=score,
        chunk_index=chunk_index,
        truncated=truncated,
    )


def _required_result_text(item: dict[str, Any], name: str) -> str:
    value = item.get(name)
    if not isinstance(value, str) or not value.strip():
        raise SearchError("WeKnora returned an invalid search result")
    return value


def _optional_result_text(item: dict[str, Any], name: str) -> str | None:
    value = item.get(name)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise SearchError("WeKnora returned an invalid search result")
    return value


def _optional_score(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SearchError("WeKnora returned an invalid search result")
    score = float(value)
    if not math.isfinite(score):
        raise SearchError("WeKnora returned an invalid search result")
    return score


def _optional_chunk_index(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SearchError("WeKnora returned an invalid search result")
    return value


def _interleave(groups: list[list[SearchResult]], limit: int) -> list[SearchResult]:
    results: list[SearchResult] = []
    depth = 0
    while len(results) < limit:
        appended = False
        for group in groups:
            if depth < len(group):
                results.append(group[depth])
                appended = True
                if len(results) == limit:
                    break
        if not appended:
            break
        depth += 1
    return results
