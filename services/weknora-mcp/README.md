# WeKnora MCP retrieval service

This package exposes one read-only `search_knowledge_base` tool over stateless
MCP Streamable HTTP. It calls WeKnora's `POST /api/v1/knowledge-search?resource_urls=handle`
endpoint, limits the configured knowledge-base scope, and returns bounded
snippets with stable `weknora:<kb>:<document>:<chunk>` citation identifiers.

The service is independently built and deployed. It does not import DeerFlow,
share DeerFlow's Python environment, or expose WeKnora's administrative tools.
Its independent lock pins the MCP Python SDK to `mcp==2.2.0`.

## Run locally

```bash
cp .env.example .env
# Edit .env with a retrieve-capable WeKnora key, allowed KB ids, and a random
# MCP_SERVER_AUTH_TOKEN that is different from the WeKnora key.
uv sync --locked
uv run --env-file .env --locked weknora-mcp
```

The endpoints are:

- `GET /health` — unauthenticated liveness response with no configuration data.
- `POST /mcp` — stateless Streamable HTTP; every request requires
  `X-MCP-Auth-Token`.

For containers:

```bash
cp .env.example .env
# Edit .env, then:
docker compose up --build -d
curl --fail http://127.0.0.1:8000/health
```

Compose publishes only on loopback unless `MCP_BIND_HOST` is set explicitly.
Across hosts, use HTTPS or an encrypted private network. Configure
`MCP_ALLOWED_HOSTS` for the Host value seen by the service and add only the
origins the deployment actually uses.

## Test

```bash
uv run --locked pytest -q -W error
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
```

The suite covers upstream request/response contracts, allowlisted scope,
bounded concurrency and response size, source-identity validation,
timeout/error sanitization, service authentication, Host/Origin checks, and
real HTTP MCP initialize/list/call including same-endpoint restart recovery.

See [the DeerFlow operator guide](../../backend/docs/WEKNORA_MCP.md) for client
registration, end-to-end verification, deployment checks, and rollback.
