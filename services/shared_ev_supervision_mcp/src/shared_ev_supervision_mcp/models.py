"""Typed public contracts for the shared EV supervision MCP service."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SupplierId = Annotated[int, Field(gt=0, description="运营商 ID")]
PageNumber = Annotated[int, Field(ge=1, description="页码，从 1 开始")]
PageSize = Annotated[int, Field(ge=1, le=100, description="每页条数，最大 100")]


class ContractModel(BaseModel):
    """Base class that keeps tool schemas strict and rejects accidental fields."""

    model_config = ConfigDict(extra="forbid")


class Supplier(ContractModel):
    supplier_id: SupplierId
    company_name: str = Field(description="运营商名称")
    company_initial: str | None = Field(default=None, description="运营商简称或首字母")


class SupplierList(ContractModel):
    total: int = Field(ge=0)
    suppliers: list[Supplier]


class HelmetRealtimeMetrics(ContractModel):
    supplier_ids: list[SupplierId]
    exclude_inaccurate: bool
    helmet_total: int = Field(ge=0, description="头盔总数")
    helmet_in_position: int = Field(ge=0, description="在位头盔数")
    helmet_lost: int = Field(ge=0, description="丢失头盔数")
    should_wear: int = Field(ge=0, description="应佩戴头盔数")
    wearing: int = Field(ge=0, description="佩戴中的头盔数")
    not_wearing: int = Field(ge=0, description="未佩戴头盔数")
    abnormal: int = Field(ge=0, description="异常头盔数")
    inaccurate_vehicle_count: int = Field(ge=0, description="头盔数据不准确车辆数")
    wearing_ratio: float = Field(ge=0, le=1, description="近一小时头盔佩戴比，0 到 1")
    order_total: int = Field(ge=0, description="近一小时消息订单总量")
    order_wearing: int = Field(ge=0, description="近一小时有佩戴消息的订单量")


class SupplierCount(ContractModel):
    supplier_id: SupplierId
    count: int = Field(ge=0)


class SupplierNotWearingOrders(ContractModel):
    supplier_id: SupplierId
    valid_order_count: int = Field(ge=0)
    not_wearing_order_count: int = Field(ge=0)


class SupplierWearingRatio(ContractModel):
    supplier_id: SupplierId
    wearing_ratio: float = Field(ge=0, le=1, description="佩戴比，0 到 1")
    message_total: int = Field(ge=0)
    wearing_message_count: int = Field(ge=0)


class HelmetTrendPoint(ContractModel):
    date: date
    valid_order_count: int = Field(ge=0)
    wearing_order_count: int = Field(ge=0)
    wearing_ratio: float = Field(ge=0, le=1)
    invalid_order_count: int = Field(ge=0)


class HelmetStatistics(ContractModel):
    start_date: date
    end_date: date
    supplier_ids: list[SupplierId]
    exclude_inaccurate: bool
    inaccurate_vehicles_by_supplier: list[SupplierCount]
    inaccurate_vehicle_orders_by_supplier: list[SupplierCount]
    not_wearing_orders_by_supplier: list[SupplierNotWearingOrders]
    wearing_trend: list[HelmetTrendPoint]
    wearing_ratio_by_supplier: list[SupplierWearingRatio]


class DateQueryWindow(ContractModel):
    requested_start_date: date
    requested_end_date: date
    effective_start_date: date
    effective_end_date: date
    fallback_applied: bool = Field(description="首次结果为空后是否改查了上一个自然月")


class CaseSearchQuery(ContractModel):
    page: PageNumber = 1
    page_size: PageSize = 20
    scope: Literal["all", "assigned"] = Field(default="all", description="all 查询全部案件；assigned 查询当前账号待办/可见案件")
    supplier_id: SupplierId | None = None
    case_code: str | None = Field(default=None, max_length=100)
    case_type: str | None = Field(default=None, max_length=20, description="页面字段 isSimple，案件类型字典值")
    source: str | None = Field(default=None, max_length=20, description="案件来源字典值")
    problem_subclass: str | None = Field(default=None, max_length=50, description="问题小类 subClass 字典值")
    reporter: str | None = Field(default=None, max_length=100)
    process_statuses: list[str] = Field(default_factory=list, max_length=20)
    is_timeout: str | None = Field(default=None, max_length=20)
    appeal_status: str | None = Field(default=None, max_length=20)
    check_status: str | None = Field(default=None, max_length=20)
    start_date: date | None = None
    end_date: date | None = None
    fallback_to_previous_month: bool = True

    @model_validator(mode="after")
    def validate_dates(self) -> CaseSearchQuery:
        _validate_date_pair(self.start_date, self.end_date, maximum_days=366)
        return self


class CaseSummary(ContractModel):
    case_id: int = Field(gt=0)
    code: str
    source: str | None = None
    case_type: str | None = None
    problem_type: str | None = None
    problem_main_class: str | None = None
    problem_subclass: str | None = None
    supplier_id: SupplierId | None = None
    supplier_brand: str | None = None
    moped_count: int | None = Field(default=None, ge=0)
    bicycle_count: int | None = Field(default=None, ge=0)
    reporter: str | None = None
    address: str | None = None
    reported_at: datetime | None = None
    is_timeout: str | None = None
    process_status: str | None = None
    appeal_status: str | None = None
    check_status: str | None = None
    score: float | None = None
    source_table: str | None = None


class CaseSearchResult(ContractModel):
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)
    window: DateQueryWindow
    items: list[CaseSummary]

    @classmethod
    def empty(cls, query: CaseSearchQuery, today: date) -> CaseSearchResult:
        start = query.start_date or today - timedelta(days=29)
        end = query.end_date or today
        return cls(
            page=query.page,
            page_size=query.page_size,
            total=0,
            window=DateQueryWindow(
                requested_start_date=start,
                requested_end_date=end,
                effective_start_date=start,
                effective_end_date=end,
                fallback_applied=False,
            ),
            items=[],
        )


class CaseHandle(ContractModel):
    stage: str | None = None
    operator: str | None = None
    opinion: str | None = None
    image_urls: list[str] = Field(default_factory=list)
    start_time: datetime | None = None
    end_time: datetime | None = None
    remaining_time: str | None = None
    used_time: str | None = None
    limit_time: str | None = None


class CaseDetail(ContractModel):
    case_id: int = Field(gt=0)
    source_table: str | None = None
    code: str | None = None
    source: str | None = None
    case_type: str | None = None
    problem_type: str | None = None
    problem_main_class: str | None = None
    problem_subclass: str | None = None
    supplier_id: SupplierId | None = None
    supplier_brand: str | None = None
    moped_count: int | None = Field(default=None, ge=0)
    bicycle_count: int | None = Field(default=None, ge=0)
    reporter: str | None = None
    reported_at: datetime | None = None
    address: str | None = None
    longitude: float | None = None
    latitude: float | None = None
    grid_name: str | None = None
    cell_name: str | None = None
    fence_name: str | None = None
    process_status: str | None = None
    is_timeout: str | None = None
    appeal_status: str | None = None
    check_status: str | None = None
    description: str | None = None
    feedback: str | None = None
    image_urls: list[str] = Field(default_factory=list)
    feedback_image_urls: list[str] = Field(default_factory=list)
    handles: list[CaseHandle]


class CaseQuestionType(ContractModel):
    type_id: int = Field(gt=0)
    value: str
    label: str
    name: str | None = None
    parent_id: int
    ancestors: str | None = None
    sort: int | None = None


class CaseQuestionTypeList(ContractModel):
    items: list[CaseQuestionType]


class NamedEntity(ContractModel):
    entity_id: int | str | None = None
    name: str | None = None


class CaseGridLocation(ContractModel):
    longitude: float
    latitude: float
    grid: NamedEntity | None = None
    cell: NamedEntity | None = None
    fence: NamedEntity | None = None


class PatrolSearchQuery(ContractModel):
    page: PageNumber = 1
    page_size: PageSize = 20
    result_id: str | None = Field(default=None, max_length=100)
    patrol_type: str | None = Field(default=None, max_length=20)
    patrol_content: str | None = Field(default=None, max_length=20)
    status: str | None = Field(default=None, max_length=20)
    result: str | None = Field(default=None, max_length=20)
    is_warn: str | None = Field(default=None, max_length=20)
    is_case: str | None = Field(default=None, max_length=20)
    time_field: Literal["start", "end"] = Field(default="start", description="按巡查开始时间或结束时间过滤")
    start_date: date | None = None
    end_date: date | None = None
    fallback_to_previous_month: bool = True

    @model_validator(mode="after")
    def validate_dates(self) -> PatrolSearchQuery:
        _validate_date_pair(self.start_date, self.end_date, maximum_days=366)
        return self


class PatrolResultSummary(ContractModel):
    result_id: str
    patrol_type: str | None = None
    patrol_content: str | None = None
    vehicle_types: list[str] = Field(default_factory=list)
    patrol_started_at: datetime | None = None
    patrol_ended_at: datetime | None = None
    status: str | None = None
    result: str | None = None
    abnormal_vehicle_count: int | None = Field(default=None, ge=0)
    abnormal_area_count: int | None = Field(default=None, ge=0)
    abnormal_data_count: int | None = Field(default=None, ge=0)
    is_warn: str | None = None
    warn_type: str | None = None
    non_warn_reason: str | None = None
    is_case: str | None = None
    case_count: int | None = Field(default=None, ge=0)
    non_case_reason: str | None = None


class PatrolSearchResult(ContractModel):
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)
    window: DateQueryWindow
    items: list[PatrolResultSummary]

    @classmethod
    def empty(cls, query: PatrolSearchQuery, today: date) -> PatrolSearchResult:
        start = query.start_date or today - timedelta(days=29)
        end = query.end_date or today
        return cls(
            page=query.page,
            page_size=query.page_size,
            total=0,
            window=DateQueryWindow(
                requested_start_date=start,
                requested_end_date=end,
                effective_start_date=start,
                effective_end_date=end,
                fallback_applied=False,
            ),
            items=[],
        )


class PatrolResultDetail(PatrolResultSummary):
    case_codes: list[str] = Field(default_factory=list)
    remark: str | None = None


PatrolSection = Literal[
    "area_summary",
    "supplier_summary",
    "vehicles",
    "grids",
    "parking_areas",
    "mac_devices",
    "data_push",
    "abnormal_statistics",
]


class PatrolSectionQuery(ContractModel):
    result_id: str = Field(min_length=1, max_length=100)
    section: PatrolSection
    page: PageNumber = 1
    page_size: PageSize = 20
    supplier_id: SupplierId | None = None
    plate_no: str | None = Field(default=None, max_length=100)
    vehicle_id: str | None = Field(default=None, max_length=100)
    frame_no: str | None = Field(default=None, max_length=100)
    grid_name: str | None = Field(default=None, max_length=200)
    cell_name: str | None = Field(default=None, max_length=200)
    parking_name: str | None = Field(default=None, max_length=200)
    construction_type: str | None = Field(default=None, max_length=50)
    mac_address: str | None = Field(default=None, max_length=100)


class PatrolAreaSummaryItem(ContractModel):
    kind: Literal["area_summary"] = "area_summary"
    name: str
    value: int = Field(ge=0)


class PatrolSupplierSummaryItem(ContractModel):
    kind: Literal["supplier_summary"] = "supplier_summary"
    name: str
    value: int = Field(ge=0)


class PatrolVehicleItem(ContractModel):
    kind: Literal["vehicle"] = "vehicle"
    record_id: int | str | None = None
    plate_no: str | None = None
    vehicle_id: str | None = None
    frame_no: str | None = None
    supplier_id: SupplierId | None = None
    supplier_brand: str | None = None
    vehicle_type: str | None = None
    case_code: str | None = None
    area_name: str | None = None
    parked_duration: str | None = None
    longitude: float | None = None
    latitude: float | None = None


class PatrolGridItem(ContractModel):
    kind: Literal["grid"] = "grid"
    grid_name: str | None = None
    cell_name: str | None = None
    case_code: str | None = None
    supplier_brand: str | None = None
    parking_capacity: int | None = Field(default=None, ge=0)
    actual_vehicle_count: int | None = Field(default=None, ge=0)


class PatrolParkingItem(ContractModel):
    kind: Literal["parking_area"] = "parking_area"
    parking_id: int | str | None = None
    parking_name: str | None = None
    construction_type: str | None = None
    case_code: str | None = None
    supplier_brand: str | None = None
    parking_capacity: int | None = Field(default=None, ge=0)
    actual_vehicle_count: int | None = Field(default=None, ge=0)


class PatrolMacItem(ContractModel):
    kind: Literal["mac_device"] = "mac_device"
    record_id: int | str | None = None
    mac_address: str | None = None
    vehicle_id: str | None = None
    supplier_id: SupplierId | None = None
    supplier_brand: str | None = None
    case_code: str | None = None
    abnormal_type: str | None = None
    longitude: float | None = None
    latitude: float | None = None


class PatrolDataPushItem(ContractModel):
    kind: Literal["data_push"] = "data_push"
    supplier_id: SupplierId | None = None
    company_name: str | None = None
    not_pushed_count: int = Field(ge=0)
    delayed_count: int = Field(ge=0)


class PatrolAbnormalStatisticsItem(ContractModel):
    kind: Literal["abnormal_statistics"] = "abnormal_statistics"
    supplier_id: SupplierId | None = None
    company_initial: str | None = None
    item_count: int = Field(ge=0)
    record_count: int = Field(ge=0)


PatrolSectionItem = Annotated[
    PatrolAreaSummaryItem
    | PatrolSupplierSummaryItem
    | PatrolVehicleItem
    | PatrolGridItem
    | PatrolParkingItem
    | PatrolMacItem
    | PatrolDataPushItem
    | PatrolAbnormalStatisticsItem,
    Field(discriminator="kind"),
]


class PatrolSectionResult(ContractModel):
    section: PatrolSection
    result_id: str
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)
    items: list[PatrolSectionItem]


class OrderSummaryQuery(ContractModel):
    page: PageNumber = 1
    page_size: PageSize = 20
    supplier_id: SupplierId | None = None
    start_date: date | None = None
    end_date: date | None = None
    fallback_to_previous_month: bool = True

    @model_validator(mode="after")
    def validate_dates(self) -> OrderSummaryQuery:
        _validate_date_pair(self.start_date, self.end_date, maximum_days=93)
        return self


class OrderSummaryItem(ContractModel):
    supplier_id: SupplierId
    supplier_brand: str
    total_order_count: int = Field(ge=0)
    moped_order_count: int = Field(ge=0)
    bicycle_order_count: int = Field(ge=0)
    total_active_vehicle_count: int = Field(ge=0)
    moped_active_vehicle_count: int = Field(ge=0)
    bicycle_active_vehicle_count: int = Field(ge=0)
    total_average_travel_time: str | None = None
    moped_average_travel_time: str | None = None
    bicycle_average_travel_time: str | None = None
    total_average_travel_distance_km: float | None = None
    moped_average_travel_distance_km: float | None = None
    bicycle_average_travel_distance_km: float | None = None
    total_orders_per_vehicle: float | None = None
    moped_orders_per_vehicle: float | None = None
    bicycle_orders_per_vehicle: float | None = None
    total_vehicle_utilization: float | None = Field(default=None, ge=0, description="车均使用率，原始比例值")
    moped_vehicle_utilization: float | None = Field(default=None, ge=0)
    bicycle_vehicle_utilization: float | None = Field(default=None, ge=0)


class OrderSummaryResult(ContractModel):
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    window: DateQueryWindow
    items: list[OrderSummaryItem]

    @classmethod
    def empty(cls, query: OrderSummaryQuery, today: date) -> OrderSummaryResult:
        start = query.start_date or today
        end = query.end_date or today
        return cls(
            page=query.page,
            page_size=query.page_size,
            window=DateQueryWindow(
                requested_start_date=start,
                requested_end_date=end,
                effective_start_date=start,
                effective_end_date=end,
                fallback_applied=False,
            ),
            items=[],
        )


class ApiField(ContractModel):
    name: str
    required: bool
    description: str


class ApiOperation(ContractModel):
    module: Literal["common", "helmet", "case", "patrol", "order"]
    method: Literal["GET", "POST"]
    path: str
    purpose: str
    input_fields: list[ApiField]
    exposed_tool: str | None


class ApiMetadata(ContractModel):
    base_url: str
    authentication: str
    operations: list[ApiOperation]
    limitations: list[str]


def _validate_date_pair(start_date: date | None, end_date: date | None, *, maximum_days: int) -> None:
    if (start_date is None) != (end_date is None):
        raise ValueError("start_date and end_date must be supplied together")
    if start_date is None or end_date is None:
        return
    if start_date > end_date:
        raise ValueError("start_date must not be after end_date")
    if (end_date - start_date).days >= maximum_days:
        raise ValueError(f"date range must be shorter than {maximum_days} days")
