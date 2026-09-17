# WeKnora read-only MCP integration

DeerFlow can retrieve evidence from a separately deployed WeKnora instance
through the standalone service in `services/weknora-mcp/`. The integration
exposes one read-only MCP tool and keeps the WeKnora API key and knowledge-base
scope outside the DeerFlow process.

```text
User → DeerFlow Agent → HTTP MCP adapter → WeKnora MCP service
                                           └→ POST /api/v1/knowledge-search?resource_urls=handle
```

The MCP result enters LangGraph as a `ToolMessage`. The next model request sees
bounded document snippets, titles, and stable citation identifiers. Retrieved
text remains untrusted data; it is never inserted as a system instruction.

## Security and ownership boundary

The two credentials have different owners and must be different:

| Deployment | Configuration | Purpose |
| --- | --- | --- |
| WeKnora MCP service | `WEKNORA_API_KEY` | Upstream retrieve-only WeKnora identity |
| WeKnora MCP service | `WEKNORA_KB_IDS` | Server-controlled UUID allowlist, at most eight KBs |
| WeKnora MCP service | `WEKNORA_TENANT_ID` | Required only for a WeKnora platform key |
| Both services | `MCP_SERVER_AUTH_TOKEN` / `WEKNORA_MCP_TOKEN` | Shared service-to-service MCP credential |
| DeerFlow | `WEKNORA_MCP_URL` | Complete remote Streamable HTTP `/mcp` URL |

Do not put `WEKNORA_API_KEY` or `WEKNORA_KB_IDS` in DeerFlow's configuration.
The model can narrow a call to the configured allowlist but cannot extend that
scope. A shared MCP credential gives every DeerFlow user authorized to call the
tool the same configured knowledge access; per-user WeKnora authorization and
cross-system SSO require a separate identity-mapping design.

Use HTTPS between hosts or an encrypted controlled network. The service rejects
missing/incorrect `X-MCP-Auth-Token` values before MCP dispatch and uses the MCP
SDK's Host/Origin protection. Configure `MCP_ALLOWED_HOSTS` for the Host header
seen after the reverse proxy. MCP responses must not be cached; if a proxy
permits SSE responses, disable response buffering. Keep proxy timeouts above
the service's 30-second retrieval deadline.

## Deploy the service

The package requires Python 3.12 and has its own lock file. It does not use the
DeerFlow backend virtual environment.

```bash
cd services/weknora-mcp
cp .env.example .env
# Edit .env. Use a retrieve-capable key and only the KB UUIDs this service may expose.
uv sync --locked
uv run --env-file .env --locked weknora-mcp
```

For the supplied container deployment:

```bash
cd services/weknora-mcp
cp .env.example .env
# Edit .env, then build and start:
docker compose up --build -d
curl --fail http://127.0.0.1:8000/health
```

`WEKNORA_BASE_URL` is the API root reachable *from the MCP service* and must end
in `/api/v1`. For example, a service outside the WeKnora Docker network may use
`http://192.168.20.94:8080/api/v1`; a service on the same network may use the
WeKnora service name. `0.0.0.0` is a bind address and is rejected as an upstream
client target.

Startup fails if required configuration is absent, malformed, or mixes the
upstream and MCP credentials. `/health` returns only `{"status":"ok"}` and does
not prove that the upstream credential can retrieve a document.

## Verify the MCP service

Run the offline and real-loopback protocol suite first:

```bash
cd services/weknora-mcp
uv run --locked pytest -q -W error
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
```

With the service running, use the pinned MCP 2.2.0 client to verify
initialization, the single-tool surface, and a real retrieval. The script reads
the service token from `.env`; it does not print it. MCP 2.x returns two
transport streams, so do not add the removed third tuple element.

```bash
cd services/weknora-mcp
WEKNORA_MCP_URL=http://127.0.0.1:8000/mcp \
uv run --env-file .env --locked python - <<'PY'
import asyncio
import os

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main():
    headers = {"X-MCP-Auth-Token": os.environ["MCP_SERVER_AUTH_TOKEN"]}
    async with httpx.AsyncClient(headers=headers, timeout=35, trust_env=False) as client:
        async with streamable_http_client(os.environ["WEKNORA_MCP_URL"], http_client=client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = (await session.list_tools()).tools
                print([tool.name for tool in tools])
                result = await session.call_tool(
                    "search_knowledge_base",
                    {"query": "替换成已索引文档中的已知问题", "top_k": 5},
                )
                print(result.model_dump_json(indent=2))


asyncio.run(main())
PY
```

Expected results:

- the tool list is exactly `search_knowledge_base`;
- a hit includes `citation`, knowledge-base/document/chunk identifiers, title,
  filename, bounded content, and `truncated`;
- a valid no-hit query returns `results: []`;
- a missing or incorrect MCP token returns HTTP 401;
- an unapproved KB argument fails before any WeKnora request;
- upstream 401/403, malformed JSON, oversized data, timeout, or a partial
  multi-KB failure becomes a sanitized tool error rather than an empty result.

## Register the service in DeerFlow

`extensions_config.example.json` contains a default-disabled `weknora` entry.
Set these values in the Gateway environment:

```dotenv
WEKNORA_MCP_URL=https://mcp.internal.example/mcp
WEKNORA_MCP_TOKEN=the-same-value-as-MCP_SERVER_AUTH_TOKEN
```

Merge the example entry into the real `extensions_config.json` without
replacing other servers, then enable it in Capability Center or through the
existing MCP configuration API. The effective entry is:

```json
{
  "enabled": true,
  "type": "http",
  "url": "$WEKNORA_MCP_URL",
  "headers": {
    "X-MCP-Auth-Token": "$WEKNORA_MCP_TOKEN"
  },
  "tool_name_prefix": true,
  "session_init_timeout": 30,
  "description": "Read-only WeKnora document retrieval",
  "routing": {
    "mode": "prefer",
    "priority": 90,
    "keywords": ["WeKnora", "知识库", "内部文档", "knowledge base"]
  }
}
```

DeerFlow exposes the tool as `weknora_search_knowledge_base`. Routing metadata
prefers it for matching questions and allows deferred discovery through
`tool_search`; it does not force retrieval on every turn. The existing
`tool_call_timeout` field does not bound ordinary HTTP MCP calls, so the service
enforces its own total deadline.

Run the DeerFlow integration test:

```bash
cd backend
.venv/bin/python -m pytest tests/test_weknora_mcp.py -q
```

Then start DeerFlow and open a new conversation. Ask:

```text
根据 WeKnora 知识库回答：<已知文档问题>。请注明文档标题和引用标识。
```

In **Token Usage → Debug**, verify that DeerFlow called
`weknora_search_knowledge_base`. Compare the answer's title, quoted fact, and
`weknora:<kb>:<document>:<chunk>` identifier with the MCP result and the source
document in WeKnora. Also test a no-hit question and a stopped MCP service; the
answer must distinguish missing evidence from retrieval failure and must not
invent a source URL.

## Rollback and rotation

Disable only the `weknora` entry. DeerFlow's existing configuration-signature
invalidation removes the tool without changing sibling MCP servers. Stop or
roll back the independent service separately; no WeKnora data is mutated.

To rotate the MCP service token, update both deployments and reload/restart them
according to the deployment platform. Rotate the WeKnora API key only in the MCP
service. Gateway environment changes normally require a restart; edits made
through the runtime MCP configuration path use the existing cache invalidation.
