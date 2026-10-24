# Role-scoped RAG MCP access

> Historical/retained implementation: its four runtime integration points are
> currently commented out for the [native RBAC MCP role test](NATIVE_RBAC_MCP_TEST.md).
> The contracts below describe the retained implementation, not active runtime
> enforcement. A `rag_access` field alone currently provides no RAG admission.

This pilot uses several logical MCP endpoints on the existing RAG deployment.
Each endpoint has its own fixed credential, explicit knowledge-base scope and
retrieval/QA tool allowlist. Agent selects permitted endpoints using the current
platform account's `user` or `admin` role. No RAG code change or account migration
is required.

## Transport and trust boundary

| Approach | Pilot decision |
| --- | --- |
| Forward a user token in runtime headers | Not needed: existing RAG endpoint tokens already identify fixed scopes. User identity stays inside Agent. |
| Inject role/user identifiers into model-visible tool arguments | Not used: arguments are untrusted and cannot grant access. |
| Several scoped MCP connections | Selected. Separate logical endpoint URLs/tokens can share one RAG process. |

Gateway clears forged identity from both request config carriers, then stamps
`user_id`, `user_role`, `is_internal` and
`authz_attributes = {"auth_source": "session"}` from authenticated server state.
Ordinary subagents already copy these attributes. Only a web session with a
current account is admitted. PAT, internal/IM, scheduler, auth-disabled, direct
CLI and durable calls are outside this pilot; they cannot inherit ambient web
authority. Other unrelated MCP tools preserve their behavior under valid config.

The initial tool catalog uses the trusted role snapshot and exact discovery
source metadata. RAG projection runs before general authorization and deferred
`tool_search`, even when general authorization is disabled. It does not mutate
the shared tool cache. Each actual business call independently rereads a stable
live configuration and the account's current role. Database reads remain on the
Gateway's owning event loop, including calls from subagent worker loops.
Async subagent initialization offloads the synchronous policy projection to a
worker thread so reading config cannot block its event loop.

## Configuration

Copy the disabled `rag_common` / `rag_restricted` entries from
[`extensions_config.example.json`](../../extensions_config.example.json).
The active `extensions_config.json` was deliberately left unchanged during
local implementation. Replace endpoint placeholders and provide complete
Authorization header values through deployment secret handling before enabling.
Never put actual credentials into documentation or tool arguments.

```json
{
  "mcpServers": {
    "rag_common": {
      "enabled": false,
      "type": "http",
      "url": "http://127.0.0.1:8080/mcp/COMMON_ENDPOINT_ID",
      "headers": {"Authorization": "$RAG_COMMON_AUTHORIZATION"},
      "tool_name_prefix": true,
      "rag_access": {"roles": ["user", "admin"]}
    },
    "rag_restricted": {
      "enabled": false,
      "type": "http",
      "url": "http://127.0.0.1:8080/mcp/RESTRICTED_ENDPOINT_ID",
      "headers": {"Authorization": "$RAG_RESTRICTED_AUTHORIZATION"},
      "tool_name_prefix": true,
      "rag_access": {"roles": ["admin"]}
    }
  }
}
```

`rag_access.roles` accepts only `user` / `admin`; omitted or empty roles grant
nobody. Administrator access must be explicit. `rag_access: null` and unknown
policy fields are rejected. Controlled entries require HTTP, prefixed tools and
fixed Authorization headers; OAuth, user/context credentials and durable task
toolsets cannot be combined with this policy. Disabled templates can load
before their environment references are provisioned.

Older config clients omitting `rag_access` preserve stored protection, including
targeted replacement updates. The Gateway remembers protected aliases during
its lifetime: removing their policy from disk cannot make them public. Retire an
endpoint by disabling or deleting it. Mark every activated RAG connection and
retire the old unrestricted RAG connection before rollout.

## Enforcement and errors

The built-in RAG interceptor runs after credential/custom interceptors, closest
to transport. Optional custom interceptor loading failures cannot remove it.
It verifies final tool name/arguments/header overrides and privately pins the
transport, URL and fixed headers captured when the tool was built. A changed
URL/token requires new discovery; a stale tool cannot call the previous scope.
Description, routing and role changes do not change connection identity.

Only `list_knowledge_bases`, `search_knowledge` and `ask` are admitted. The `ask`
schema hides `session_id`, replaces reuse instructions, rejects nonempty session
IDs and explicitly sends an empty ID to create a fresh downstream session.
Follow-up context belongs in the platform question, not a shared RAG session.

| Condition | Result before RAG business I/O |
| --- | --- |
| Missing/unassigned role, missing account, non-web source, disabled/deleted endpoint, removed policy | `RAG_ACCESS_DENIED` |
| Account lookup absent/failing, unreadable/invalid/unstable policy, invalid resolved headers | `RAG_AUTH_UNAVAILABLE` |
| Changed bound URL/token or custom header substitution | `RAG_CONNECTION_CHANGED` |
| Write/unknown tool | `RAG_TOOL_DENIED` |
| Nonempty ask session ID | `RAG_SESSION_REUSE_DENIED` |

Policy read failures are explicit errors, never cached grants or empty searches.
Because policy is shared by all configured deployment connections, an unreadable
revision can also prevent unrelated MCP admission until repaired; it cannot be
safely classified as a new protected endpoint. Normal non-RAG calls require no
web actor or account lookup. Audit contains actor, current role, logical endpoint,
raw tool, run/call identifiers and decision, excluding credentials and questions.

Parallel calls have independent decisions: authorized calls may finish while
unauthorized calls fail. Revocation blocks the next admission; already admitted
work may finish and previous answers are retained. New grants do not expand a
run's already assembled catalog. Discovery may initialize/list tools at several
endpoints using service credentials; the zero-request assertion concerns denied
business `tools/call`, not service-owned discovery.

## IDOR boundary and implementation steps

1. Configure each RAG endpoint with an explicit **nonempty** knowledge-base list
   and only retrieval/QA operations. The local RAG implementation interprets an
   empty KB list as all workspace-visible KBs. Confirm the deployed behavior and
   safe default QA agent before activation.
2. Add the endpoint definitions and explicit role grants to Agent config. Keep
   fixed secrets outside JSON using complete-header environment references.
   Keep secrets and host configuration outside Agent sandbox mounts; leave
   local host-bash execution disabled for untrusted users.
3. Enable authenticated web sessions; the Gateway lifespan installs fresh role
   lookup and initializes the protected-alias registry. No new database schema
   or downstream middleware is needed for this pilot.
4. Validate role projection, parallel denial, account/policy revocation, ordinary
   subagents, stale tools, fresh QA sessions and unchanged secret masking locally.
5. Separately authorize real activation, verify endpoint scopes and replace the
   old unrestricted connection. Test a foreign KB ID through an allowed endpoint:
   RAG must reject it, without stripping the selector or retrying another scope.

The RAG side retains its existing endpoint-token authentication, raw tool
allowlist and KB/document membership checks. Agent passes KB selectors unchanged;
endpoint-level role filtering cannot repair an incorrectly broad RAG scope.
Downstream 401/403/timeouts are surfaced without privileged fallback or automatic
replay. A leaked fixed endpoint token remains usable outside Agent; per-person
downstream audit would require a later RAG identity extension.

Conceptual protected-endpoint admission pseudocode (implemented in
`mcp/rag_access.py`):

```python
async def invoke(request, transport):
    policy = await read_stable_live_policy()
    endpoint = require_enabled_protected_endpoint(policy, request.server_name)
    require_same_private_connection_binding(endpoint)
    actor = require_server_stamped_web_actor(request.runtime.context)
    role = await gateway_lookup_current_account_role(actor)
    require_explicit_role_grant(role, endpoint.rag_access.roles)
    require_readonly_tool(request.name)
    require_unchanged_fixed_headers(request.headers)
    args = dict(request.args)
    if request.name == "ask":
        reject_nonempty_session_id(args)
        args["session_id"] = ""
    return await transport(request.override(args=args))
```

Core files: config schema and config API preserve the policy; Gateway services
stamp identity; `app/gateway/rag_mcp_access.py` owns fresh account lookup;
`mcp/rag_access.py` owns projection/admission/session restrictions;
`mcp/interceptors.py` installs the guard; `mcp/tools.py` records exact discovery
source and adapts ask; `authz/tool_filter.py` shares projection across Agent paths;
`subagents/executor.py` offloads projection during async child initialization.
No live RAG activation is implied by the local tests.
