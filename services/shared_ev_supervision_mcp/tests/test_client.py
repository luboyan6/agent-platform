from __future__ import annotations

from datetime import date

import httpx
import pytest

from shared_ev_supervision_mcp.client import SharedEvApiClient, UpstreamAuthenticationError, UpstreamProtocolError
from shared_ev_supervision_mcp.models import CaseSearchQuery, OrderSummaryQuery, PatrolSectionQuery


def _response(data: object, *, code: int = 200, message: str = "操作成功") -> httpx.Response:
    return httpx.Response(200, json={"code": code, "msg": message, "data": data})


@pytest.mark.asyncio
async def test_realtime_query_sends_frontend_contract_and_normalizes_numeric_strings() -> None:
    seen_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_request
        seen_request = request
        return _response(
            {
                "supplierIds": [1],
                "type": 1,
                "helmetNum": "12",
                "inPositionNum": "8",
                "lostNum": "4",
                "shouldWearNum": "7",
                "wearingNum": "5",
                "notWearingNum": "2",
                "abnormalNum": "1",
                "fakeNum": "3",
                "wearingRatio": "0.7143",
                "totalNumInOrder": "10",
                "wearingNumInOrder": "7",
            }
        )

    client = SharedEvApiClient(
        base_url="http://backend.example/prod-api",
        authorization="Bearer synthetic.jwt.value",
        transport=httpx.MockTransport(handler),
    )

    result = await client.get_helmet_realtime_metrics(supplier_ids=[1], exclude_inaccurate=True)

    assert seen_request is not None
    assert seen_request.url.path == "/prod-api/biz/helmet/query"
    assert seen_request.headers["authorization"] == "Bearer synthetic.jwt.value"
    assert seen_request.headers["content-type"] == "application/json"
    assert seen_request.content == b'{"supplierIds":[1],"type":1}'
    assert result.helmet_total == 12
    assert result.wearing_ratio == 0.7143
    assert result.order_total == 10


@pytest.mark.asyncio
async def test_statistics_normalize_the_confirmed_30_day_response_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/prod-api/biz/helmet/stat"
        assert request.content == (b'{"supplierIds":[],"type":1,"startTime":"2026-08-22","endTime":"2026-09-20"}')
        return _response(
            {
                "supplierIds": [],
                "type": 1,
                "startTime": "2026-08-22",
                "endTime": "2026-09-20",
                "fakeNum": {"supplierIds": [1, 3], "carNum": ["2", "1"]},
                "fakeOrderNum": {"supplierIds": [1, 3], "orderNum": ["9", "4"]},
                "helmetWearingRatioVos": [{"supplierId": 1, "wearingRatio": "0.7500", "totalNum": "20", "wearingNum": "15"}],
                "helmetWearingTrendVo": {
                    "times": ["2026-08-22", "2026-09-20"],
                    "orderNums": ["10", "20"],
                    "wearingNums": ["7", "15"],
                    "wearingRatios": ["0.7000", "0.7500"],
                    "invalidOrderNums": ["1", "2"],
                },
                "helmetNotWornVo": {
                    "supplierIds": [1, 3],
                    "orderNums": ["10", "20"],
                    "notWearingNums": ["3", "5"],
                },
            }
        )

    client = SharedEvApiClient(
        base_url="http://backend.example/prod-api",
        authorization="Bearer synthetic.jwt.value",
        transport=httpx.MockTransport(handler),
    )

    result = await client.get_helmet_statistics(
        start_date=date(2026, 8, 22),
        end_date=date(2026, 9, 20),
        supplier_ids=None,
        exclude_inaccurate=True,
    )

    assert result.start_date == date(2026, 8, 22)
    assert result.end_date == date(2026, 9, 20)
    assert result.inaccurate_vehicles_by_supplier[0].count == 2
    assert result.inaccurate_vehicle_orders_by_supplier[1].count == 4
    assert result.wearing_ratio_by_supplier[0].wearing_ratio == 0.75
    assert result.wearing_trend[-1].date == date(2026, 9, 20)
    assert result.wearing_trend[-1].invalid_order_count == 2
    assert result.not_wearing_orders_by_supplier[-1].not_wearing_order_count == 5


@pytest.mark.asyncio
async def test_statistics_reject_misaligned_parallel_arrays() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return _response(
            {
                "supplierIds": [],
                "type": 1,
                "startTime": "2026-08-22",
                "endTime": "2026-09-20",
                "fakeNum": {"supplierIds": [1, 3], "carNum": ["2"]},
                "fakeOrderNum": {"supplierIds": [], "orderNum": []},
                "helmetWearingRatioVos": [],
                "helmetWearingTrendVo": {
                    "times": [],
                    "orderNums": [],
                    "wearingNums": [],
                    "wearingRatios": [],
                    "invalidOrderNums": [],
                },
                "helmetNotWornVo": {"supplierIds": [], "orderNums": [], "notWearingNums": []},
            }
        )

    client = SharedEvApiClient(
        base_url="http://backend.example/prod-api",
        authorization="Bearer synthetic.jwt.value",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(UpstreamProtocolError, match="schema"):
        await client.get_helmet_statistics(
            start_date=date(2026, 8, 22),
            end_date=date(2026, 9, 20),
            supplier_ids=[],
            exclude_inaccurate=True,
        )


@pytest.mark.asyncio
async def test_business_authentication_error_never_echoes_secret_or_backend_message() -> None:
    secret = "synthetic.jwt.value"

    def handler(_: httpx.Request) -> httpx.Response:
        return _response(None, code=401, message=f"expired {secret}")

    client = SharedEvApiClient(
        base_url="http://backend.example/prod-api",
        authorization=f"Bearer {secret}",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(UpstreamAuthenticationError) as error:
        await client.list_suppliers()

    assert secret not in str(error.value)
    assert "expired" not in str(error.value)


@pytest.mark.asyncio
async def test_supplier_list_returns_only_conversation_relevant_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/prod-api/biz/supplier/listUI"
        return _response(
            [
                {
                    "id": 1,
                    "companyInitial": "MT",
                    "companyName": "示例运营商",
                    "bikeLogo": "https://private.example/logo.png",
                    "bikeColor": "yellow",
                    "ebikeLogo": "https://private.example/e-logo.png",
                    "ebikeColor": "blue",
                }
            ]
        )

    client = SharedEvApiClient(
        base_url="http://backend.example/prod-api",
        authorization="Bearer synthetic.jwt.value",
        transport=httpx.MockTransport(handler),
    )

    result = await client.list_suppliers()

    assert result.total == 1
    assert result.suppliers[0].supplier_id == 1
    assert result.suppliers[0].company_name == "示例运营商"
    assert "logo" not in result.model_dump_json().lower()


@pytest.mark.asyncio
async def test_case_search_uses_the_page_filters_and_nested_date_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/prod-api/biz/case/list"
        assert request.url.params["dataType"] == "2"
        assert request.url.params["supplierId"] == "3"
        assert request.url.params["processStatuses"] == "1,5"
        assert request.url.params["params[beginGmtReport]"] == "2026-08-22"
        assert request.url.params["params[endGmtReport]"] == "2026-09-20"
        return httpx.Response(
            200,
            json={
                "code": 200,
                "msg": "查询成功",
                "total": 1,
                "rows": [
                    {
                        "id": 9,
                        "code": "CASE-9",
                        "source": "10",
                        "isSimple": "2",
                        "subClass": "4",
                        "supplierId": 3,
                        "supplierBrand": "示例运营商",
                        "gmtReport": "2026-09-01 12:00:00",
                        "processStatus": "1",
                        "sourceTable": "biz_case",
                    }
                ],
            },
        )

    client = SharedEvApiClient(
        base_url="http://backend.example/prod-api",
        authorization="Bearer synthetic.jwt.value",
        transport=httpx.MockTransport(handler),
        today=lambda: date(2026, 9, 20),
    )

    result = await client.search_cases(
        CaseSearchQuery(
            supplier_id=3,
            process_statuses=["1", "5"],
            start_date=date(2026, 8, 22),
            end_date=date(2026, 9, 20),
        )
    )

    assert result.total == 1
    assert result.items[0].case_id == 9
    assert result.items[0].source_table == "biz_case"
    assert result.window.fallback_applied is False


@pytest.mark.asyncio
async def test_case_search_default_window_is_thirty_inclusive_calendar_days() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["params[beginGmtReport]"] == "2026-08-22"
        assert request.url.params["params[endGmtReport]"] == "2026-09-20"
        return httpx.Response(200, json={"code": 200, "msg": "查询成功", "total": 0, "rows": []})

    client = SharedEvApiClient(
        base_url="http://backend.example/prod-api",
        authorization="Bearer synthetic.jwt.value",
        transport=httpx.MockTransport(handler),
        today=lambda: date(2026, 9, 20),
    )

    result = await client.search_cases(CaseSearchQuery(fallback_to_previous_month=False))

    assert result.window.requested_start_date == date(2026, 8, 22)
    assert result.window.requested_end_date == date(2026, 9, 20)


@pytest.mark.asyncio
async def test_case_detail_without_source_table_uses_the_primary_record_endpoint() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/prod-api/biz/case/17":
            return _response({"id": 17, "code": "CASE-17", "sourceTable": "biz_case"})
        if request.url.path == "/prod-api/biz/case/getCaseHandles/17":
            return _response([])
        raise AssertionError(f"unexpected path: {request.url.path}")

    client = SharedEvApiClient(
        base_url="http://backend.example/prod-api",
        authorization="Bearer synthetic.jwt.value",
        transport=httpx.MockTransport(handler),
    )

    result = await client.get_case_detail(17, None)

    assert paths == ["/prod-api/biz/case/17", "/prod-api/biz/case/getCaseHandles/17"]
    assert result.case_id == 17
    assert result.source_table == "biz_case"
    assert result.handles == []


@pytest.mark.asyncio
async def test_empty_order_summary_retries_only_the_previous_calendar_month() -> None:
    requested_ranges: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_ranges.append((request.url.params["queryDateStart"], request.url.params["queryDateEnd"]))
        if len(requested_ranges) == 1:
            return _response([])
        return _response(
            [
                {
                    "supplierId": "1",
                    "supplierBrand": "示例运营商",
                    "allOrderNum": 12,
                    "mopedOrderNum": 12,
                    "bicycleOrderNum": 0,
                    "allNum": 6,
                    "mopedNum": 6,
                    "bicycleNum": 0,
                    "allAvgTravelTime": "00:12:30",
                    "mopedAvgTravelTime": "00:12:30",
                    "bicycleAvgTravelTime": None,
                    "allAvgTravelDistance": "1.25",
                    "mopedAvgTravelDistance": "1.25",
                    "bicycleAvgTravelDistance": None,
                    "allOrdersPerBike": "2.0",
                    "mopedOrdersPerBike": "2.0",
                    "bicycleOrdersPerBike": None,
                    "allOrdersPer": "0.4",
                    "mopedOrdersPer": "0.4",
                    "bicycleOrdersPer": None,
                }
            ]
        )

    client = SharedEvApiClient(
        base_url="http://backend.example/prod-api",
        authorization="Bearer synthetic.jwt.value",
        transport=httpx.MockTransport(handler),
        today=lambda: date(2026, 9, 20),
    )

    result = await client.get_order_summary(OrderSummaryQuery())

    assert requested_ranges == [("2026-09-20", "2026-09-20"), ("2026-08-01", "2026-08-31")]
    assert result.window.fallback_applied is True
    assert result.window.effective_start_date == date(2026, 8, 1)
    assert result.items[0].total_order_count == 12
    assert result.items[0].total_orders_per_vehicle == 2.0


@pytest.mark.asyncio
async def test_patrol_section_routes_vehicle_filters_without_returning_raw_payloads() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/prod-api/biz/patrolResult/getEvInfo"
        assert request.url.params["resultId"] == "PATROL-1"
        assert request.url.params["plateNo"] == "TEST-001"
        return httpx.Response(
            200,
            json={
                "code": 200,
                "msg": "查询成功",
                "total": 1,
                "rows": [
                    {
                        "id": 7,
                        "plateNo": "TEST-001",
                        "carId": "CAR-1",
                        "model": "FRAME-1",
                        "supplierId": 1,
                        "supplierBrand": "示例运营商",
                        "type": "1",
                        "code": "CASE-1",
                        "areaName": "示例区域",
                        "parkTimeDesc": "10分钟",
                    }
                ],
            },
        )

    client = SharedEvApiClient(
        base_url="http://backend.example/prod-api",
        authorization="Bearer synthetic.jwt.value",
        transport=httpx.MockTransport(handler),
    )

    result = await client.query_patrol_section(PatrolSectionQuery(result_id="PATROL-1", section="vehicles", plate_no="TEST-001"))

    assert result.total == 1
    assert result.items[0].kind == "vehicle"
    assert result.items[0].vehicle_id == "CAR-1"


@pytest.mark.asyncio
async def test_patrol_section_decoders_cover_every_detail_tab_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/prod-api/biz/patrolResult/area/PATROL-2":
            return _response([{"name": "禁停区 A", "value": 4}])
        if path == "/prod-api/biz/patrolResult/supplier/PATROL-2":
            return _response([{"name": "示例运营商", "value": 3}])
        rows_by_path = {
            "/prod-api/biz/patrolResult/getGridInfo": {
                "gridName": "责任网格",
                "cellName": "单元网格",
                "caseCode": "CASE-GRID",
                "supplierBrand": "示例运营商",
                "parkMax": 20,
                "evNum": 21,
            },
            "/prod-api/biz/patrolResult/getParkInfo": {
                "id": 8,
                "parkName": "停车区",
                "constructionType": "1",
                "caseCode": "CASE-PARK",
                "supplierBrand": "示例运营商",
                "parkMax": 20,
                "evNum": 22,
            },
            "/prod-api/biz/patrolResult/getMacInfo": {
                "id": 9,
                "imeiMac": "00:11:22:33:44:55",
                "carId": "CAR-2",
                "supplierId": 1,
                "supplierBrand": "示例运营商",
                "code": "CASE-MAC",
                "type": "未备案",
                "longitude": 117.1,
                "latitude": 36.7,
            },
            "/prod-api/biz/patrolResult/getDataPushInfo": {
                "supplierId": 1,
                "companyName": "示例运营商",
                "notPushedCount": 5,
                "delayedCount": 2,
            },
            "/prod-api/biz/patrolResult/abnormalStat": {
                "supplierId": 1,
                "companyInitial": "示例",
                "itemCount": 6,
                "recordCount": 9,
            },
        }
        if path in rows_by_path:
            return httpx.Response(200, json={"code": 200, "msg": "查询成功", "total": 1, "rows": [rows_by_path[path]]})
        raise AssertionError(f"unexpected path: {path}")

    client = SharedEvApiClient(
        base_url="http://backend.example/prod-api",
        authorization="Bearer synthetic.jwt.value",
        transport=httpx.MockTransport(handler),
    )

    results = {
        section: await client.query_patrol_section(PatrolSectionQuery(result_id="PATROL-2", section=section))
        for section in (
            "area_summary",
            "supplier_summary",
            "grids",
            "parking_areas",
            "mac_devices",
            "data_push",
            "abnormal_statistics",
        )
    }

    assert results["area_summary"].items[0].kind == "area_summary"
    assert results["supplier_summary"].items[0].kind == "supplier_summary"
    assert results["grids"].items[0].actual_vehicle_count == 21
    assert results["parking_areas"].items[0].parking_id == 8
    assert results["mac_devices"].items[0].mac_address == "00:11:22:33:44:55"
    assert results["data_push"].items[0].not_pushed_count == 5
    assert results["abnormal_statistics"].items[0].record_count == 9


@pytest.mark.asyncio
async def test_network_retry_never_changes_the_configured_backend() -> None:
    requested_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(request.url.host)
        if len(requested_hosts) == 1:
            raise httpx.ConnectError("synthetic refusal", request=request)
        return _response([])

    client = SharedEvApiClient(
        base_url="http://backend-a.example/prod-api",
        authorization="Bearer synthetic.jwt.value",
        request_attempts=2,
        transport=httpx.MockTransport(handler),
    )

    result = await client.list_suppliers()

    assert result.total == 0
    assert requested_hosts == ["backend-a.example", "backend-a.example"]
