# DeerFlow × WeKnora 多用户/多角色知识库权限隔离 — Codex 开发任务

## 1. 目标与边界

在**现有 DeerFlow 已接入 WeKnora MCP** 的基础上，实现根据**已认证用户身份与服务端角色授权**，仅访问对应的 WeKnora RAG 知识库；不能依赖大模型理解问题、System Prompt 或前端传入的角色字段进行授权。

- **仅允许修改 DeerFlow 项目源码、配置和测试**；**不修改 WeKnora 源码**。
- 允许通过 **WeKnora 现有管理界面**创建/配置多个 MCP Endpoint，限制各 Endpoint 可访问的知识库和可调用的工具。
- 保持现有登录流程、DeerFlow Agent、其他 MCP/工具及原有功能尽可能不受影响。
- 不将 Endpoint Token、内部密钥或未经授权的知识库内容暴露给 LLM、前端或日志。

## 2. 权限模型

采用 **可信身份 → 用户角色（RBAC）→ MCP Endpoint/Tool 白名单 → WeKnora Endpoint 知识库范围限制** 的双层隔离。

| 角色 | 可访问知识库 | 禁止访问 |
|---|---|---|
| `finance`（财务） | 财务、预算、公共 | 售后维修 |
| `aftersales`（售后维修） | 维修、故障案例、公共 | 财务、预算 |
| `user`（普通员工） | 公共 | 财务、售后维修 |
| `manager`（管理人员） | 财务、预算、维修、公共（按实际授权） | 其他未授权库 |
| 未认证/未映射用户 | 默认拒绝业务知识库 | 所有受限库 |

**原则：** 用户提出的问题仅决定在**已授权范围内**选择哪个检索工具；越权请求必须拒绝，而不是让 Agent 自行判断是否应该放行。

## 3. 技术方案

### 3.1 WeKnora 侧（仅管理配置）

建立独立的 MCP Endpoint，例如：

- `weknora_finance`：仅财务及预算库；仅开放检索/问答/阅读等只读工具。
- `weknora_repair`：仅维修及故障案例库；仅开放只读工具。
- `weknora_public`：仅公共库；仅开放只读工具。

每个 Endpoint 使用独立 URL/Token，**显式限制知识库范围**。不得将空知识库范围视为“无权限”（需核实 WeKnora 版本语义）；禁用文档增删改等写入工具。Endpoint URL/Token 使用占位符或环境变量，严禁写入真实密钥。

### 3.2 DeerFlow 侧（优先复用原生能力）

1. **先检查本地实际版本与代码**：`extensions_config.json`、`config.yaml`、MCP Server/Tool 加载流程、认证用户上下文、RBAC/Authorization Provider、工具调用拦截、Subagent/延迟工具发现机制。不要假定 GitHub `main` 的实现与当前部署一致。
2. 在 `extensions_config.json` 中配置上述 MCP Server，保留原配置；启用能避免同名工具冲突的前缀机制。确认版本支持的 `type`、`headers` 环境变量引用格式，以及实际工具名；**不要臆造工具名或配置键**。
3. 优先使用当前版本**原生 RBAC/AuthorizationProvider**定义角色 → MCP 工具白名单；若不支持，再在 DeerFlow 内实现最小必要的扩展，不改 WeKnora。
4. 角色只能来自 DeerFlow **服务端已验证**的 Session/JWT/OIDC/账号信息（如现有 OA 单点登录）；实现或复用可信的用户角色映射，禁止信任客户端提交的 `role`、对话文本或 MCP Tool 参数。未认证/授权信息缺失时 `fail closed`。
5. **两处强制鉴权**：① Agent 工具注册、工具发现、动态加载时过滤未授权 MCP 工具；② 工具实际执行前重新鉴权。必须覆盖直接调用、Subagent、工具搜索/延迟加载、重试与恢复执行等可达入口。不能只靠提示词、路由或 UI 隐藏。
6. **职责隔离**：DeerFlow 控制哪些用户能调用哪些 Endpoint/Tool；WeKnora 的受限 Endpoint 再限制所能触达的知识库。检查是否存在共享全权限 Endpoint、直接 WeKnora API、通用 HTTP/脚本工具等绕过路径，并提出可实施的封堵措施。
7. 若支持用户级 `user_auth`，可作为辅助防线，但不能替代 RBAC。已有单一全权限 WeKnora Endpoint 不得继续暴露给普通用户。
8. 角色/权限变更对**后续新调用**生效；处理长会话和 Subagent 的授权缓存，避免撤权后复用旧工具授权。现有历史对话、记忆及缓存的敏感信息不等同于自动撤销，需明确处理策略。

## 4. 开发要求

- **先阅读并输出简短现状分析**：当前版本是否提供原生 RBAC、MCP 前缀与 `user_auth`、权限校验的入口和实际代码位置；然后直接在本项目完成修改。
- 尽量采用配置化的 `role → allowed_mcp_servers/tools` 授权矩阵，便于后续新增采购、人事、运营等部门。
- 仅允许在授权范围内根据用户问题选择检索 Endpoint；不得允许用户通过指定 `knowledge_base_id`、工具名、资源 URI、参数注入突破授权。
- 保持最小权限、默认拒绝；不为普通员工分配写入权限。管理员权限与业务管理人员权限分开。
- 保留必要审计字段：`user_id`、`role`、`mcp_server`、`tool`、`decision`、`timestamp`、拒绝原因；日志应脱敏，不记录密钥及完整敏感检索结果。
- 配置方式应与当前部署一致，说明是否需重启、重建容器、迁移数据库或重新登录；不要凭空创建与项目架构不符的模块。

## 5. 验收测试（必须提供自动化测试或可执行验证步骤）

1. 财务用户可检索财务/公共库，无法调用维修 MCP，也无法用维修库 ID 越权读取。
2. 售后维修用户可检索维修/公共库，无法调用财务 MCP 或读取财务文档。
3. 管理人员只能访问其明确获授权的库；普通员工只能访问公共库。
4. 未登录、无角色、非法角色、伪造前端角色、Prompt Injection、直接指定隐藏工具、越权修改 MCP 参数均被拒绝。
5. 在 Agent Tool 列表、延迟工具搜索、Subagent 和**执行前**均无法绕过权限校验。
6. 角色撤销/变更后，后续请求与已有会话中的新工具调用均按新权限校验。
7. 默认无法调用 WeKnora 的新增、修改、删除文档工具；不同 Endpoint Token 的范围由 WeKnora 服务端验证。
8. 原有合法 MCP 工具和正常聊天能力无功能回归；异常拒绝有脱敏审计记录。

## 6. Codex 交付内容

请**实际完成代码及配置修改**（非仅输出建议），并返回：

1. 现有源码检查结论，以及选择“原生 RBAC / 扩展 Provider”的理由。
2. 修改文件清单、关键实现说明、完整配置示例（仅占位符）。
3. WeKnora 管理界面需要创建的 Endpoint、知识库白名单及只读权限清单。
4. 用户与角色分配/同步方法（优先复用现有认证/管理接口）。
5. 测试命令、通过/失败结果及未解决风险。
6. 部署生效步骤和回滚方式。

**参考资料：**
- DeerFlow：https://github.com/bytedance/deer-flow
- WeKnora：https://github.com/Tencent/WeKnora
- WeKnora MCP 文档：https://weknora.weixin.qq.com/docs/03-features/08-mcp

> 开始实施前，必须以当前项目的**实际代码和 WeKnora 版本**核对接口、配置字段和工具名称；不得因参考文档版本差异而假设某一功能已存在。
