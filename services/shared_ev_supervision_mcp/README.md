# Shared EV Supervision MCP

共享电动车监管 Java 后端的只读 MCP 适配服务。服务只提供 Streamable HTTP，不提供 stdio；头盔监管、案件处理、自动巡查和订单汇总始终复用同一个 `SHARED_EV_API_BASE_URL`，不会读取或自动切换到备用后端。

## 已确认的后端与鉴权

- 测试后端 A：`http://112.250.106.138:2304/shared-ev-web/prod-api`
- 前端把登录接口返回的 `access_token` 保存在 `Admin-Token-Ev` Cookie 中，并在 Axios 拦截器中发送 `Authorization: Bearer <access_token>`。
- MCP 服务从权限不超过 `0600` 的本地文件读取该 Authorization 值。凭证不属于工具参数，不会进入 MCP Schema、日志或配置文件。

令牌文件只能有一行，可写成裸 token、`Bearer ...` 或完整的 `Authorization: Bearer ...`。不要把令牌放入 `.env`、命令行或仓库：

```bash
chmod 600 /run/secrets/shared_ev_authorization
```

## 启动

```bash
cd services/shared_ev_supervision_mcp
uv sync --locked

export SHARED_EV_API_BASE_URL=http://112.250.106.138:2304/shared-ev-web/prod-api
export SHARED_EV_API_AUTH_FILE=/run/secrets/shared_ev_authorization
uv run --locked shared-ev-supervision-mcp
```

默认监听：

- 健康检查：`GET http://127.0.0.1:8765/health`
- MCP：`http://127.0.0.1:8765/mcp`

默认只允许回环地址访问 MCP。若绑定非回环地址，配置加载会强制要求独立的 `SHARED_EV_MCP_AUTH_TOKEN` 或 `SHARED_EV_MCP_AUTH_TOKEN_FILE`，客户端通过 `X-MCP-Auth-Token` 发送；该令牌与 Java 后端 access token 相互独立。

## MCP Tools

所有工具都声明为只读、幂等、非破坏性。输出均为显式 Pydantic Schema，不返回未经筛选的后端响应体。

完整的 Java 参数映射与输出字段见 [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md)。

| Tool | 主要输入 | 结构化输出 |
| --- | --- | --- |
| `get_api_metadata` | 无 | 当前唯一 Base URL、路由、参数和限制 |
| `list_suppliers` | 无 | `supplier_id`、运营商名称和简称 |
| `get_helmet_realtime_metrics` | `supplier_ids`、`exclude_inaccurate` | 头盔存量、在位/丢失、佩戴、异常和近一小时订单指标 |
| `get_helmet_statistics` | 日期、运营商、排除标记 | 佩戴趋势、运营商佩戴率、未佩戴及不准确数据统计 |
| `search_cases` | 页面全部筛选项、日期、`scope` | 分页案件、查询窗口和是否回退 |
| `get_case_detail` | `case_id`、可选 `source_table` | 案件详情与处理记录；覆盖主记录和联合详情查询 |
| `list_case_question_types` | 无 | 案件问题类型节点 |
| `locate_case_grid` | WGS84 经纬度 | 责任网格、单元网格和电子围栏 |
| `search_patrol_results` | 页面全部筛选项、开始/结束时间口径 | 分页巡查记录、查询窗口和是否回退 |
| `get_patrol_result` | `result_id` | 巡查概览、异常数量和关联案件编号 |
| `query_patrol_result_section` | `result_id`、`section` 及对应筛选项 | 区域、运营商、车辆、网格、停车区、MAC、数据推送或异常统计 |
| `get_order_summary` | 运营商、日期、分页 | 订单数、活跃车辆数、平均时长/距离、车均订单和使用率 |

`search_cases` 和 `search_patrol_results` 未指定日期时查询包含当天在内的近 30 个自然日。`get_order_summary` 未指定日期时先查当天。如果首次业务结果为空且 `fallback_to_previous_month=true`，工具会再查上一个完整自然月，并在 `window.fallback_applied` 及 effective 日期中明确标记。网络、鉴权、HTTP 或响应 Schema 错误不会触发日期回退。

## Java 路由

| 模块 | 路由 |
| --- | --- |
| 运营商 | `GET /biz/supplier/listUI` |
| 头盔 | `POST /biz/helmet/query`、`POST /biz/helmet/stat` |
| 案件 | `GET /biz/case/list`、`GET /biz/case/dealList`、`GET /biz/case/{id}`、`GET /biz/case/unionQuery`、`GET /biz/case/getCaseHandles/{id}`、`GET /biz/case/getQuestionType`、`GET /biz/case/getGridByCoordinate` |
| 自动巡查 | `GET /biz/patrolResult/list`、`GET /biz/patrolResult/{id}` 以及详情页的 8 类子查询 |
| 订单 | `GET /biz/summaryOrder/orderReckon` |

导出、删除、案件处置、评分等写操作或文件下载不暴露为 MCP Tool。当前头盔接口没有道路或路口筛选字段，因此不能按“某路口”精确查询。

## DeerFlow 接入

本仓库根目录的 `extensions_config.example.json` 包含默认关闭的 `shared_ev_supervision` HTTP 配置。当前本地配置可使用：

```json
{
  "enabled": true,
  "type": "http",
  "url": "http://127.0.0.1:8765/mcp",
  "tool_name_prefix": true
}
```

启用前必须先启动本服务。若服务部署在另一个主机或容器中，应把 URL 改成 Gateway 实际可达地址；非回环部署还必须配置独立 MCP token header。

## 对话示例

- “查询 2026-08-22 到 2026-09-20 的头盔佩戴趋势，并按运营商列出佩戴率。”
- “查询近 30 天案件处理和自动巡查记录；如果没有数据就查上一个自然月，再汇总同一时间范围的订单统计。”

## 验证

```bash
cd services/shared_ev_supervision_mcp
uv run --locked ruff check src tests scripts
uv run --locked ruff format --check src tests scripts
uv run --locked pytest -q
uv build
```

服务启动后，可通过标准 MCP 客户端执行只输出汇总计数、不输出案件或巡查明细的在线冒烟测试：

```bash
uv run --locked python scripts/smoke_http.py \
  --expected-base-url http://112.250.106.138:2304/shared-ev-web/prod-api \
  --start-date 2026-08-22 \
  --end-date 2026-09-20
```
