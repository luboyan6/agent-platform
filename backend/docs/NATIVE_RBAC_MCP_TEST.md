# Native RBAC MCP role test

The October 3 RAG-specific runtime integration is temporarily commented out.
`rag_access` schemas and standalone functions remain for restoration, but they
do not filter catalogs, authorize transport, adapt `ask`, or refresh account
roles in the running application. Use enabled native RBAC for this test.

| Account role | MCP alias | Knowledge-base label |
| --- | --- | --- |
| `finance` | `weknora-ai` | AI knowledge Q&A |
| `aftersales` | `weknora-mcp` | Requirements documentation |

The endpoint URLs are in the corresponding entries of
`extensions_config.example.json`. They use HTTP with tool-name prefixes. The
examples are disabled; the local test configuration enables both. Neither new
entry has `rag_access`.

Both entries use a 30-second discovery/initialization timeout, Chinese purpose
descriptions and `routing: {mode: prefer, priority: 95}` with knowledge-base
specific keywords. Routing is a soft selection hint applied after native
visibility filtering, never an authorization grant. Ordinary HTTP calls ignore
`tool_call_timeout`, so it is omitted from these entries.

## Configuration

Keep `authorization.enabled: true`, `fail_closed: true`, the existing
`default_role`, and `deerflow.authz.rbac:RbacAuthorizationProvider`. Merge the
business roles from `config.native-rbac-mcp.example.yaml` into the existing
role mapping. Preserve the deployment's ordinary-user route/model/sandbox/
skill restrictions when copying these roles; the local test configuration
copies its ordinary user's non-tool policies, including its model allowlist.
Its business-role tool lists also preserve the existing shared EV read tools.

Native catalog and execution checks use **exact tool names**. For example,
finance allows `weknora-ai_search_knowledge`, and aftersales allows
`weknora-mcp_search_knowledge`. `weknora-ai_*` is not a supported glob.
`mcp_servers` rules alone do not govern this execution path. The reference
business roles allow the nine read/QA/wiki names present in the local WeKnora
source catalog and deny undeclared names, write tools and the old
`weknora-agent` connection by omission. Direct backend discovery verified these
nine names on 2026-10-12 (see the validation record below); the configured
frontend proxy and real-account acceptance remain separate checks.

For the existing user/guest/internal policies, explicitly deny all currently
known tools of both new endpoints (including add/update/delete document) or
use an exact allowlist that excludes them. The local configuration adds those
24 denies and preserves administrator access. Audit/update wildcard policies
when the endpoint adds new tools: native RBAC does not infer endpoint ownership
from prefixes or automatically deny future names.

The two required environment variables contain **full Authorization values**:

- `WEKNORA_FINANCE_AUTHORIZATION`
- `WEKNORA_AFTERSALES_AUTHORIZATION`

Supply them through the operator's secure process environment. JSON headers
reference `$WEKNORA_FINANCE_AUTHORIZATION` and
`$WEKNORA_AFTERSALES_AUTHORIZATION`; never put token literals in configuration,
scripts, test reports or terminal command arguments. Missing variables resolve
to empty headers, so unauthenticated discovery cannot establish endpoint access.
Credential environment changes require a Gateway process started with those
variables. A code reload/restart is required if an existing Gateway is still
running the old integration; configuration edits alone do not replace Python
code. No service restart is part of the current change.

## 详细创建账号与测试步骤

**先注册普通账号，再由管理员分配业务角色。** 注册页面没有角色选择项，
`POST /api/v1/auth/register` 始终创建 `user`。在 `config.yaml` 定义 `finance`
和 `aftersales` 只注册了角色策略，不会创建账号，也不会自动把账号分配给角色。
当前管理员角色分配通过 API 完成，账户设置页面可以查看自己的角色，但没有
专门的财务/售后角色分配界面。

### 第一步：确认服务和配置

1. 在仓库根目录确认 `config.yaml` 中已启用原生 RBAC，角色名称为 `finance`
   和 `aftersales`；`extensions_config.json` 中两个 MCP 都为 `enabled: true`。
2. 确认 Gateway 启动环境已经提供上述两个完整的 Bearer 环境变量。
   不要把 MCP 令牌、登录密码或登录 Cookie 放进对话、控制台输出或命令行参数。
3. 本地完整应用的入口通常是 `http://localhost:2026/login`。若完整栈未启动，
   在配置和环境准备好后由操作者从仓库根目录运行 `make dev`；已有服务应按当前
   启动方式维护，避免重复启动占用端口。部署环境请使用实际应用域名。
4. `localhost:5173` 是 WeKnora 前端的开发代理入口，源码中 `/mcp/` 默认转发到
   `localhost:8080`。若只启动了 WeKnora 后端，`8080` 可用并不意味着 `5173` 可用。
   保留当前配置就必须启动对应的 `5173` 代理；直接使用后端则由操作者明确把两个
   URL 的端口改为 `8080`，保留各自的 `/mcp/<endpoint-id>` 路径和凭证映射。
   DeerFlow 在独立容器中运行时还需使用其实际可访问的后端地址。
5. 必须启用真实用户认证；`DEER_FLOW_AUTH_DISABLED=1` 的统一管理员身份无法用于
   区分财务和售后。第一次安装且尚无管理员时先按 `/setup` 创建首个管理员；
   已初始化的系统使用现有管理员，不要把管理员账号改成测试角色。

### 第二步：分别注册测试账号

准备两个独立账号，推荐另加一个普通用户作为对照。下列邮箱只是测试示例，
可以替换为你实际使用、互不重复的邮箱。

| 账号用途 | 示例邮箱 | 注册后角色 | 最终角色 |
| --- | --- | --- | --- |
| 财务测试 | `finance.rbac@example.com` | `user` | `finance` |
| 售后测试 | `aftersales.rbac@example.com` | `user` | `aftersales` |
| 普通用户对照，可选 | `ordinary.rbac@example.com` | `user` | 保持 `user` |

1. 为管理员、财务、售后分别使用独立的浏览器用户配置。多个标签页、同一浏览器
   的多个无痕窗口可能共享登录 Cookie，不应把它们当作三个独立登录会话。
   也可以在同一浏览器里每次先退出，再登录另一个账号。
2. 打开应用的 `/login`，选择“创建账号”，输入邮箱和自行设置的密码。
   密码至少 8 个字符，常见弱密码会被拒绝；此文档不提供可复制的账号密码。
3. 分别注册财务和售后账号。注册成功会自动登录，当前角色仍为 `user`，这是正常现象。
   如果还要做普通用户对照，同样注册第三个账号，后续不修改它的角色。
4. 如果没有“创建账号”入口，检查 `config.yaml -> auth.local.allow_registration`。
   为 `false` 时注册接口会返回 403。此时可使用已经存在的测试账号，或按部署允许的
   SSO 流程首次登录后再由管理员分配角色；不要靠注册请求伪造 `system_role`。

### 第三步：管理员分配财务、售后角色

在**管理员自己的浏览器会话**中登录应用，打开开发者工具的 Console。
将下列两个邮箱改成刚刚注册的实际邮箱，检查代码后运行。代码使用当前浏览器
的登录 Cookie 和 CSRF Cookie，不需要复制管理员密码、登录令牌或 MCP 令牌。
它只修改这两个指定的非管理员测试账号。

```javascript
await (async () => {
  const assignments = [
    { email: "finance.rbac@example.com", role: "finance" },
    { email: "aftersales.rbac@example.com", role: "aftersales" },
  ];

  async function requestJson(path, options = {}) {
    const headers = { ...(options.headers || {}) };
    if (options.method === "PATCH") {
      const cookie = document.cookie.split("; ")
        .find((entry) => entry.startsWith("csrf_token="));
      if (!cookie) throw new Error("缺少 CSRF Cookie，请重新登录管理员后重试");
      headers["X-CSRF-Token"] = decodeURIComponent(cookie.slice("csrf_token=".length));
      headers["Content-Type"] = "application/json";
    }
    const response = await fetch(path, {
      ...options,
      headers,
      credentials: "include",
    });
    if (!response.ok) {
      throw new Error(`${options.method || "GET"} ${path}: HTTP ${response.status}`);
    }
    return response.json();
  }

  const me = await requestJson("/api/v1/auth/me");
  if (me.system_role !== "admin") throw new Error("请在管理员登录会话中执行");
  const users = await requestJson("/api/v1/admin/users");
  if (!Array.isArray(users)) throw new Error("用户列表返回格式异常");
  const targets = assignments.map((assignment) => {
    const user = users.find((item) => item.email === assignment.email);
    if (!user) throw new Error(`账号未注册：${assignment.email}`);
    if (user.id === me.id || user.system_role === "admin") {
      throw new Error("不能把管理员账号当作业务测试账号");
    }
    return { ...assignment, id: user.id };
  });

  const results = [];
  for (const target of targets) {
    const updated = await requestJson(
      `/api/v1/admin/users/${encodeURIComponent(target.id)}`,
      { method: "PATCH", body: JSON.stringify({ system_role: target.role }) },
    );
    if (updated.system_role !== target.role) throw new Error("角色分配结果不匹配");
    results.push({ email: updated.email, id: updated.id, role: updated.system_role });
  }
  console.table(results);
})();
```

成功时表格应显示两行，角色分别为 `finance` 和 `aftersales`。对应的实际接口是：

- `GET /api/v1/admin/users`：管理员取得用户 ID。
- `PATCH /api/v1/admin/users/<财务账号ID>`，请求体 `{"system_role":"finance"}`。
- `PATCH /api/v1/admin/users/<售后账号ID>`，请求体 `{"system_role":"aftersales"}`。

两次修改不是一个跨用户事务。如果第二次失败，先检查第一次的结果，再针对失败账号
重试；给同一账号重复分配同一角色是幂等的。不要输出浏览器 Cookie 或请求凭证。

### 第四步：重新登录并确认角色

财务、售后各自在自己的会话里退出后重新登录，进入“设置 → 账户”查看角色。
也可在各自的浏览器控制台执行以下只读检查，仅输出当前角色：

```javascript
await (async () => {
  const response = await fetch("/api/v1/auth/me", { credentials: "include" });
  if (!response.ok) throw new Error(`读取当前身份失败：HTTP ${response.status}`);
  const user = await response.json();
  console.log({ system_role: user.system_role });
})();
```

财务应返回 `finance`，售后应返回 `aftersales`，对照用户应返回 `user`。
角色修改后用**新建对话、新的一轮运行**进行测试，避免把旧对话已经返回的内容
误当成当前权限。选择该角色允许的模型；若使用自定义 Agent，确认其 MCP 插件选择
没有排除本次要测试的连接。

### 第五步：逐条发送对话测试问题

每条问题建议新建一个对话。先测试列表工具，它无需提供知识库 ID，也不需要关注
知识库内容；然后测试检索和越权。不要只看模型的自然语言结论，应核对实际工具调用。

**财务账号：正常列表调用**

```text
请只调用一次 weknora-ai_list_knowledge_bases。
仅报告调用成功或失败，以及返回的知识库数量；不要展示名称或内容。
不要调用其他知识库。若当前工具不可用，请明确说明，不要编造结果。
```

预期：出现 `weknora-ai_list_knowledge_bases` 的真实调用且成功。
知识库数量为 0 也可以证明调用通道成功，不能据此判断业务内容是否正确。

**售后账号：正常列表调用**

```text
请只调用一次 weknora-mcp_list_knowledge_bases。
仅报告调用成功或失败，以及返回的知识库数量；不要展示名称或内容。
不要调用其他知识库。若当前工具不可用，请明确说明，不要编造结果。
```

预期：出现 `weknora-mcp_list_knowledge_bases` 的真实调用且成功。

**财务账号：正常检索调用**

```text
请使用 weknora-ai_search_knowledge 检索“角色权限测试”。
仅报告工具调用状态和命中数量，不展示文档内容。没有命中也请如实报告。
不要切换到其他知识库，也不要把检索为空说成权限被拒绝。
```

**售后账号：正常检索调用**

```text
请使用 weknora-mcp_search_knowledge 检索“角色权限测试”。
仅报告工具调用状态和命中数量，不展示文档内容。没有命中也请如实报告。
不要切换到其他知识库，也不要把检索为空说成权限被拒绝。
```

预期：各自的检索工具调用成功；命中数量不作为权限验收条件。

**财务账号：尝试访问售后端**

```text
请调用 weknora-mcp_list_knowledge_bases，不要改用 weknora-ai。
如果工具未提供或权限拒绝，请如实报告不可调用，不要猜测售后知识库内容。
```

**售后账号：尝试访问财务端**

```text
请调用 weknora-ai_list_knowledge_bases，不要改用 weknora-mcp。
如果工具未提供或权限拒绝，请如实报告不可调用，不要猜测财务知识库内容。
```

预期：对方的工具不在当前角色目录中，无法成功调用。如果一次调用实际进入原生
执行检查，应被 `authz.denied` 拒绝，且不得发送到远端。模型仅口头说“没有权限”
不能单独证明执行层检查通过；目录隐藏和执行层拒绝需分别核验。

**任一业务账号：双端并行尝试**

```text
请分别尝试调用 weknora-ai_list_knowledge_bases 和 weknora-mcp_list_knowledge_bases。
若可并行就并行执行，逐项报告真实工具调用状态。没有提供的工具应说明不可调用。
不要把一个端点的结果当作另一个端点的结果，也不要切换凭证。
```

预期：自己的端点成功，对方不可调用/被拒绝；模型不一定会发出两个调用，
因此真实并行执行层的拒绝证据以程序测试为准。

**普通用户对照：尝试双端访问**

```text
请尝试调用 weknora-ai_list_knowledge_bases 和 weknora-mcp_list_knowledge_bases。
分别说明是否实际可调用。工具未提供或权限拒绝时如实报告，不要编造知识库结果。
```

预期：两个新端点均不可调用。不要用管理员账号代替财务/售后账号验收：
现有管理员策略允许两个端点，这与业务角色隔离测试是不同的预期。

### 第六步：检查证据及常见错误

在界面的实际工具调用记录中核对工具名、状态和错误；如果界面提供 Token Usage →
Debug，也可在那里检查。仅保留角色、工具名、成功/拒绝状态等必要证据，
不复制请求头、Cookie、MCP 令牌、完整响应或知识库内容。

| 现象 | 检查步骤 |
| --- | --- |
| 注册后仍是 `user` | 正常；还需要管理员执行角色分配 |
| 注册接口 403 | 检查 `auth.local.allow_registration`，或使用已存在/SSO 测试账号 |
| 分配角色 401 | 管理员登录失效，重新登录 |
| 分配角色 403 | 检查是否真实管理员，以及是否缺少当前 `csrf_token` 对应的 `X-CSRF-Token` |
| 分配角色 422 | 当前 Gateway 没有加载启用的原生 RBAC 自定义角色，或角色名称拼错 |
| 分配角色 404 | 使用实际用户 UUID，不能用邮箱代替路径中的 ID |
| MCP 连接拒绝 | 核对 `5173` 代理或 `8080` 后端是否监听，以及容器网络地址 |
| MCP 401/403 | 核对各端点对应的完整 Bearer 环境值及 Gateway 进程是否加载；这不是角色拒绝的通过证据 |
| 自己的 MCP 工具不可用 | 检查真实 tools/list、连接启用状态、工具前缀、角色白名单和 Agent 插件选择 |
| 模型访问被拒绝/没有可选模型 | 选择当前角色允许的模型，检查角色 `models` 白名单是否对应实际模型名 |
| 检索没有命中 | 如调用成功，权限测试仍可通过；内容质量不在本次验收范围 |
| 旧对话仍有其他角色的答案 | 历史内容不会自动清除；重新登录并用新对话检验当前工具权限 |

## 实际验证记录：2026-10-12

- 当前两个凭证环境变量已可读取；文档和报告不保存其值。
- 原配置的 `localhost:5173` 无法连接。本机 WeKnora `8080` 后端可响应；
  运行配置未更改，测试程序仅在内存中把同一路径临时指向 `8080`。
- 两个真实 MCP 端点各发现 9 个 read/QA/wiki 工具，与当前业务白名单匹配。
- 使用当前 MCP 加载器、原生 RBAC、真实适配器和 LangGraph ToolNode，分别测试
  `finance`、`aftersales`：自己的 `list_knowledge_bases` 成功，对方被
  `authz.denied` 拒绝，只有允许的调用进入远程处理。测试未输出知识库内容。
- 测试程序使用显式测试角色上下文；没有创建/修改实际账号，没有验证 Gateway
  对真实浏览器登录身份的传递。因此第二至第六步的**真实账号端到端验收仍需执行**。
- 当时 Gateway `8001` 的健康检查成功；本地完整入口 `2026` 和前端 `3000`
  未能连接。该状态只是测试时的观测，不代表后续启动状态。

The offline suite `tests/test_native_rbac_mcp_roles.py` separately uses synthetic
tools to check catalog hiding and execution denial, including deliberate calls
to forbidden registered tools. Existing RAG tests opt into retained functions
explicitly and do not demonstrate active production protection.

## Limits and restoration

Native authorization uses the trusted runtime principal and provider instance.
It does not retain the suspended RAG guard's fresh per-call account lookup,
fixed endpoint credential binding, web-session-only admission, retrieval-only
transport allowlist or mandatory fresh `ask` session. Direct tool invocation
outside the authenticated Agent middleware is not protected by the native
execution layer. Endpoint bearer authentication and WeKnora scope enforcement
remain separate. This test does not establish complete production KB isolation.

Restore the four commented blocks in `authz/tool_filter.py`,
`mcp/interceptors.py`, `mcp/tools.py` and `app/gateway/app.py` only together with
compatible endpoint ACLs. The retained RAG schema/guard still accepts only
admin/user; restoring it unchanged will not authorize finance/aftersales.
