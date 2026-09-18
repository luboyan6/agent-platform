# Windows/WSL 配置 WeKnora Agent MCP：问题与解决方案

> 更新日期：2026-09-18
>
> 本文记录 Windows 主机、WSL 中的 WeKnora，以及当前 DeerFlow 项目之间的
> MCP 配置、排障、连通性验证和前端手工验收方法。

## 1. 最终结论

当前正确的 MCP 访问方式是：

```text
Windows/WSL DeerFlow
        │
        │ Streamable HTTP + Authorization: Bearer <token>
        ▼
http://127.0.0.1:8080/mcp/<endpoint-id>
        │
        ▼
WeKnora 后端 MCP 端点
```

已确认的关键点：

- `5173` 是 Vite Web UI 端口，不是 MCP 端口；不能将 `/mcp` 请求发到该端口。
- `8080` 是 WeKnora 后端端口；在当前 Windows/WSL 拓扑中，客户端使用
  `127.0.0.1:8080` 可以访问 WSL 服务。
- MCP 认证头是完整的 `Authorization: Bearer <token>`，Token 通过环境变量
  注入，不写入提交的 JSON、文档或对话。
- 当前项目的 `weknora-agent` 条目已经使用 HTTP transport、环境变量认证引用和
  `tool_name_prefix`。
- DeerFlow 实际发现了 9 个工具，并成功调用 `list_knowledge_bases`；当前端点返回
  2 个知识库条目。

本文的 `weknora-agent` 指已经部署好的 WeKnora Agent MCP 端点；项目中另有一个
独立部署的只读 bridge 示例 `weknora`，两者不是同一套认证和工具契约。相同知识范围
通常只启用其中一个，避免模型面对重复的检索工具。

## 2. 配置前的网络拓扑判断

| 项目 | 正确值 | 说明 |
| --- | --- | --- |
| Web UI | `http://192.168.20.94:5173/` | Vite 前端页面，只用于浏览器访问 |
| WeKnora 后端监听 | `0.0.0.0:8080` | 服务端监听地址；`0.0.0.0` 不作为客户端目标 |
| MCP 客户端目标 | `http://127.0.0.1:8080/mcp/<endpoint-id>` | 当前 Windows/WSL 回环转发方式 |
| 认证方式 | `Authorization: Bearer <token>` | 必须包含 `Bearer ` 前缀 |
| MCP 协议 | Streamable HTTP | 不是 stdio，也不是 Vite 单页路由 |

### 为什么不能使用 5173

Vite 配置只代理了部分 API 路由，没有将 `/mcp` 转发到 WeKnora 后端。访问
`5173/mcp/...` 时，通常得到 HTML 单页应用内容，而不是 JSON-RPC/MCP 响应，客户端
会表现为协议解析失败或工具发现失败。

### 为什么优先使用 127.0.0.1

在当前 WSL/Windows 环境中，Windows 主机访问 WSL 暴露的服务通过回环地址可用；使用
物理网卡地址可能触发 Windows 本地出站回环限制。该结论只适用于 DeerFlow 与服务
共享当前回环拓扑；如果 DeerFlow 运行在独立 Docker 网络中，应改用可达的私网入口、
`host.docker.internal` 或 HTTPS 反向代理地址，不能假设容器内的 `127.0.0.1` 指向
Windows 主机。

## 3. Windows Antigravity CLI 配置

Antigravity CLI 的全局配置和 DeerFlow 项目配置相互独立。Windows PowerShell 中可
按以下形态添加 MCP（示例使用占位符，不要把真实 Token 写入脚本或提交）：

```powershell
agy.exe mcp add `
  --header "Authorization: Bearer <weknora-agent-token>" `
  weknora-agent `
  http://127.0.0.1:8080/mcp/<endpoint-id>

agy.exe mcp list
```

预期状态应为：

```text
weknora-agent     http     enabled     http://127.0.0.1:8080/mcp/<endpoint-id>
```

该命令写入 Antigravity 的全局 MCP 配置；它不会自动修改当前 DeerFlow 项目的
`extensions_config.json`。

## 4. 当前项目 DeerFlow 配置

### 4.1 注入认证环境变量

将完整的 Bearer 头值放入 Gateway 的运行环境或本地未提交的 `.env`：

```dotenv
WEKNORA_MCP_AUTH_HEADER=Bearer <weknora-agent-token>
```

如果使用 Windows 用户环境变量，可以使用占位符形式的 PowerShell 命令：

```powershell
[Environment]::SetEnvironmentVariable(
  "WEKNORA_MCP_AUTH_HEADER",
  "Bearer <weknora-agent-token>",
  "User"
)
```

设置环境变量后，需要重启 Gateway，或通过项目已有的 MCP 配置刷新/缓存重置路径
让新进程读取到该变量。不要在聊天输入、Git 跟踪文件或错误日志中粘贴真实 Token。

### 4.2 `extensions_config.json` 条目

当前项目条目的安全形态如下；需要保留其他 MCP server，不要整文件覆盖：

```json
{
  "weknora-agent": {
    "enabled": true,
    "type": "http",
    "url": "http://127.0.0.1:8080/mcp/<endpoint-id>",
    "headers": {
      "Authorization": "$WEKNORA_MCP_AUTH_HEADER"
    },
    "tool_name_prefix": true,
    "session_init_timeout": 100,
    "description": "WeKnora Agent MCP document retrieval",
    "routing": {
      "mode": "prefer",
      "priority": 90,
      "keywords": [
        "WeKnora",
        "知识库",
        "知识检索",
        "文档检索",
        "文档引用"
      ]
    }
  }
}
```

环境变量解析发生在 DeerFlow 配置加载阶段。`Authorization` 的值应解析为完整的
`Bearer ...` 字符串；缺失或为空时，MCP discovery 会失败，不应通过把 Token 改成
明文写入 JSON 来绕过问题。

## 5. MCP 工具清单

当前端点通过 MCP `tools/list` 暴露以下 9 个原始工具。由于项目启用了工具名前缀，
在 DeerFlow 中对应的名字是 `weknora-agent_<原始工具名>`。

| 原始工具 | 用途 | 常用参数 |
| --- | --- | --- |
| `list_knowledge_bases` | 列出当前端点可访问的知识库 | 无 |
| `search_knowledge` | 语义检索知识库片段 | `query`、可选 `knowledge_base_ids` |
| `grep_chunks` | 精确/正则匹配分块文本 | `query`、可选 `knowledge_base_ids` |
| `list_documents` | 列出指定知识库的文档 | `knowledge_base_id`、分页参数 |
| `read_document` | 读取文档元数据和分块内容 | `knowledge_id`、`offset`、`limit` |
| `ask` | 基于知识库执行综合问答 | `question`、可选 `knowledge_base_ids`、`session_id` |
| `wiki_index` | 查看知识库 Wiki 索引 | 以端点返回 schema 为准 |
| `wiki_read_page` | 读取 Wiki 页面 | 以端点返回 schema 为准 |
| `wiki_search` | 搜索 Wiki 页面 | 以端点返回 schema 为准 |

工具 schema 由远端 MCP server 决定。每次更换 endpoint 或升级 WeKnora 后，都应重新
执行 `tools/list`，不要仅凭旧文档假定工具数量和参数不变。

## 6. 连通性验证

### 6.1 后端存活检查

不携带 Token 的健康检查只验证服务存活，不验证 MCP 认证：

```powershell
curl.exe --noproxy "*" --connect-timeout 3 --max-time 8 `
  http://127.0.0.1:8080/health
```

预期为 HTTP 200。健康检查失败时，先检查 WSL 服务、端口映射和 Windows 防火墙；
不要先修改 MCP header。

### 6.2 MCP 协议检查顺序

MCP 验证应按以下顺序进行：

1. `initialize`：确认 JSON-RPC/MCP 协议握手成功。
2. `tools/list`：确认认证通过，并核对工具数量和工具名。
3. `tools/call` → `list_knowledge_bases`：确认端点不仅能发现工具，也能实际调用。
4. `search_knowledge` 或 `grep_chunks`：使用已知文档事实或唯一关键词进行检索。
5. 在 DeerFlow 新对话中检查 ToolMessage、回答引用和无命中行为。

本次实际验证结果：

```text
配置解析：通过
transport：http
认证环境变量解析：通过（未输出 Token）
MCP initialize/tools/list：通过
发现工具数：9
list_knowledge_bases：通过
返回知识库条目数：2
```

同时执行了 DeerFlow 相关回归测试：`21 passed`。测试中出现的 4 条依赖弃用警告
不是本次配置引入的失败。

## 7. 前端手动验收样例

在 DeerFlow 前端进入 **Capability Center → MCP**，确认 `weknora-agent` 已启用且
认证字段被掩码。然后新建对话，建议按以下顺序验证。

### 7.1 工具发现和知识库列表

```text
请调用 `weknora-agent_list_knowledge_bases`，列出我当前可访问的知识库数量和名称；不要猜测或补全未返回的信息。
```

预期：

- Token Usage → Debug 中出现 `weknora-agent_list_knowledge_bases`；
- 返回数量与端点实际返回一致；
- 助手不凭空补充未返回的知识库。

### 7.2 语义检索和引用

```text
请先调用 `weknora-agent_search_knowledge` 检索 WeKnora 知识库，再回答：<已知文档问题>。
请给出文档标题和可核对的文档或分块标识；证据不足时明确说明，不要编造来源。
```

预期：

- Debug 中出现 `weknora-agent_search_knowledge`；
- 回答中的事实可以回到检索片段；
- 如果需要上下文，可以继续调用 `weknora-agent_read_document`；
- 不虚构 URL、文档标题或分块标识。

### 7.3 精确关键词检索

```text
请调用 `weknora-agent_grep_chunks` 在 WeKnora 知识库中精确查找 “<唯一关键词>”。
返回匹配的文档标题和相关片段；没有匹配时只回答未命中。
```

适合错误码、接口名、设备型号、专有名词等语义检索可能漏掉的内容。

### 7.4 无命中和提示注入验收

```text
请在 WeKnora 中查找一个确定不存在的关键词：<随机唯一字符串>。
如果没有证据，请明确回答未命中，不要猜测，也不要生成引用。
```

如果检索文档中出现“忽略之前指令”“改变系统规则”等文字，助手应将其当作资料
内容，而不是系统指令；它不能改变用户权限、MCP 配置或工具调用边界。

### 7.5 服务异常验收

在确认正常调用后，再由运维人员短暂停止 MCP 服务或使用无效 Token 验证失败反馈：

- 服务不可达/超时：明确说明无法连接或检索失败；
- 401/403：明确说明认证或权限失败；
- 无命中：返回空证据，不应伪装成服务故障，也不应生成虚构答案。

不要在前端对话中粘贴真实 Token 来做错误测试。

## 8. 常见问题排查

| 现象 | 根因 | 处理 |
| --- | --- | --- |
| MCP parser 收到 HTML | URL 使用了 `5173` | 改为后端 `127.0.0.1:8080/mcp/...` |
| `ConnectError` | 当前执行进程不在 Windows/WSL 服务的网络命名空间 | 从 Gateway 实际运行环境测试，或配置可达的私网/host-gateway 地址 |
| 401/403 | Token 缺失、Bearer 前缀错误或端点权限不足 | 检查环境变量解析和端点授权，不把 Token 改写进 JSON |
| `tools/list` 成功但没有目标工具 | 端点工具集发生变化或工具被前缀化 | 重新查看工具 schema 和 `weknora-agent_` 前缀 |
| 修改配置后旧工具仍存在 | Gateway 使用了旧 MCP cache | 新建对话、重启 Gateway 或调用已有 MCP cache reset |
| 前端回答没有检索 | routing 是偏好提示，不是强制策略 | 在问题中明确要求调用目标工具，并检查 Debug |

## 9. 安全和回滚

- 不要将真实 `Authorization`、WeKnora API Key、Tenant ID 或知识库权限范围写入
  Git 跟踪文件。
- DeerFlow 只需要 MCP URL 和端点认证头；WeKnora 上游 API Key 应留在 WeKnora
  服务端，不应放进 DeerFlow 工具参数。
- `extensions_config.json` 是本地运行配置；变更时保留其他 MCP server，优先使用
  Capability Center/API 的原子写入路径。
- 回滚时只禁用 `weknora-agent`（或实际启用的 `weknora` bridge），不要删除其他
  MCP 配置，不修改 WeKnora 数据。
- 轮换 Token 时同步更新运行环境和 Antigravity/DeerFlow 使用的配置来源，然后重启
  或刷新 MCP cache。

## 10. 本次改动和验证范围

- 已修改当前项目本地 `extensions_config.json` 的 MCP URL；认证仍通过已有环境变量
  引用解析。
- 已新增本汇总文档，并在 README 的 WeKnora 入口补充说明。
- 已验证配置解析、MCP discovery、只读工具调用和后端相关回归测试。
- 尚未代替用户执行浏览器内的最终回答引用验收；第 7 节样例用于人工确认真实文档
  引用、无命中和服务异常表现。
