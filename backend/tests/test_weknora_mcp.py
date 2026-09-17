"""DeerFlow-side contract tests for the remote WeKnora MCP integration."""

from __future__ import annotations

import asyncio
import json
import secrets
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest
import uvicorn
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from starlette.responses import JSONResponse

from app.gateway.routers.mcp import McpServerConfigResponse, _mask_server_config
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.mcp.client import build_server_params
from deerflow.mcp.tools import get_mcp_tools
from deerflow.tools.builtins.tool_search import get_mcp_routing_hints_prompt_section
from deerflow.tools.mcp_metadata import get_mcp_routing

_KB_ID = "11111111-1111-4111-8111-111111111111"
_MCP_TOKEN = "deerflow-weknora-test-service-token"


def _example_path() -> Path:
    return Path(__file__).resolve().parents[2] / "extensions_config.example.json"


def _write_extensions_config(path: Path, url: str) -> None:
    example = json.loads(_example_path().read_text(encoding="utf-8"))
    weknora = deepcopy(example["mcpServers"]["weknora"])
    weknora["enabled"] = True
    weknora["url"] = url
    path.write_text(json.dumps({"mcpServers": {"weknora": weknora}}), encoding="utf-8")


class _ServiceTokenMiddleware:
    def __init__(self, application, expected_token: str, accepted_requests: list[str]) -> None:
        self._application = application
        self._expected_token = expected_token.encode("ascii")
        self._accepted_requests = accepted_requests

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http" and scope.get("path") == "/mcp":
            values = [value for name, value in scope.get("headers", []) if name.lower() == b"x-mcp-auth-token"]
            if len(values) != 1 or not secrets.compare_digest(values[0], self._expected_token):
                await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
                return
            self._accepted_requests.append(scope["path"])
        await self._application(scope, receive, send)


@asynccontextmanager
async def _synthetic_weknora_server() -> AsyncIterator[tuple[str, list[str], list[str]]]:
    queries: list[str] = []
    accepted_requests: list[str] = []
    server = FastMCP("Synthetic WeKnora", stateless_http=True, json_response=True)

    @server.tool(
        name="search_knowledge_base",
        description="Search read-only internal documents and cite returned identifiers.",
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
        structured_output=True,
    )
    async def search_knowledge_base(query: str, top_k: int = 5) -> dict[str, object]:
        queries.append(query)
        return {
            "searched_knowledge_base_ids": [_KB_ID],
            "results": [
                {
                    "citation": f"weknora:{_KB_ID}:document-1:chunk-1",
                    "knowledge_base_id": _KB_ID,
                    "knowledge_id": "document-1",
                    "chunk_id": "chunk-1",
                    "title": "操作手册",
                    "filename": "manual.md",
                    "content": "重启前先保存。",
                    "score": 0.8,
                    "chunk_index": 3,
                    "truncated": False,
                }
            ][:top_k],
        }

    application = _ServiceTokenMiddleware(server.streamable_http_app(), _MCP_TOKEN, accepted_requests)
    server_socket = socket.socket()
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(("127.0.0.1", 0))
    server_socket.listen()
    server_socket.setblocking(False)
    port = server_socket.getsockname()[1]
    uvicorn_server = uvicorn.Server(uvicorn.Config(application, log_level="error", lifespan="on"))
    server_task = asyncio.create_task(uvicorn_server.serve(sockets=[server_socket]))
    try:
        for _ in range(500):
            if uvicorn_server.started:
                break
            if server_task.done():
                await server_task
            await asyncio.sleep(0.01)
        else:
            raise TimeoutError("Timed out starting the synthetic WeKnora MCP server")
        yield f"http://127.0.0.1:{port}/mcp", queries, accepted_requests
    finally:
        uvicorn_server.should_exit = True
        await server_task
        server_socket.close()


def test_example_registers_a_disabled_remote_service_without_upstream_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    example = json.loads(_example_path().read_text(encoding="utf-8"))
    raw = example["mcpServers"]["weknora"]

    assert raw["enabled"] is False
    assert raw["type"] == "http"
    assert raw["url"] == "$WEKNORA_MCP_URL"
    assert raw["headers"] == {"X-MCP-Auth-Token": "$WEKNORA_MCP_TOKEN"}
    assert raw["tool_name_prefix"] is True
    assert raw["routing"]["mode"] == "prefer"
    assert raw["routing"]["priority"] == 90
    assert {"WeKnora", "知识库", "内部文档", "knowledge base"} <= set(raw["routing"]["keywords"])
    assert {"command", "args", "cwd", "env"}.isdisjoint(raw)
    assert "WEKNORA_API_KEY" not in json.dumps(raw)
    assert "WEKNORA_KB_IDS" not in json.dumps(raw)

    monkeypatch.setenv("WEKNORA_MCP_URL", "https://mcp.internal.example/mcp")
    monkeypatch.setenv("WEKNORA_MCP_TOKEN", _MCP_TOKEN)
    config_path = tmp_path / "extensions_config.json"
    _write_extensions_config(config_path, "$WEKNORA_MCP_URL")
    extensions = ExtensionsConfig.from_file(str(config_path))
    server = extensions.mcp_servers["weknora"]
    params = build_server_params("weknora", server)
    masked = _mask_server_config(McpServerConfigResponse.model_validate(server.model_dump()))

    assert params == {
        "transport": "http",
        "url": "https://mcp.internal.example/mcp",
        "headers": {"X-MCP-Auth-Token": _MCP_TOKEN},
    }
    assert masked.headers == {"X-MCP-Auth-Token": "***"}
    assert _MCP_TOKEN not in masked.model_dump_json()


@pytest.mark.asyncio
async def test_real_http_adapter_puts_tool_result_in_the_next_model_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WEKNORA_MCP_TOKEN", _MCP_TOKEN)
    async with _synthetic_weknora_server() as (url, queries, accepted_requests):
        config_path = tmp_path / "extensions_config.json"
        _write_extensions_config(config_path, url)
        extensions = ExtensionsConfig.from_file(str(config_path))
        with patch("deerflow.mcp.tools.ExtensionsConfig.from_file", return_value=extensions):
            tools = await get_mcp_tools()

        assert [tool.name for tool in tools] == ["weknora_search_knowledge_base"]
        tool = tools[0]
        routing = get_mcp_routing(tool)
        assert routing == {
            "mode": "prefer",
            "priority": 90,
            "keywords": ["WeKnora", "知识库", "内部文档", "knowledge base"],
        }
        routing_prompt = get_mcp_routing_hints_prompt_section(tools, deferred_names=frozenset({tool.name}))
        assert "use `tool_search` to fetch `weknora_search_knowledge_base`" in routing_prompt

        next_model_messages: list[object] = []

        async def observe_next_model_request(state: MessagesState) -> dict[str, list[AIMessage]]:
            next_model_messages.extend(state["messages"])
            return {"messages": [AIMessage(content="已根据检索结果回答。")]}

        graph = StateGraph(MessagesState)
        graph.add_node("tools", ToolNode(tools))
        graph.add_node("model", observe_next_model_request)
        graph.add_edge(START, "tools")
        graph.add_edge("tools", "model")
        graph.add_edge("model", END)
        initial = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": tool.name,
                    "args": {"query": "如何重启", "top_k": 3},
                    "id": "call-weknora-1",
                    "type": "tool_call",
                }
            ],
        )
        result = await graph.compile().ainvoke({"messages": [initial]})

    tool_messages = [message for message in next_model_messages if isinstance(message, ToolMessage)]
    assert len(tool_messages) == 1
    assert tool_messages[0].name == "weknora_search_knowledge_base"
    assert f"weknora:{_KB_ID}:document-1:chunk-1" in str(tool_messages[0].content)
    assert "重启前先保存" in str(tool_messages[0].content)
    assert any(isinstance(message, ToolMessage) for message in result["messages"])
    assert queries == ["如何重启"]
    assert accepted_requests
