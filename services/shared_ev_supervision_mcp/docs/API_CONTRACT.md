# API 与 MCP 契约

## 公共约束

- 四个业务模块只使用 `SHARED_EV_API_BASE_URL` 指定的同一 Java 后端；不存在备用地址配置或跨后端回退。
- Java 鉴权固定为服务端注入的 `Authorization: Bearer <access_token>`。
- 分页参数在 MCP 中为 `page`、`page_size`，映射为 Java 的 `pageNum`、`pageSize`。
- MCP 输出使用 snake_case，并把 Java 返回的数字字符串校验、转换为整数或浮点数。
- Java 的 HTTP 错误、业务 `code != 200`、鉴权失败、超时、过大响应和 Schema 偏差会显式报错，不会伪装成空结果。

## 运营商

### `list_suppliers`

- Java：`GET /biz/supplier/listUI`
- 输入：无
- 输出：`total`；`suppliers[]` 包含 `supplier_id`、`company_name`、`company_initial`

## 头盔监管

### `get_helmet_realtime_metrics`

- Java：`POST /biz/helmet/query`
- JSON：`supplierIds: number[]`、`type: 0 | 1`
- MCP 输入：`supplier_ids`；`exclude_inaccurate`（映射到 `type`）
- MCP 输出：`helmet_total`、`helmet_in_position`、`helmet_lost`、`should_wear`、`wearing`、`not_wearing`、`abnormal`、`inaccurate_vehicle_count`、`wearing_ratio`、`order_total`、`order_wearing`

### `get_helmet_statistics`

- Java：`POST /biz/helmet/stat`
- JSON：`startTime`、`endTime`、`supplierIds`、`type`
- MCP 输入：`start_date`、`end_date`、`supplier_ids`、`exclude_inaccurate`
- MCP 输出：
  - `inaccurate_vehicles_by_supplier[]`: `supplier_id`、`count`
  - `inaccurate_vehicle_orders_by_supplier[]`: `supplier_id`、`count`
  - `not_wearing_orders_by_supplier[]`: `supplier_id`、`valid_order_count`、`not_wearing_order_count`
  - `wearing_trend[]`: `date`、`valid_order_count`、`wearing_order_count`、`wearing_ratio`、`invalid_order_count`
  - `wearing_ratio_by_supplier[]`: `supplier_id`、`wearing_ratio`、`message_total`、`wearing_message_count`

## 案件处理

### `search_cases`

- Java：管理员范围 `GET /biz/case/list`；当前账号范围 `GET /biz/case/dealList`
- 固定参数：`dataType=2`
- MCP 到 Java 筛选映射：

| MCP | Java |
| --- | --- |
| `case_code` | `code` |
| `case_type` | `isSimple` |
| `source` | `source` |
| `problem_subclass` | `subClass` |
| `reporter` | `reportBy` |
| `process_statuses[]` | 逗号拼接后的 `processStatuses` |
| `is_timeout` | `isTimeout` |
| `supplier_id` | `supplierId` |
| `appeal_status` | `isAppeal` |
| `check_status` | `isCheck` |
| `start_date` | `params[beginGmtReport]` |
| `end_date` | `params[endGmtReport]` |

- 输出 `items[]`：`case_id`、`code`、`source`、`case_type`、问题类型三级字段、运营商、车辆数、上报人/位置/时间、超时/办理/申诉/核查状态、评分和 `source_table`
- 输出 `window`：请求日期、实际日期及 `fallback_applied`

### `get_case_detail`

- `source_table` 已知时：`GET /biz/case/unionQuery?id=...&sourceTable=...`
- `source_table` 未知时：`GET /biz/case/{id}`
- 处理记录：`GET /biz/case/getCaseHandles/{id}`
- 输出：列表字段之外，还包含经纬度、网格/单元/围栏、描述、反馈、图片 URL，以及 `handles[]` 中的阶段、经办人、意见、图片、开始/结束/剩余/已用/时限

### 辅助查询

- `list_case_question_types` → `GET /biz/case/getQuestionType?type=question_type`
  - 输出：`type_id`、`value`、`label`、`name`、`parent_id`、`ancestors`、`sort`
- `locate_case_grid` → `GET /biz/case/getGridByCoordinate`
  - 发送 `centerLng`、`centerLat`、`centerLngWgs`、`centerLatWgs`
  - 输出 `grid`、`cell`、`fence`，每项为 `entity_id`、`name`

## 自动巡查

### `search_patrol_results`

- Java：`GET /biz/patrolResult/list`
- 普通筛选：`id`、`patrolType`、`patrolContent`、`status`、`result`、`isWarn`、`isCase`
- 开始时间口径：`params[beginGmtPatrol]`、`params[endGmtPatrol]`
- 结束时间口径：`params[beginGmtPatrolEnd]`、`params[endGmtPatrolEnd]`
- 输出 `items[]`：巡查编号、类型、内容、车辆类型、开始/结束时间、状态、结果、异常车辆/区域/数据数、告警、案件和未处理原因

### `get_patrol_result`

- Java：`GET /biz/patrolResult/{id}`
- 输出：巡查概览、关联 `case_codes[]` 和备注

### `query_patrol_result_section`

| `section` | Java | 可用筛选 | 输出核心字段 |
| --- | --- | --- | --- |
| `area_summary` | `GET /biz/patrolResult/area/{id}` | 无 | `name`、`value` |
| `supplier_summary` | `GET /biz/patrolResult/supplier/{id}` | 无 | `name`、`value` |
| `vehicles` | `GET /biz/patrolResult/getEvInfo` | 运营商、车牌号、车辆号、车架号 | 车辆标识、运营商、类型、案件、区域、停车时长、坐标 |
| `grids` | `GET /biz/patrolResult/getGridInfo` | 责任网格、单元网格 | 网格、案件、运营商、容量和实停数 |
| `parking_areas` | `GET /biz/patrolResult/getParkInfo` | 停车区、建设单位 | 停车区、案件、运营商、容量和实停数 |
| `mac_devices` | `GET /biz/patrolResult/getMacInfo` | 运营商、车辆号、MAC | MAC、车辆、运营商、案件、异常类型和坐标 |
| `data_push` | `GET /biz/patrolResult/getDataPushInfo` | 运营商 | 运营商、未推送数、延迟推送数 |
| `abnormal_statistics` | `GET /biz/patrolResult/abnormalStat` | 运营商 | 运营商、异常项数、异常记录数 |

所有分页明细都发送 `resultId`、`pageNum`、`pageSize`。

## 订单汇总

### `get_order_summary`

- Java：`GET /biz/summaryOrder/orderReckon`
- 参数：`pageNum`、`pageSize`、可选 `supplierId`、`queryDateStart`、`queryDateEnd`
- 日期间隔必须小于 93 天
- 输出 `items[]`：运营商、合计/助力车/单车订单数、活跃车辆数、平均骑行时间、平均骑行距离、车均订单和车辆使用率
- 当天无数据且允许回退时，查询上一个完整自然月；实际窗口写入 `window`

## 未暴露能力

- 导出接口和文件下载
- 新增、修改、删除、处置、评分、批量处理等写操作
- 案件编号生成（属于新增流程，不属于监管数据检索）
- 头盔按路口/道路查询（已确认的接口没有对应字段）

