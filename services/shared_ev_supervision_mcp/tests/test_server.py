from __future__ import annotations

from datetime import date
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from shared_ev_supervision_mcp.config import ServiceSettings
from shared_ev_supervision_mcp.models import (
    CaseDetail,
    CaseGridLocation,
    CaseQuestionTypeList,
    CaseSearchQuery,
    CaseSearchResult,
    HelmetRealtimeMetrics,
    HelmetStatistics,
    OrderSummaryQuery,
    OrderSummaryResult,
    PatrolResultDetail,
    PatrolSearchQuery,
    PatrolSearchResult,
    PatrolSectionQuery,
    PatrolSectionResult,
    SupplierList,
)
from shared_ev_supervision_mcp.server import HttpAccessMiddleware, create_server


class _FakeApiClient:
    base_url = "http://backend.example/prod-api"

    async def list_suppliers(self) -> SupplierList:
        return SupplierList(total=0, suppliers=[])

    async def get_helmet_realtime_metrics(
        self,
        supplier_ids: list[int] | None,
        exclude_inaccurate: bool,
    ) -> HelmetRealtimeMetrics:
        return HelmetRealtimeMetrics(
            supplier_ids=supplier_ids or [],
            exclude_inaccurate=exclude_inaccurate,
            helmet_total=12,
            helmet_in_position=8,
            helmet_lost=4,
            should_wear=7,
            wearing=5,
            not_wearing=2,
            abnormal=1,
            inaccurate_vehicle_count=3,
            wearing_ratio=0.7143,
            order_total=10,
            order_wearing=7,
        )

    async def get_helmet_statistics(
        self,
        start_date: date,
        end_date: date,
        supplier_ids: list[int] | None,
        exclude_inaccurate: bool,
    ) -> HelmetStatistics:
        return HelmetStatistics(
            start_date=start_date,
            end_date=end_date,
            supplier_ids=supplier_ids or [],
            exclude_inaccurate=exclude_inaccurate,
            inaccurate_vehicles_by_supplier=[],
            inaccurate_vehicle_orders_by_supplier=[],
            not_wearing_orders_by_supplier=[],
            wearing_trend=[],
            wearing_ratio_by_supplier=[],
        )

    async def search_cases(self, query: CaseSearchQuery) -> CaseSearchResult:
        return CaseSearchResult.empty(query, date(2026, 9, 20))

    async def get_case_detail(self, case_id: int, source_table: str | None) -> CaseDetail:
        return CaseDetail(case_id=case_id, source_table=source_table, handles=[])

    async def list_case_question_types(self) -> CaseQuestionTypeList:
        return CaseQuestionTypeList(items=[])

    async def locate_case_grid(self, longitude: float, latitude: float) -> CaseGridLocation:
        return CaseGridLocation(longitude=longitude, latitude=latitude)

    async def search_patrol_results(self, query: PatrolSearchQuery) -> PatrolSearchResult:
        return PatrolSearchResult.empty(query, date(2026, 9, 20))

    async def get_patrol_result(self, result_id: str) -> PatrolResultDetail:
        return PatrolResultDetail(result_id=result_id)

    async def query_patrol_section(self, query: PatrolSectionQuery) -> PatrolSectionResult:
        return PatrolSectionResult(
            section=query.section,
            result_id=query.result_id,
            page=query.page,
            page_size=query.page_size,
            total=0,
            items=[],
        )

    async def get_order_summary(self, query: OrderSummaryQuery) -> OrderSummaryResult:
        return OrderSummaryResult.empty(query, date(2026, 9, 20))


@pytest.mark.asyncio
async def test_server_publishes_project_level_tools_with_structured_schemas() -> None:
    server = create_server(_FakeApiClient())

    tools = {tool.name: tool for tool in await server.list_tools()}

    assert set(tools) == {
        "get_api_metadata",
        "list_suppliers",
        "get_helmet_realtime_metrics",
        "get_helmet_statistics",
        "search_cases",
        "get_case_detail",
        "list_case_question_types",
        "locate_case_grid",
        "search_patrol_results",
        "get_patrol_result",
        "query_patrol_result_section",
        "get_order_summary",
    }
    assert tools["get_helmet_statistics"].inputSchema["properties"]["start_date"]["format"] == "date"
    assert tools["get_helmet_statistics"].outputSchema is not None
    assert "wearing_trend" in tools["get_helmet_statistics"].outputSchema["properties"]
    assert tools["get_helmet_realtime_metrics"].annotations is not None
    assert tools["get_helmet_realtime_metrics"].annotations.readOnlyHint is True

    result = await server.call_tool(
        "get_helmet_realtime_metrics",
        {"supplier_ids": [1], "exclude_inaccurate": True},
    )

    assert isinstance(result, tuple)
    _, structured = result
    assert structured["helmet_total"] == 12
    assert structured["supplier_ids"] == [1]


async def _ok_app(scope: dict[str, Any], receive: Any, send: Any) -> None:
    assert scope["type"] == "http"
    await send({"type": "http.response.start", "status": 204, "headers": []})
    await send({"type": "http.response.body", "body": b""})


def _settings(*, host: str = "127.0.0.1", mcp_token: str | None = None) -> ServiceSettings:
    return ServiceSettings(
        api_base_url="http://backend.example/prod-api",
        api_authorization=SecretStr("Bearer synthetic.jwt.value"),
        host=host,
        port=8765,
        mcp_auth_token=SecretStr(mcp_token) if mcp_token else None,
        request_timeout_seconds=20.0,
        max_response_bytes=2_000_000,
    )


@pytest.mark.asyncio
async def test_http_boundary_allows_unauthenticated_health_but_protects_remote_mcp() -> None:
    app = HttpAccessMiddleware(_ok_app, _settings(host="0.0.0.0", mcp_token="synthetic-mcp-token"))
    transport = httpx.ASGITransport(app=app, client=("203.0.113.10", 1234))
    async with httpx.AsyncClient(transport=transport, base_url="http://service.example") as client:
        health = await client.get("/health")
        unauthorized = await client.post("/mcp")
        authorized = await client.post("/mcp", headers={"X-MCP-Auth-Token": "synthetic-mcp-token"})

    assert health.status_code == 200
    assert health.json() == {"status": "ok", "service": "shared-ev-supervision-mcp"}
    assert unauthorized.status_code == 401
    assert authorized.status_code == 204


@pytest.mark.asyncio
async def test_http_boundary_without_service_token_is_loopback_only() -> None:
    app = HttpAccessMiddleware(_ok_app, _settings())
    loopback = httpx.ASGITransport(app=app, client=("127.0.0.1", 1234))
    remote = httpx.ASGITransport(app=app, client=("203.0.113.10", 1234))

    async with httpx.AsyncClient(transport=loopback, base_url="http://service.example") as client:
        local_response = await client.post("/mcp")
    async with httpx.AsyncClient(transport=remote, base_url="http://service.example") as client:
        remote_response = await client.post("/mcp")

    assert local_response.status_code == 204
    assert remote_response.status_code == 401


@pytest.mark.asyncio
async def test_http_boundary_closes_upstream_client_only_at_asgi_shutdown() -> None:
    closed = False

    async def close() -> None:
        nonlocal closed
        closed = True

    async def lifespan_app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        assert scope["type"] == "lifespan"
        assert (await receive())["type"] == "lifespan.startup"
        await send({"type": "lifespan.startup.complete"})
        assert not closed
        assert (await receive())["type"] == "lifespan.shutdown"
        await send({"type": "lifespan.shutdown.complete"})

    messages = iter(
        [
            {"type": "lifespan.startup"},
            {"type": "lifespan.shutdown"},
        ]
    )

    async def receive() -> dict[str, str]:
        return next(messages)

    async def send(_: dict[str, Any]) -> None:
        return None

    app = HttpAccessMiddleware(lifespan_app, _settings(), on_shutdown=close)
    await app({"type": "lifespan"}, receive, send)

    assert closed
