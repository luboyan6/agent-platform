"""Typed, read-only client for the shared EV supervision Java API."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, time, timedelta
from typing import Any, Protocol, cast

import httpx
from pydantic import ValidationError

from shared_ev_supervision_mcp.models import (
    CaseDetail,
    CaseGridLocation,
    CaseHandle,
    CaseQuestionType,
    CaseQuestionTypeList,
    CaseSearchQuery,
    CaseSearchResult,
    CaseSummary,
    DateQueryWindow,
    HelmetRealtimeMetrics,
    HelmetStatistics,
    HelmetTrendPoint,
    NamedEntity,
    OrderSummaryItem,
    OrderSummaryQuery,
    OrderSummaryResult,
    PatrolAbnormalStatisticsItem,
    PatrolAreaSummaryItem,
    PatrolDataPushItem,
    PatrolGridItem,
    PatrolMacItem,
    PatrolParkingItem,
    PatrolResultDetail,
    PatrolResultSummary,
    PatrolSearchQuery,
    PatrolSearchResult,
    PatrolSectionItem,
    PatrolSectionQuery,
    PatrolSectionResult,
    PatrolSupplierSummaryItem,
    PatrolVehicleItem,
    Supplier,
    SupplierCount,
    SupplierList,
    SupplierNotWearingOrders,
    SupplierWearingRatio,
)


class SharedEvApiError(ValueError):
    """Safe base error: messages never contain credentials or response bodies."""


class UpstreamAuthenticationError(SharedEvApiError):
    pass


class UpstreamUnavailableError(SharedEvApiError):
    pass


class UpstreamProtocolError(SharedEvApiError):
    pass


class UpstreamRejectedError(SharedEvApiError):
    pass


class SharedEvApi(Protocol):
    base_url: str

    async def list_suppliers(self) -> SupplierList: ...

    async def get_helmet_realtime_metrics(
        self,
        supplier_ids: list[int] | None,
        exclude_inaccurate: bool,
    ) -> HelmetRealtimeMetrics: ...

    async def get_helmet_statistics(
        self,
        start_date: date,
        end_date: date,
        supplier_ids: list[int] | None,
        exclude_inaccurate: bool,
    ) -> HelmetStatistics: ...

    async def search_cases(self, query: CaseSearchQuery) -> CaseSearchResult: ...

    async def get_case_detail(self, case_id: int, source_table: str | None) -> CaseDetail: ...

    async def list_case_question_types(self) -> CaseQuestionTypeList: ...

    async def locate_case_grid(self, longitude: float, latitude: float) -> CaseGridLocation: ...

    async def search_patrol_results(self, query: PatrolSearchQuery) -> PatrolSearchResult: ...

    async def get_patrol_result(self, result_id: str) -> PatrolResultDetail: ...

    async def query_patrol_section(self, query: PatrolSectionQuery) -> PatrolSectionResult: ...

    async def get_order_summary(self, query: OrderSummaryQuery) -> OrderSummaryResult: ...


class SharedEvApiClient:
    """Owns all Java payload decoding; MCP tools only see typed models."""

    def __init__(
        self,
        *,
        base_url: str,
        authorization: str,
        timeout_seconds: float = 20.0,
        max_response_bytes: int = 2_000_000,
        request_attempts: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
        today: Callable[[], date] = date.today,
    ) -> None:
        if authorization.strip() != authorization or "\n" in authorization or "\r" in authorization:
            raise ValueError("authorization has invalid surrounding whitespace or control characters")
        self.base_url = base_url.rstrip("/")
        self._max_response_bytes = max_response_bytes
        self._request_attempts = request_attempts
        self._today = today
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": authorization, "Accept": "application/json"},
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def list_suppliers(self) -> SupplierList:
        payload = await self._request("GET", "/biz/supplier/listUI")
        data = _require_list(payload.get("data"), "supplier list")
        suppliers: list[Supplier] = []
        for raw in data:
            item = _require_mapping(raw, "supplier")
            suppliers.append(
                Supplier(
                    supplier_id=_required_positive_int(item.get("id"), "supplier.id"),
                    company_name=_required_string(item.get("companyName"), "supplier.companyName"),
                    company_initial=_optional_string(item.get("companyInitial")),
                )
            )
        return SupplierList(total=len(suppliers), suppliers=suppliers)

    async def get_helmet_realtime_metrics(
        self,
        supplier_ids: list[int] | None,
        exclude_inaccurate: bool,
    ) -> HelmetRealtimeMetrics:
        ids = _normalize_supplier_ids(supplier_ids)
        payload = await self._request(
            "POST",
            "/biz/helmet/query",
            json_body={"supplierIds": ids, "type": 1 if exclude_inaccurate else 0},
        )
        data = _require_mapping(payload.get("data"), "helmet realtime data")
        return _validated(
            HelmetRealtimeMetrics,
            {
                "supplier_ids": ids,
                "exclude_inaccurate": exclude_inaccurate,
                "helmet_total": _required_nonnegative_int(data.get("helmetNum"), "helmetNum"),
                "helmet_in_position": _required_nonnegative_int(data.get("inPositionNum"), "inPositionNum"),
                "helmet_lost": _required_nonnegative_int(data.get("lostNum"), "lostNum"),
                "should_wear": _required_nonnegative_int(data.get("shouldWearNum"), "shouldWearNum"),
                "wearing": _required_nonnegative_int(data.get("wearingNum"), "wearingNum"),
                "not_wearing": _required_nonnegative_int(data.get("notWearingNum"), "notWearingNum"),
                "abnormal": _required_nonnegative_int(data.get("abnormalNum"), "abnormalNum"),
                "inaccurate_vehicle_count": _required_nonnegative_int(data.get("fakeNum"), "fakeNum"),
                "wearing_ratio": _required_ratio(data.get("wearingRatio"), "wearingRatio"),
                "order_total": _required_nonnegative_int(data.get("totalNumInOrder"), "totalNumInOrder"),
                "order_wearing": _required_nonnegative_int(data.get("wearingNumInOrder"), "wearingNumInOrder"),
            },
        )

    async def get_helmet_statistics(
        self,
        start_date: date,
        end_date: date,
        supplier_ids: list[int] | None,
        exclude_inaccurate: bool,
    ) -> HelmetStatistics:
        _validate_date_range(start_date, end_date, maximum_days=366)
        ids = _normalize_supplier_ids(supplier_ids)
        payload = await self._request(
            "POST",
            "/biz/helmet/stat",
            json_body={
                "supplierIds": ids,
                "type": 1 if exclude_inaccurate else 0,
                "startTime": start_date.isoformat(),
                "endTime": end_date.isoformat(),
            },
        )
        data = _require_mapping(payload.get("data"), "helmet statistics")
        fake_vehicles = _supplier_count_series(data.get("fakeNum"), "carNum", "fakeNum")
        fake_orders = _supplier_count_series(data.get("fakeOrderNum"), "orderNum", "fakeOrderNum")
        not_wearing = _not_wearing_series(data.get("helmetNotWornVo"))
        trend = _helmet_trend(data.get("helmetWearingTrendVo"))
        ratios = _helmet_supplier_ratios(data.get("helmetWearingRatioVos"))
        return _validated(
            HelmetStatistics,
            {
                "start_date": start_date,
                "end_date": end_date,
                "supplier_ids": ids,
                "exclude_inaccurate": exclude_inaccurate,
                "inaccurate_vehicles_by_supplier": fake_vehicles,
                "inaccurate_vehicle_orders_by_supplier": fake_orders,
                "not_wearing_orders_by_supplier": not_wearing,
                "wearing_trend": trend,
                "wearing_ratio_by_supplier": ratios,
            },
        )

    async def search_cases(self, query: CaseSearchQuery) -> CaseSearchResult:
        requested_start, requested_end = _resolve_dates(query.start_date, query.end_date, self._today(), default_days=29)
        total, items = await self._fetch_cases(query, requested_start, requested_end)
        effective_start, effective_end = requested_start, requested_end
        fallback_applied = False
        previous_start, previous_end = _previous_calendar_month(self._today())
        if query.fallback_to_previous_month and total == 0 and (requested_start, requested_end) != (previous_start, previous_end):
            total, items = await self._fetch_cases(query, previous_start, previous_end)
            effective_start, effective_end = previous_start, previous_end
            fallback_applied = True
        return CaseSearchResult(
            page=query.page,
            page_size=query.page_size,
            total=total,
            window=_window(requested_start, requested_end, effective_start, effective_end, fallback_applied),
            items=items,
        )

    async def get_case_detail(self, case_id: int, source_table: str | None) -> CaseDetail:
        if case_id <= 0:
            raise ValueError("case_id must be positive")
        if source_table is not None and (not source_table.strip() or len(source_table) > 100):
            raise ValueError("source_table must contain 1-100 characters")
        if source_table is None:
            detail_payload = await self._request("GET", f"/biz/case/{case_id}")
        else:
            detail_payload = await self._request(
                "GET",
                "/biz/case/unionQuery",
                params={"id": str(case_id), "sourceTable": source_table},
            )
        handles_payload = await self._request("GET", f"/biz/case/getCaseHandles/{case_id}")
        detail = _require_mapping(detail_payload.get("data"), "case detail")
        handles_data = _require_list(handles_payload.get("data"), "case handles")
        handles = [_decode_case_handle(_require_mapping(item, "case handle")) for item in handles_data]
        resolved_source_table = source_table or _optional_string(detail.get("sourceTable"))
        return _decode_case_detail(case_id, resolved_source_table, detail, handles)

    async def list_case_question_types(self) -> CaseQuestionTypeList:
        payload = await self._request("GET", "/biz/case/getQuestionType", params={"type": "question_type"})
        data = _require_list(payload.get("data"), "case question types")
        items = []
        for raw in data:
            item = _require_mapping(raw, "case question type")
            items.append(
                CaseQuestionType(
                    type_id=_required_positive_int(item.get("id"), "questionType.id"),
                    value=_required_string(item.get("value"), "questionType.value"),
                    label=_required_string(item.get("label"), "questionType.label"),
                    name=_optional_string(item.get("name")),
                    parent_id=_required_int(item.get("parentId"), "questionType.parentId"),
                    ancestors=_optional_string(item.get("ancestors")),
                    sort=_optional_int(item.get("sort"), "questionType.sort"),
                )
            )
        return CaseQuestionTypeList(items=items)

    async def locate_case_grid(self, longitude: float, latitude: float) -> CaseGridLocation:
        if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
            raise ValueError("longitude or latitude is outside the valid range")
        payload = await self._request(
            "GET",
            "/biz/case/getGridByCoordinate",
            params={
                "centerLng": str(longitude),
                "centerLat": str(latitude),
                "centerLngWgs": str(longitude),
                "centerLatWgs": str(latitude),
            },
        )
        raw = payload.get("data")
        if raw is None:
            return CaseGridLocation(longitude=longitude, latitude=latitude)
        data = _require_mapping(raw, "case grid location")
        return CaseGridLocation(
            longitude=longitude,
            latitude=latitude,
            grid=_decode_named_entity(data.get("grid")),
            cell=_decode_named_entity(data.get("cell")),
            fence=_decode_named_entity(data.get("fence")),
        )

    async def search_patrol_results(self, query: PatrolSearchQuery) -> PatrolSearchResult:
        requested_start, requested_end = _resolve_dates(query.start_date, query.end_date, self._today(), default_days=29)
        total, items = await self._fetch_patrol_results(query, requested_start, requested_end)
        effective_start, effective_end = requested_start, requested_end
        fallback_applied = False
        previous_start, previous_end = _previous_calendar_month(self._today())
        if query.fallback_to_previous_month and total == 0 and (requested_start, requested_end) != (previous_start, previous_end):
            total, items = await self._fetch_patrol_results(query, previous_start, previous_end)
            effective_start, effective_end = previous_start, previous_end
            fallback_applied = True
        return PatrolSearchResult(
            page=query.page,
            page_size=query.page_size,
            total=total,
            window=_window(requested_start, requested_end, effective_start, effective_end, fallback_applied),
            items=items,
        )

    async def get_patrol_result(self, result_id: str) -> PatrolResultDetail:
        normalized_id = _validate_result_id(result_id)
        payload = await self._request("GET", f"/biz/patrolResult/{normalized_id}")
        data = _require_mapping(payload.get("data"), "patrol result detail")
        summary = _decode_patrol_summary(data)
        sub_list = data.get("patrolResultSubList")
        case_codes: list[str] = []
        if sub_list is not None:
            for raw in _require_list(sub_list, "patrol result sub-list"):
                item = _require_mapping(raw, "patrol result sub-item")
                code = _optional_string(item.get("code"))
                if code and code not in case_codes:
                    case_codes.append(code)
        return PatrolResultDetail(**summary.model_dump(), case_codes=case_codes, remark=_optional_string(data.get("remark")))

    async def query_patrol_section(self, query: PatrolSectionQuery) -> PatrolSectionResult:
        if query.section == "area_summary":
            return await self._patrol_summary_section(query, endpoint="area", item_kind="area")
        if query.section == "supplier_summary":
            return await self._patrol_summary_section(query, endpoint="supplier", item_kind="supplier")

        endpoint_by_section = {
            "vehicles": "getEvInfo",
            "grids": "getGridInfo",
            "parking_areas": "getParkInfo",
            "mac_devices": "getMacInfo",
            "data_push": "getDataPushInfo",
            "abnormal_statistics": "abnormalStat",
        }
        endpoint = endpoint_by_section[query.section]
        params = _patrol_section_params(query)
        payload = await self._request("GET", f"/biz/patrolResult/{endpoint}", params=params)
        total, rows = _extract_page(payload, f"patrol {query.section}")
        items = [_decode_patrol_section_item(query.section, _require_mapping(row, f"patrol {query.section} item")) for row in rows]
        return PatrolSectionResult(
            section=query.section,
            result_id=query.result_id,
            page=query.page,
            page_size=query.page_size,
            total=total,
            items=items,
        )

    async def get_order_summary(self, query: OrderSummaryQuery) -> OrderSummaryResult:
        requested_start, requested_end = _resolve_dates(query.start_date, query.end_date, self._today(), default_days=0)
        items = await self._fetch_order_summary(query, requested_start, requested_end)
        effective_start, effective_end = requested_start, requested_end
        fallback_applied = False
        previous_start, previous_end = _previous_calendar_month(self._today())
        if query.fallback_to_previous_month and not items and (requested_start, requested_end) != (previous_start, previous_end):
            items = await self._fetch_order_summary(query, previous_start, previous_end)
            effective_start, effective_end = previous_start, previous_end
            fallback_applied = True
        return OrderSummaryResult(
            page=query.page,
            page_size=query.page_size,
            window=_window(requested_start, requested_end, effective_start, effective_end, fallback_applied),
            items=items,
        )

    async def _fetch_cases(self, query: CaseSearchQuery, start_date: date, end_date: date) -> tuple[int, list[CaseSummary]]:
        params = _without_none(
            {
                "pageNum": query.page,
                "pageSize": query.page_size,
                "dataType": 2,
                "supplierId": query.supplier_id,
                "code": query.case_code,
                "isSimple": query.case_type,
                "source": query.source,
                "subClass": query.problem_subclass,
                "reportBy": query.reporter,
                "processStatuses": ",".join(query.process_statuses) if query.process_statuses else None,
                "isTimeout": query.is_timeout,
                "isAppeal": query.appeal_status,
                "isCheck": query.check_status,
                "params[beginGmtReport]": start_date.isoformat(),
                "params[endGmtReport]": end_date.isoformat(),
            }
        )
        endpoint = "/biz/case/list" if query.scope == "all" else "/biz/case/dealList"
        payload = await self._request("GET", endpoint, params=params)
        total, rows = _extract_page(payload, "case list")
        return total, [_decode_case_summary(_require_mapping(row, "case item")) for row in rows]

    async def _fetch_patrol_results(
        self,
        query: PatrolSearchQuery,
        start_date: date,
        end_date: date,
    ) -> tuple[int, list[PatrolResultSummary]]:
        date_prefix = "GmtPatrolEnd" if query.time_field == "end" else "GmtPatrol"
        params = _without_none(
            {
                "pageNum": query.page,
                "pageSize": query.page_size,
                "id": query.result_id,
                "patrolType": query.patrol_type,
                "patrolContent": query.patrol_content,
                "status": query.status,
                "result": query.result,
                "isWarn": query.is_warn,
                "isCase": query.is_case,
                f"params[begin{date_prefix}]": datetime.combine(start_date, time.min).strftime("%Y-%m-%d %H:%M:%S"),
                f"params[end{date_prefix}]": datetime.combine(end_date, time.max).strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
        payload = await self._request("GET", "/biz/patrolResult/list", params=params)
        total, rows = _extract_page(payload, "patrol result list")
        return total, [_decode_patrol_summary(_require_mapping(row, "patrol result item")) for row in rows]

    async def _patrol_summary_section(
        self,
        query: PatrolSectionQuery,
        *,
        endpoint: str,
        item_kind: str,
    ) -> PatrolSectionResult:
        result_id = _validate_result_id(query.result_id)
        payload = await self._request("GET", f"/biz/patrolResult/{endpoint}/{result_id}")
        rows = _require_list(payload.get("data"), f"patrol {query.section}")
        if item_kind == "area":
            items: list[PatrolSectionItem] = [
                PatrolAreaSummaryItem(
                    name=_required_string(_require_mapping(raw, "patrol area summary").get("name"), "area.name"),
                    value=_required_nonnegative_int(_require_mapping(raw, "patrol area summary").get("value"), "area.value"),
                )
                for raw in rows
            ]
        else:
            items = [
                PatrolSupplierSummaryItem(
                    name=_required_string(_require_mapping(raw, "patrol supplier summary").get("name"), "supplier.name"),
                    value=_required_nonnegative_int(_require_mapping(raw, "patrol supplier summary").get("value"), "supplier.value"),
                )
                for raw in rows
            ]
        return PatrolSectionResult(
            section=query.section,
            result_id=query.result_id,
            page=1,
            page_size=max(1, len(items)),
            total=len(items),
            items=items,
        )

    async def _fetch_order_summary(
        self,
        query: OrderSummaryQuery,
        start_date: date,
        end_date: date,
    ) -> list[OrderSummaryItem]:
        _validate_date_range(start_date, end_date, maximum_days=93)
        payload = await self._request(
            "GET",
            "/biz/summaryOrder/orderReckon",
            params=_without_none(
                {
                    "pageNum": query.page,
                    "pageSize": query.page_size,
                    "supplierId": query.supplier_id,
                    "queryDateStart": start_date.isoformat(),
                    "queryDateEnd": end_date.isoformat(),
                }
            ),
        )
        rows = _require_list(payload.get("data"), "order summary")
        return [_decode_order_summary(_require_mapping(row, "order summary item")) for row in rows]

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, object] | None = None,
        json_body: Mapping[str, object] | None = None,
    ) -> Mapping[str, Any]:
        for attempt in range(self._request_attempts):
            try:
                async with self._client.stream(method, path, params=params, json=json_body) as response:
                    if response.status_code in {401, 403}:
                        raise UpstreamAuthenticationError("shared EV backend rejected the configured authorization")
                    if not 200 <= response.status_code < 300:
                        raise UpstreamRejectedError(f"shared EV backend returned HTTP {response.status_code}")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > self._max_response_bytes:
                            raise UpstreamProtocolError("shared EV backend response exceeds the size limit")
                try:
                    decoded = json.loads(body)
                except (UnicodeError, ValueError):
                    raise UpstreamProtocolError("shared EV backend returned invalid JSON") from None
                payload = _require_mapping(decoded, "response envelope")
                code = payload.get("code")
                if code == 401:
                    raise UpstreamAuthenticationError("shared EV backend rejected the configured authorization")
                if code != 200:
                    safe_code = str(code) if isinstance(code, (int, str)) and len(str(code)) <= 20 else "unknown"
                    raise UpstreamRejectedError(f"shared EV backend rejected the request (business code {safe_code})")
                return payload
            except (UpstreamAuthenticationError, UpstreamProtocolError, UpstreamRejectedError):
                raise
            except httpx.RequestError:
                if attempt + 1 >= self._request_attempts:
                    raise UpstreamUnavailableError("shared EV backend network request failed after limited retries") from None
                await asyncio.sleep(0.25 * (attempt + 1))
        raise AssertionError("unreachable")


def _supplier_count_series(raw: object, count_key: str, name: str) -> list[SupplierCount]:
    data = _require_mapping(raw, name)
    supplier_ids = _require_list(data.get("supplierIds"), f"{name}.supplierIds")
    counts = _require_list(data.get(count_key), f"{name}.{count_key}")
    _require_equal_lengths(name, supplier_ids, counts)
    return [
        SupplierCount(
            supplier_id=_required_positive_int(supplier_id, f"{name}.supplierId"),
            count=_required_nonnegative_int(count, f"{name}.{count_key}"),
        )
        for supplier_id, count in zip(supplier_ids, counts, strict=True)
    ]


def _not_wearing_series(raw: object) -> list[SupplierNotWearingOrders]:
    data = _require_mapping(raw, "helmetNotWornVo")
    supplier_ids = _require_list(data.get("supplierIds"), "helmetNotWornVo.supplierIds")
    orders = _require_list(data.get("orderNums"), "helmetNotWornVo.orderNums")
    not_wearing = _require_list(data.get("notWearingNums"), "helmetNotWornVo.notWearingNums")
    _require_equal_lengths("helmetNotWornVo", supplier_ids, orders, not_wearing)
    return [
        SupplierNotWearingOrders(
            supplier_id=_required_positive_int(supplier_id, "helmetNotWornVo.supplierId"),
            valid_order_count=_required_nonnegative_int(order, "helmetNotWornVo.orderNum"),
            not_wearing_order_count=_required_nonnegative_int(count, "helmetNotWornVo.notWearingNum"),
        )
        for supplier_id, order, count in zip(supplier_ids, orders, not_wearing, strict=True)
    ]


def _helmet_trend(raw: object) -> list[HelmetTrendPoint]:
    data = _require_mapping(raw, "helmetWearingTrendVo")
    dates = _require_list(data.get("times"), "helmetWearingTrendVo.times")
    orders = _require_list(data.get("orderNums"), "helmetWearingTrendVo.orderNums")
    wearing = _require_list(data.get("wearingNums"), "helmetWearingTrendVo.wearingNums")
    ratios = _require_list(data.get("wearingRatios"), "helmetWearingTrendVo.wearingRatios")
    invalid = _require_list(data.get("invalidOrderNums"), "helmetWearingTrendVo.invalidOrderNums")
    _require_equal_lengths("helmetWearingTrendVo", dates, orders, wearing, ratios, invalid)
    return [
        HelmetTrendPoint(
            date=_required_date(day, "helmetWearingTrendVo.time"),
            valid_order_count=_required_nonnegative_int(order, "helmetWearingTrendVo.orderNum"),
            wearing_order_count=_required_nonnegative_int(wearing_count, "helmetWearingTrendVo.wearingNum"),
            wearing_ratio=_required_ratio(ratio, "helmetWearingTrendVo.wearingRatio"),
            invalid_order_count=_required_nonnegative_int(invalid_count, "helmetWearingTrendVo.invalidOrderNum"),
        )
        for day, order, wearing_count, ratio, invalid_count in zip(dates, orders, wearing, ratios, invalid, strict=True)
    ]


def _helmet_supplier_ratios(raw: object) -> list[SupplierWearingRatio]:
    rows = _require_list(raw, "helmetWearingRatioVos")
    return [
        SupplierWearingRatio(
            supplier_id=_required_positive_int(item.get("supplierId"), "helmetWearingRatio.supplierId"),
            wearing_ratio=_required_ratio(item.get("wearingRatio"), "helmetWearingRatio.wearingRatio"),
            message_total=_required_nonnegative_int(item.get("totalNum"), "helmetWearingRatio.totalNum"),
            wearing_message_count=_required_nonnegative_int(item.get("wearingNum"), "helmetWearingRatio.wearingNum"),
        )
        for item in (_require_mapping(row, "helmet wearing ratio") for row in rows)
    ]


def _decode_case_summary(item: Mapping[str, Any]) -> CaseSummary:
    return CaseSummary(
        case_id=_required_positive_int(item.get("id"), "case.id"),
        code=_required_string(item.get("code"), "case.code"),
        source=_optional_string(item.get("source")),
        case_type=_optional_string(item.get("isSimple")),
        problem_type=_optional_string(item.get("type")),
        problem_main_class=_optional_string(item.get("mainClass")),
        problem_subclass=_optional_string(item.get("subClass")),
        supplier_id=_optional_positive_int(item.get("supplierId"), "case.supplierId"),
        supplier_brand=_optional_string(item.get("supplierBrand")),
        moped_count=_optional_nonnegative_int(item.get("carNum"), "case.carNum"),
        bicycle_count=_optional_nonnegative_int(item.get("bicycleNum"), "case.bicycleNum"),
        reporter=_optional_string(item.get("reportBy")),
        address=_optional_string(item.get("addressDetail")),
        reported_at=_optional_datetime(item.get("gmtReport"), "case.gmtReport"),
        is_timeout=_optional_string(item.get("isTimeout")),
        process_status=_optional_string(item.get("processStatus")),
        appeal_status=_optional_string(item.get("isAppeal")),
        check_status=_optional_string(item.get("isCheck")),
        score=_optional_float(item.get("score"), "case.score"),
        source_table=_optional_string(item.get("sourceTable")),
    )


def _decode_case_detail(
    case_id: int,
    source_table: str | None,
    item: Mapping[str, Any],
    handles: list[CaseHandle],
) -> CaseDetail:
    return CaseDetail(
        case_id=case_id,
        source_table=source_table,
        code=_optional_string(item.get("code")),
        source=_optional_string(item.get("source")),
        case_type=_optional_string(item.get("isSimple")),
        problem_type=_optional_string(item.get("type")),
        problem_main_class=_optional_string(item.get("mainClass")),
        problem_subclass=_optional_string(item.get("subClass")),
        supplier_id=_optional_positive_int(item.get("supplierId"), "case.supplierId"),
        supplier_brand=_optional_string(item.get("supplierBrand")),
        moped_count=_optional_nonnegative_int(item.get("carNum"), "case.carNum"),
        bicycle_count=_optional_nonnegative_int(item.get("bicycleNum"), "case.bicycleNum"),
        reporter=_optional_string(item.get("reportBy")),
        reported_at=_optional_datetime(item.get("gmtReport"), "case.gmtReport"),
        address=_optional_string(item.get("addressDetail")),
        longitude=_optional_float(item.get("centerLngWgs", item.get("centerLng")), "case.longitude"),
        latitude=_optional_float(item.get("centerLatWgs", item.get("centerLat")), "case.latitude"),
        grid_name=_optional_string(item.get("gridName")),
        cell_name=_optional_string(item.get("cellName")),
        fence_name=_optional_string(item.get("fenceName")),
        process_status=_optional_string(item.get("processStatus")),
        is_timeout=_optional_string(item.get("isTimeout")),
        appeal_status=_optional_string(item.get("isAppeal")),
        check_status=_optional_string(item.get("isCheck")),
        description=_optional_string(item.get("remark")),
        feedback=_optional_string(item.get("opinion")),
        image_urls=_split_urls(item.get("pics")),
        feedback_image_urls=_split_urls(item.get("dealPics")),
        handles=handles,
    )


def _decode_case_handle(item: Mapping[str, Any]) -> CaseHandle:
    return CaseHandle(
        stage=_optional_string(item.get("stage")),
        operator=_optional_string(item.get("createBy")),
        opinion=_optional_string(item.get("opinion")),
        image_urls=_split_urls(item.get("pics")),
        start_time=_optional_datetime(item.get("startTime"), "caseHandle.startTime"),
        end_time=_optional_datetime(item.get("endTime"), "caseHandle.endTime"),
        remaining_time=_optional_string(item.get("surplusTime")),
        used_time=_optional_string(item.get("usedTime")),
        limit_time=_optional_string(item.get("limitTime")),
    )


def _decode_named_entity(raw: object) -> NamedEntity | None:
    if raw is None:
        return None
    item = _require_mapping(raw, "named entity")
    entity_id = item.get("id")
    if entity_id is not None and not isinstance(entity_id, (int, str)):
        raise UpstreamProtocolError("shared EV backend response does not match the expected schema")
    return NamedEntity(entity_id=entity_id, name=_optional_string(item.get("name")))


def _decode_patrol_summary(item: Mapping[str, Any]) -> PatrolResultSummary:
    return PatrolResultSummary(
        result_id=_required_string(item.get("id"), "patrol.id"),
        patrol_type=_optional_string(item.get("patrolType")),
        patrol_content=_optional_string(item.get("patrolContent")),
        vehicle_types=_decode_string_list(item.get("evType"), "patrol.evType"),
        patrol_started_at=_optional_datetime(item.get("gmtPatrolStart"), "patrol.gmtPatrolStart"),
        patrol_ended_at=_optional_datetime(item.get("gmtPatrolEnd"), "patrol.gmtPatrolEnd"),
        status=_optional_string(item.get("status")),
        result=_optional_string(item.get("result")),
        abnormal_vehicle_count=_optional_nonnegative_int(item.get("evNum"), "patrol.evNum"),
        abnormal_area_count=_optional_nonnegative_int(item.get("areaNum"), "patrol.areaNum"),
        abnormal_data_count=_optional_nonnegative_int(item.get("abnormalDataNum"), "patrol.abnormalDataNum"),
        is_warn=_optional_string(item.get("isWarn")),
        warn_type=_optional_string(item.get("warnType")),
        non_warn_reason=_optional_string(item.get("nonWarnReason")),
        is_case=_optional_string(item.get("isCase")),
        case_count=_optional_nonnegative_int(item.get("caseNum"), "patrol.caseNum"),
        non_case_reason=_optional_string(item.get("nonCaseReason")),
    )


def _patrol_section_params(query: PatrolSectionQuery) -> dict[str, object]:
    common: dict[str, object | None] = {
        "pageNum": query.page,
        "pageSize": query.page_size,
        "resultId": _validate_result_id(query.result_id),
    }
    if query.section == "vehicles":
        common.update(
            supplierId=query.supplier_id,
            plateNo=query.plate_no,
            carId=query.vehicle_id,
            model=query.frame_no,
        )
    elif query.section == "grids":
        common.update(gridName=query.grid_name, cellName=query.cell_name)
    elif query.section == "parking_areas":
        common.update(parkName=query.parking_name, constructionType=query.construction_type)
    elif query.section == "mac_devices":
        common.update(supplierId=query.supplier_id, carId=query.vehicle_id, imeiMac=query.mac_address)
    elif query.section in {"data_push", "abnormal_statistics"}:
        common.update(supplierId=query.supplier_id)
    return _without_none(common)


def _decode_patrol_section_item(section: str, item: Mapping[str, Any]) -> PatrolSectionItem:
    if section == "vehicles":
        return PatrolVehicleItem(
            record_id=_optional_scalar(item.get("id"), "patrolVehicle.id"),
            plate_no=_optional_string(item.get("plateNo")),
            vehicle_id=_optional_string(item.get("carId")),
            frame_no=_optional_string(item.get("model")),
            supplier_id=_optional_positive_int(item.get("supplierId"), "patrolVehicle.supplierId"),
            supplier_brand=_optional_string(item.get("supplierBrand")),
            vehicle_type=_optional_string(item.get("type")),
            case_code=_optional_string(item.get("code")),
            area_name=_optional_string(item.get("areaName")),
            parked_duration=_optional_string(item.get("parkTimeDesc")),
            longitude=_optional_float(item.get("longitude"), "patrolVehicle.longitude"),
            latitude=_optional_float(item.get("latitude"), "patrolVehicle.latitude"),
        )
    if section == "grids":
        return PatrolGridItem(
            grid_name=_optional_string(item.get("gridName")),
            cell_name=_optional_string(item.get("cellName")),
            case_code=_optional_string(item.get("caseCode")),
            supplier_brand=_optional_string(item.get("supplierBrand")),
            parking_capacity=_optional_nonnegative_int(item.get("parkMax"), "patrolGrid.parkMax"),
            actual_vehicle_count=_optional_nonnegative_int(item.get("evNum"), "patrolGrid.evNum"),
        )
    if section == "parking_areas":
        return PatrolParkingItem(
            parking_id=_optional_scalar(item.get("id"), "patrolParking.id"),
            parking_name=_optional_string(item.get("parkName")),
            construction_type=_optional_string(item.get("constructionType")),
            case_code=_optional_string(item.get("caseCode")),
            supplier_brand=_optional_string(item.get("supplierBrand")),
            parking_capacity=_optional_nonnegative_int(item.get("parkMax"), "patrolParking.parkMax"),
            actual_vehicle_count=_optional_nonnegative_int(item.get("evNum"), "patrolParking.evNum"),
        )
    if section == "mac_devices":
        return PatrolMacItem(
            record_id=_optional_scalar(item.get("id"), "patrolMac.id"),
            mac_address=_optional_string(item.get("imeiMac")),
            vehicle_id=_optional_string(item.get("carId")),
            supplier_id=_optional_positive_int(item.get("supplierId"), "patrolMac.supplierId"),
            supplier_brand=_optional_string(item.get("supplierBrand")),
            case_code=_optional_string(item.get("code")),
            abnormal_type=_optional_string(item.get("type")),
            longitude=_optional_float(item.get("longitude"), "patrolMac.longitude"),
            latitude=_optional_float(item.get("latitude"), "patrolMac.latitude"),
        )
    if section == "data_push":
        return PatrolDataPushItem(
            supplier_id=_optional_positive_int(item.get("supplierId"), "patrolDataPush.supplierId"),
            company_name=_optional_string(item.get("companyName")),
            not_pushed_count=_required_nonnegative_int(item.get("notPushedCount"), "patrolDataPush.notPushedCount"),
            delayed_count=_required_nonnegative_int(item.get("delayedCount"), "patrolDataPush.delayedCount"),
        )
    if section == "abnormal_statistics":
        return PatrolAbnormalStatisticsItem(
            supplier_id=_optional_positive_int(item.get("supplierId"), "patrolAbnormal.supplierId"),
            company_initial=_optional_string(item.get("companyInitial")),
            item_count=_required_nonnegative_int(item.get("itemCount"), "patrolAbnormal.itemCount"),
            record_count=_required_nonnegative_int(item.get("recordCount"), "patrolAbnormal.recordCount"),
        )
    raise UpstreamProtocolError("unsupported patrol section decoder")


def _decode_order_summary(item: Mapping[str, Any]) -> OrderSummaryItem:
    return OrderSummaryItem(
        supplier_id=_required_positive_int(item.get("supplierId"), "orderSummary.supplierId"),
        supplier_brand=_required_string(item.get("supplierBrand"), "orderSummary.supplierBrand"),
        total_order_count=_required_nonnegative_int(item.get("allOrderNum"), "orderSummary.allOrderNum"),
        moped_order_count=_required_nonnegative_int(item.get("mopedOrderNum"), "orderSummary.mopedOrderNum"),
        bicycle_order_count=_required_nonnegative_int(item.get("bicycleOrderNum"), "orderSummary.bicycleOrderNum"),
        total_active_vehicle_count=_required_nonnegative_int(item.get("allNum"), "orderSummary.allNum"),
        moped_active_vehicle_count=_required_nonnegative_int(item.get("mopedNum"), "orderSummary.mopedNum"),
        bicycle_active_vehicle_count=_required_nonnegative_int(item.get("bicycleNum"), "orderSummary.bicycleNum"),
        total_average_travel_time=_optional_string(item.get("allAvgTravelTime")),
        moped_average_travel_time=_optional_string(item.get("mopedAvgTravelTime")),
        bicycle_average_travel_time=_optional_string(item.get("bicycleAvgTravelTime")),
        total_average_travel_distance_km=_optional_float(item.get("allAvgTravelDistance"), "orderSummary.allAvgTravelDistance"),
        moped_average_travel_distance_km=_optional_float(item.get("mopedAvgTravelDistance"), "orderSummary.mopedAvgTravelDistance"),
        bicycle_average_travel_distance_km=_optional_float(item.get("bicycleAvgTravelDistance"), "orderSummary.bicycleAvgTravelDistance"),
        total_orders_per_vehicle=_optional_float(item.get("allOrdersPerBike"), "orderSummary.allOrdersPerBike"),
        moped_orders_per_vehicle=_optional_float(item.get("mopedOrdersPerBike"), "orderSummary.mopedOrdersPerBike"),
        bicycle_orders_per_vehicle=_optional_float(item.get("bicycleOrdersPerBike"), "orderSummary.bicycleOrdersPerBike"),
        total_vehicle_utilization=_optional_float(item.get("allOrdersPer"), "orderSummary.allOrdersPer"),
        moped_vehicle_utilization=_optional_float(item.get("mopedOrdersPer"), "orderSummary.mopedOrdersPer"),
        bicycle_vehicle_utilization=_optional_float(item.get("bicycleOrdersPer"), "orderSummary.bicycleOrdersPer"),
    )


def _extract_page(payload: Mapping[str, Any], name: str) -> tuple[int, list[object]]:
    rows = _require_list(payload.get("rows"), f"{name}.rows")
    total = _required_nonnegative_int(payload.get("total"), f"{name}.total")
    return total, rows


def _window(
    requested_start: date,
    requested_end: date,
    effective_start: date,
    effective_end: date,
    fallback_applied: bool,
) -> DateQueryWindow:
    return DateQueryWindow(
        requested_start_date=requested_start,
        requested_end_date=requested_end,
        effective_start_date=effective_start,
        effective_end_date=effective_end,
        fallback_applied=fallback_applied,
    )


def _resolve_dates(start_date: date | None, end_date: date | None, today: date, *, default_days: int) -> tuple[date, date]:
    if start_date is None and end_date is None:
        return today - timedelta(days=default_days), today
    if start_date is None or end_date is None:
        raise ValueError("start_date and end_date must be supplied together")
    return start_date, end_date


def _previous_calendar_month(today: date) -> tuple[date, date]:
    first_of_month = today.replace(day=1)
    end = first_of_month - timedelta(days=1)
    return end.replace(day=1), end


def _validate_date_range(start_date: date, end_date: date, *, maximum_days: int) -> None:
    if start_date > end_date:
        raise ValueError("start_date must not be after end_date")
    if (end_date - start_date).days >= maximum_days:
        raise ValueError(f"date range must be shorter than {maximum_days} days")


def _normalize_supplier_ids(values: list[int] | None) -> list[int]:
    if values is None:
        return []
    if len(values) > 100:
        raise ValueError("supplier_ids must not contain more than 100 entries")
    normalized: list[int] = []
    for value in values:
        if type(value) is not int or value <= 0:
            raise ValueError("supplier_ids must contain positive integers")
        if value not in normalized:
            normalized.append(value)
    return normalized


def _validate_result_id(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 100 or any(character.isspace() for character in normalized):
        raise ValueError("result_id must contain 1-100 non-whitespace characters")
    return normalized


def _require_mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise UpstreamProtocolError(f"shared EV backend {name} does not match the expected schema")
    return cast(Mapping[str, Any], value)


def _require_list(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise UpstreamProtocolError(f"shared EV backend {name} does not match the expected schema")
    return value


def _required_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UpstreamProtocolError(f"shared EV backend {name} does not match the expected schema")
    return value


def _optional_string(value: object) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return str(value)
    raise UpstreamProtocolError("shared EV backend response does not match the expected schema")


def _required_int(value: object, name: str) -> int:
    if isinstance(value, bool):
        raise UpstreamProtocolError(f"shared EV backend {name} does not match the expected schema")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not value.is_integer():
            raise UpstreamProtocolError(f"shared EV backend {name} does not match the expected schema")
        return int(value)
    if not isinstance(value, str):
        raise UpstreamProtocolError(f"shared EV backend {name} does not match the expected schema")
    try:
        number = int(value)
    except (ValueError, OverflowError):
        raise UpstreamProtocolError(f"shared EV backend {name} does not match the expected schema") from None
    return number


def _required_positive_int(value: object, name: str) -> int:
    number = _required_int(value, name)
    if number <= 0:
        raise UpstreamProtocolError(f"shared EV backend {name} does not match the expected schema")
    return number


def _required_nonnegative_int(value: object, name: str) -> int:
    number = _required_int(value, name)
    if number < 0:
        raise UpstreamProtocolError(f"shared EV backend {name} does not match the expected schema")
    return number


def _optional_int(value: object, name: str) -> int | None:
    if value is None or value == "":
        return None
    return _required_int(value, name)


def _optional_positive_int(value: object, name: str) -> int | None:
    if value is None or value == "":
        return None
    return _required_positive_int(value, name)


def _optional_nonnegative_int(value: object, name: str) -> int | None:
    if value is None or value == "":
        return None
    return _required_nonnegative_int(value, name)


def _required_ratio(value: object, name: str) -> float:
    number = _required_float(value, name)
    if not 0 <= number <= 1:
        raise UpstreamProtocolError(f"shared EV backend {name} does not match the expected schema")
    return number


def _required_float(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise UpstreamProtocolError(f"shared EV backend {name} does not match the expected schema")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise UpstreamProtocolError(f"shared EV backend {name} does not match the expected schema") from None
    if number != number or number in {float("inf"), float("-inf")}:
        raise UpstreamProtocolError(f"shared EV backend {name} does not match the expected schema")
    return number


def _optional_float(value: object, name: str) -> float | None:
    if value is None or value == "":
        return None
    return _required_float(value, name)


def _required_date(value: object, name: str) -> date:
    if not isinstance(value, str):
        raise UpstreamProtocolError(f"shared EV backend {name} does not match the expected schema")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise UpstreamProtocolError(f"shared EV backend {name} does not match the expected schema") from None


def _optional_datetime(value: object, name: str) -> datetime | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise UpstreamProtocolError(f"shared EV backend {name} does not match the expected schema")
    normalized = value.strip().replace(" ", "T", 1)
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        raise UpstreamProtocolError(f"shared EV backend {name} does not match the expected schema") from None


def _optional_scalar(value: object, name: str) -> int | str | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise UpstreamProtocolError(f"shared EV backend {name} does not match the expected schema")
    return value


def _decode_string_list(value: object, name: str) -> list[str]:
    if value is None or value == "":
        return []
    decoded = value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except ValueError:
            return [value]
    if not isinstance(decoded, list) or any(not isinstance(item, (str, int)) for item in decoded):
        raise UpstreamProtocolError(f"shared EV backend {name} does not match the expected schema")
    return [str(item) for item in decoded]


def _split_urls(value: object) -> list[str]:
    text = _optional_string(value)
    if text is None:
        return []
    return [item.strip() for item in text.split(",") if item.strip()]


def _require_equal_lengths(name: str, *values: Sequence[object]) -> None:
    if len({len(value) for value in values}) != 1:
        raise UpstreamProtocolError(f"shared EV backend {name} does not match the expected schema")


def _without_none(values: Mapping[str, object | None]) -> dict[str, object]:
    return {key: value for key, value in values.items() if value is not None and value != ""}


def _validated(model: type[Any], values: Mapping[str, object]) -> Any:
    try:
        return model.model_validate(values)
    except ValidationError:
        raise UpstreamProtocolError("shared EV backend response does not match the expected schema") from None
