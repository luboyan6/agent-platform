"""Streamable HTTP MCP server for shared EV supervision queries."""

from __future__ import annotations

import ipaddress
import secrets
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Annotated, Any

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.responses import JSONResponse

from shared_ev_supervision_mcp.client import SharedEvApi, SharedEvApiClient
from shared_ev_supervision_mcp.config import ConfigError, ServiceSettings
from shared_ev_supervision_mcp.models import (
    ApiField,
    ApiMetadata,
    ApiOperation,
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
    PatrolSection,
    PatrolSectionQuery,
    PatrolSectionResult,
    SupplierList,
)

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
SupplierIds = Annotated[list[Annotated[int, Field(gt=0)]] | None, Field(default=None, max_length=100)]


def create_server(api: SharedEvApi) -> FastMCP:
    server = FastMCP(
        "shared-ev-supervision",
        instructions=(
            "只读查询共享电动车监管数据。先用 list_suppliers 将运营商名称解析为 ID；日期回退会在结果 window.fallback_applied 中明确标记。"
        ),
        stateless_http=True,
        json_response=True,
        log_level="WARNING",
    )

    @server.tool(
        description="返回已验证的 Java API 路径、参数、对应 MCP 工具及已知限制，不发起业务数据查询。",
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def get_api_metadata() -> ApiMetadata:
        return _api_metadata(api.base_url)

    @server.tool(
        description="查询运营商 ID 与名称。按运营商名称提问时，应先调用本工具解析 supplier_id。",
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def list_suppliers() -> SupplierList:
        return await api.list_suppliers()

    @server.tool(
        description="查询头盔监管实时指标。supplier_ids 为空表示全部运营商；默认排除头盔数据不准确车辆。",
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def get_helmet_realtime_metrics(
        supplier_ids: SupplierIds = None,
        exclude_inaccurate: Annotated[bool, Field(description="是否排除头盔数据不准确车辆")] = True,
    ) -> HelmetRealtimeMetrics:
        return await api.get_helmet_realtime_metrics(supplier_ids, exclude_inaccurate)

    @server.tool(
        description="按日期和运营商查询头盔佩戴趋势、排名、未佩戴订单及数据不准确车辆统计。日期闭区间最长 365 天。",
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def get_helmet_statistics(
        start_date: Annotated[date, Field(description="开始日期，YYYY-MM-DD")],
        end_date: Annotated[date, Field(description="结束日期，YYYY-MM-DD")],
        supplier_ids: SupplierIds = None,
        exclude_inaccurate: Annotated[bool, Field(description="是否排除头盔数据不准确车辆及对应订单")] = True,
    ) -> HelmetStatistics:
        return await api.get_helmet_statistics(start_date, end_date, supplier_ids, exclude_inaccurate)

    @server.tool(
        description=(
            "分页查询案件处理列表，覆盖页面全部筛选项。未给日期时先查含当天的近 30 天；结果为 0 时可显式回退上一个自然月。"
            "scope=all 对应全部案件，scope=assigned 对应当前账号待办/可见案件。"
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def search_cases(
        page: Annotated[int, Field(ge=1)] = 1,
        page_size: Annotated[int, Field(ge=1, le=100)] = 20,
        scope: Annotated[str, Field(pattern="^(all|assigned)$")] = "all",
        supplier_id: Annotated[int | None, Field(gt=0)] = None,
        case_code: Annotated[str | None, Field(max_length=100)] = None,
        case_type: Annotated[str | None, Field(max_length=20, description="案件类型 isSimple 字典值")] = None,
        source: Annotated[str | None, Field(max_length=20, description="案件来源字典值")] = None,
        problem_subclass: Annotated[str | None, Field(max_length=50, description="问题小类 subClass 字典值")] = None,
        reporter: Annotated[str | None, Field(max_length=100)] = None,
        process_statuses: Annotated[list[str], Field(max_length=20)] | None = None,
        is_timeout: Annotated[str | None, Field(max_length=20)] = None,
        appeal_status: Annotated[str | None, Field(max_length=20)] = None,
        check_status: Annotated[str | None, Field(max_length=20)] = None,
        start_date: Annotated[date | None, Field(description="上报开始日期；须与 end_date 同时提供")] = None,
        end_date: Annotated[date | None, Field(description="上报结束日期；须与 start_date 同时提供")] = None,
        fallback_to_previous_month: bool = True,
    ) -> CaseSearchResult:
        query = CaseSearchQuery(
            page=page,
            page_size=page_size,
            scope=scope,
            supplier_id=supplier_id,
            case_code=case_code,
            case_type=case_type,
            source=source,
            problem_subclass=problem_subclass,
            reporter=reporter,
            process_statuses=process_statuses or [],
            is_timeout=is_timeout,
            appeal_status=appeal_status,
            check_status=check_status,
            start_date=start_date,
            end_date=end_date,
            fallback_to_previous_month=fallback_to_previous_month,
        )
        return await api.search_cases(query)

    @server.tool(
        description=(
            "查询单个案件完整详情及流转/处理意见。优先传入 search_cases 返回的 source_table 以使用联合详情查询；"
            "未传时按案件 ID 查询主案件记录。"
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def get_case_detail(
        case_id: Annotated[int, Field(gt=0)],
        source_table: Annotated[str | None, Field(min_length=1, max_length=100)] = None,
    ) -> CaseDetail:
        return await api.get_case_detail(case_id, source_table)

    @server.tool(
        description="查询案件问题类型树的扁平节点，可用于把自然语言问题类型解析为 problem_subclass 字典值。",
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def list_case_question_types() -> CaseQuestionTypeList:
        return await api.list_case_question_types()

    @server.tool(
        description="根据 WGS84 经纬度查询所属责任网格、单元网格和电子围栏。",
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def locate_case_grid(
        longitude: Annotated[float, Field(ge=-180, le=180)],
        latitude: Annotated[float, Field(ge=-90, le=90)],
    ) -> CaseGridLocation:
        return await api.locate_case_grid(longitude, latitude)

    @server.tool(
        description=(
            "分页查询自动巡查记录，覆盖巡查类型、内容、编号、结果、状态、告警、案件和起止日期筛选。"
            "未给日期时先查含当天的近 30 天；结果为 0 时可回退上一个自然月。"
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def search_patrol_results(
        page: Annotated[int, Field(ge=1)] = 1,
        page_size: Annotated[int, Field(ge=1, le=100)] = 20,
        result_id: Annotated[str | None, Field(max_length=100)] = None,
        patrol_type: Annotated[str | None, Field(max_length=20)] = None,
        patrol_content: Annotated[str | None, Field(max_length=20)] = None,
        status: Annotated[str | None, Field(max_length=20)] = None,
        result: Annotated[str | None, Field(max_length=20)] = None,
        is_warn: Annotated[str | None, Field(max_length=20)] = None,
        is_case: Annotated[str | None, Field(max_length=20)] = None,
        time_field: Annotated[str, Field(pattern="^(start|end)$", description="按巡查开始或结束时间过滤")] = "start",
        start_date: Annotated[date | None, Field(description="须与 end_date 同时提供")] = None,
        end_date: Annotated[date | None, Field(description="须与 start_date 同时提供")] = None,
        fallback_to_previous_month: bool = True,
    ) -> PatrolSearchResult:
        query = PatrolSearchQuery(
            page=page,
            page_size=page_size,
            result_id=result_id,
            patrol_type=patrol_type,
            patrol_content=patrol_content,
            status=status,
            result=result,
            is_warn=is_warn,
            is_case=is_case,
            time_field=time_field,
            start_date=start_date,
            end_date=end_date,
            fallback_to_previous_month=fallback_to_previous_month,
        )
        return await api.search_patrol_results(query)

    @server.tool(
        description="按自动巡查编号查询概览详情、异常数量、告警/案件状态及关联案件编号。",
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def get_patrol_result(result_id: Annotated[str, Field(min_length=1, max_length=100)]) -> PatrolResultDetail:
        return await api.get_patrol_result(result_id)

    @server.tool(
        description=(
            "查询某次自动巡查的子结果。section 可选 area_summary、supplier_summary、vehicles、grids、parking_areas、"
            "mac_devices、data_push、abnormal_statistics；其余筛选参数仅对相应 section 生效。"
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def query_patrol_result_section(
        result_id: Annotated[str, Field(min_length=1, max_length=100)],
        section: PatrolSection,
        page: Annotated[int, Field(ge=1)] = 1,
        page_size: Annotated[int, Field(ge=1, le=100)] = 20,
        supplier_id: Annotated[int | None, Field(gt=0)] = None,
        plate_no: Annotated[str | None, Field(max_length=100)] = None,
        vehicle_id: Annotated[str | None, Field(max_length=100)] = None,
        frame_no: Annotated[str | None, Field(max_length=100)] = None,
        grid_name: Annotated[str | None, Field(max_length=200)] = None,
        cell_name: Annotated[str | None, Field(max_length=200)] = None,
        parking_name: Annotated[str | None, Field(max_length=200)] = None,
        construction_type: Annotated[str | None, Field(max_length=50)] = None,
        mac_address: Annotated[str | None, Field(max_length=100)] = None,
    ) -> PatrolSectionResult:
        query = PatrolSectionQuery(
            result_id=result_id,
            section=section,
            page=page,
            page_size=page_size,
            supplier_id=supplier_id,
            plate_no=plate_no,
            vehicle_id=vehicle_id,
            frame_no=frame_no,
            grid_name=grid_name,
            cell_name=cell_name,
            parking_name=parking_name,
            construction_type=construction_type,
            mac_address=mac_address,
        )
        return await api.query_patrol_section(query)

    @server.tool(
        description=(
            "查询订单汇总统计：订单数、骑行车辆数、平均骑行时间/距离、车均订单和使用率。"
            "未给日期时先查当天；结果为空时可回退上一个自然月。日期间隔必须小于 93 天。"
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def get_order_summary(
        page: Annotated[int, Field(ge=1)] = 1,
        page_size: Annotated[int, Field(ge=1, le=100)] = 20,
        supplier_id: Annotated[int | None, Field(gt=0)] = None,
        start_date: Annotated[date | None, Field(description="订单开始日期；须与 end_date 同时提供")] = None,
        end_date: Annotated[date | None, Field(description="订单结束日期；须与 start_date 同时提供")] = None,
        fallback_to_previous_month: bool = True,
    ) -> OrderSummaryResult:
        return await api.get_order_summary(
            OrderSummaryQuery(
                page=page,
                page_size=page_size,
                supplier_id=supplier_id,
                start_date=start_date,
                end_date=end_date,
                fallback_to_previous_month=fallback_to_previous_month,
            )
        )

    return server


class HttpAccessMiddleware:
    """Expose health publicly; keep MCP local-only unless a service token exists."""

    def __init__(
        self,
        application: Any,
        settings: ServiceSettings,
        on_shutdown: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._application = application
        self._token = settings.mcp_auth_token.get_secret_value().encode("utf-8") if settings.mcp_auth_token else None
        self._on_shutdown = on_shutdown

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") == "lifespan":
            try:
                await self._application(scope, receive, send)
            finally:
                if self._on_shutdown is not None:
                    await self._on_shutdown()
            return
        if scope.get("type") != "http":
            await self._application(scope, receive, send)
            return
        path = scope.get("path", "")
        if path == "/health":
            await JSONResponse(
                {"status": "ok", "service": "shared-ev-supervision-mcp"},
                headers={"Cache-Control": "no-store"},
            )(scope, receive, send)
            return
        if (path == "/mcp" or path.startswith("/mcp/")) and not self._authorized(scope):
            await JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"Cache-Control": "no-store"},
            )(scope, receive, send)
            return
        await self._application(scope, receive, send)

    def _authorized(self, scope: dict[str, Any]) -> bool:
        if self._token is None:
            client = scope.get("client")
            if not isinstance(client, (tuple, list)) or not client or not isinstance(client[0], str):
                return False
            try:
                return ipaddress.ip_address(client[0]).is_loopback
            except ValueError:
                return client[0].lower() == "localhost"
        values = [value for name, value in scope.get("headers", []) if name.lower() == b"x-mcp-auth-token"]
        return len(values) == 1 and secrets.compare_digest(values[0], self._token)


def build_http_app(settings: ServiceSettings) -> HttpAccessMiddleware:
    client = SharedEvApiClient(
        base_url=settings.api_base_url,
        authorization=settings.api_authorization.get_secret_value(),
        timeout_seconds=settings.request_timeout_seconds,
        max_response_bytes=settings.max_response_bytes,
        request_attempts=settings.request_attempts,
    )
    server = create_server(client)
    return HttpAccessMiddleware(server.streamable_http_app(), settings, on_shutdown=client.aclose)


def main() -> None:
    try:
        settings = ServiceSettings.from_environ()
    except ConfigError as error:
        raise SystemExit(f"configuration error: {error}") from None
    uvicorn.run(
        build_http_app(settings),
        host=settings.host,
        port=settings.port,
        log_level="info",
        access_log=False,
    )


def _api_metadata(base_url: str) -> ApiMetadata:
    field = ApiField
    operations = [
        ApiOperation(
            module="common",
            method="GET",
            path="/biz/supplier/listUI",
            purpose="运营商 ID、名称和展示信息",
            input_fields=[],
            exposed_tool="list_suppliers",
        ),
        ApiOperation(
            module="helmet",
            method="POST",
            path="/biz/helmet/query",
            purpose="头盔实时指标",
            input_fields=[
                field(name="supplierIds", required=True, description="运营商 ID 数组，空数组表示全部"),
                field(name="type", required=True, description="1 排除数据不准确车辆，0 不排除"),
            ],
            exposed_tool="get_helmet_realtime_metrics",
        ),
        ApiOperation(
            module="helmet",
            method="POST",
            path="/biz/helmet/stat",
            purpose="头盔历史统计",
            input_fields=[
                field(name="startTime", required=True, description="YYYY-MM-DD"),
                field(name="endTime", required=True, description="YYYY-MM-DD"),
                field(name="supplierIds", required=True, description="运营商 ID 数组"),
                field(name="type", required=True, description="排除标记"),
            ],
            exposed_tool="get_helmet_statistics",
        ),
        ApiOperation(
            module="case",
            method="GET",
            path="/biz/case/list | /biz/case/dealList",
            purpose="全部案件或当前账号待办/可见案件分页查询",
            input_fields=[
                field(name="pageNum/pageSize", required=True, description="分页"),
                field(
                    name="params[beginGmtReport]/params[endGmtReport]",
                    required=False,
                    description="上报日期范围",
                ),
                field(
                    name="其他筛选",
                    required=False,
                    description="运营商、编号、类型、来源、问题类型、上报人及状态",
                ),
            ],
            exposed_tool="search_cases",
        ),
        ApiOperation(
            module="case",
            method="GET",
            path="/biz/case/{id} | /biz/case/unionQuery + /biz/case/getCaseHandles/{id}",
            purpose="案件详情和处理记录",
            input_fields=[
                field(name="id", required=True, description="案件 ID"),
                field(name="sourceTable", required=False, description="联合查询所需的案件来源表"),
            ],
            exposed_tool="get_case_detail",
        ),
        ApiOperation(
            module="case",
            method="GET",
            path="/biz/case/getQuestionType",
            purpose="案件问题类型",
            input_fields=[field(name="type", required=True, description="固定 question_type")],
            exposed_tool="list_case_question_types",
        ),
        ApiOperation(
            module="case",
            method="GET",
            path="/biz/case/getGridByCoordinate",
            purpose="坐标所属网格/围栏",
            input_fields=[field(name="centerLng/centerLat", required=True, description="WGS84 经纬度")],
            exposed_tool="locate_case_grid",
        ),
        ApiOperation(
            module="patrol",
            method="GET",
            path="/biz/patrolResult/list",
            purpose="自动巡查记录分页查询",
            input_fields=[
                field(name="pageNum/pageSize", required=True, description="分页"),
                field(
                    name="params[beginGmtPatrol]/params[endGmtPatrol]",
                    required=False,
                    description="巡查时间范围",
                ),
                field(
                    name="其他筛选",
                    required=False,
                    description="类型、内容、编号、结果、状态、告警和案件",
                ),
            ],
            exposed_tool="search_patrol_results",
        ),
        ApiOperation(
            module="patrol",
            method="GET",
            path="/biz/patrolResult/{id}",
            purpose="自动巡查概览详情",
            input_fields=[field(name="id", required=True, description="自动巡查编号")],
            exposed_tool="get_patrol_result",
        ),
        ApiOperation(
            module="patrol",
            method="GET",
            path="/biz/patrolResult/{area|supplier|getEvInfo|getGridInfo|getParkInfo|getMacInfo|getDataPushInfo|abnormalStat}",
            purpose="自动巡查的区域、运营商及各类异常明细",
            input_fields=[
                field(name="resultId", required=True, description="自动巡查编号"),
                field(
                    name="section filters",
                    required=False,
                    description="运营商、车辆、网格、停车区或 MAC 筛选",
                ),
            ],
            exposed_tool="query_patrol_result_section",
        ),
        ApiOperation(
            module="order",
            method="GET",
            path="/biz/summaryOrder/orderReckon",
            purpose="订单汇总统计",
            input_fields=[
                field(
                    name="queryDateStart/queryDateEnd",
                    required=True,
                    description="订单日期范围，小于 93 天",
                ),
                field(name="supplierId", required=False, description="运营商 ID"),
            ],
            exposed_tool="get_order_summary",
        ),
    ]
    return ApiMetadata(
        base_url=base_url,
        authentication="Authorization: Bearer <server-side access token>",
        operations=operations,
        limitations=[
            "四个业务模块统一使用同一个配置的 Java Base URL，不做跨后端自动切换。",
            "已确认的头盔接口没有路口/道路筛选字段，因此不能声称支持按路口查询。",
            "导出、删除、案件处置、评分等写入或文件下载操作未暴露为只读 MCP 查询工具。",
        ],
    )


if __name__ == "__main__":
    main()
