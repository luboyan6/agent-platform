"""Native RBAC MCP role tests with synthetic, credential-free tools."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml
from langchain.agents.middleware.types import AgentState
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langchain_mcp_adapters.tools import convert_mcp_tool_to_langchain_tool
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from mcp.types import CallToolResult, TextContent
from mcp.types import Tool as MCPTool

from deerflow.agents.middlewares.tool_error_handling_middleware import build_lead_runtime_middlewares, build_subagent_runtime_middlewares
from deerflow.authz.adapter import GuardrailAuthorizationAdapter
from deerflow.authz.provider import AuthzRequest, Principal
from deerflow.authz.rbac import RbacAuthorizationProvider
from deerflow.authz.tool_filter import apply_tool_authorization
from deerflow.config.app_config import AppConfig
from deerflow.config.authorization_config import AuthorizationConfig, AuthorizationProviderConfig
from deerflow.config.extensions_config import ExtensionsConfig, McpServerConfig, RagMcpAccessConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.guardrails.middleware import GuardrailMiddleware
from deerflow.mcp import rag_access
from deerflow.mcp.interceptors import build_mcp_tool_interceptors
from deerflow.mcp.tools import get_mcp_tools
from deerflow.tools.builtins.tool_search import assemble_deferred_tools
from deerflow.tools.mcp_metadata import tag_mcp_tool


@pytest.fixture
def config():
    return AppConfig(
        sandbox=SandboxConfig(use="test"),
        authorization=AuthorizationConfig(
            enabled=True,
            provider=AuthorizationProviderConfig(
                use="deerflow.authz.rbac:RbacAuthorizationProvider",
                config={
                    "roles": {
                        "finance": {"tools": {"allow": ["web_search", "weknora-ai_search_knowledge"]}},
                        "aftersales": {"tools": {"allow": ["web_search", "weknora-mcp_search_knowledge"]}},
                        "user": {"tools": {"allow": ["web_search"]}},
                        "admin": {"tools": {"allow": "*"}},
                    }
                },
            ),
        ),
    )


@pytest.fixture
def catalog():
    return [
        tag_mcp_tool(
            StructuredTool.from_function(lambda: "synthetic result", name=f"{alias}_search_knowledge", description="synthetic MCP tool"),
            server_name=alias,
            transport="http",
            original_tool_name="search_knowledge",
        )
        for alias in ["weknora-ai", "weknora-mcp", "weknora-ai_extra"]
    ]


@pytest.mark.parametrize(
    "role,expected",
    [
        ("finance", ["weknora-ai_search_knowledge"]),
        ("aftersales", ["weknora-mcp_search_knowledge"]),
        ("user", []),
        (None, []),
        ("unknown", []),
    ],
)
def test_native_role_catalog_and_deferred_search(config, catalog, monkeypatch, role, expected):
    monkeypatch.setattr(rag_access, "project_rag_tools", MagicMock(side_effect=AssertionError("RAG projection is suspended")))
    filtered, provider = apply_tool_authorization(catalog, context={"user_id": "synthetic-user", "user_role": role}, app_config=config)
    assert provider is not None
    assert [tool.name for tool in filtered] == expected
    _, deferred = assemble_deferred_tools(filtered, enabled=True)
    assert deferred.deferred_names == frozenset(expected)
    assert len(catalog) == 3


def test_shared_catalog_is_not_mutated_between_roles(config, catalog):
    metadata = [dict(tool.metadata) for tool in catalog]
    for role, alias in [("finance", "weknora-ai"), ("aftersales", "weknora-mcp")]:
        filtered, _ = apply_tool_authorization(catalog, context={"user_role": role}, app_config=config)
        assert [tool.name for tool in filtered] == [f"{alias}_search_knowledge"]
    assert [tool.metadata for tool in catalog] == metadata


def test_mcp_interceptor_assembly_never_builds_rag_guard(monkeypatch):
    guard = MagicMock(side_effect=AssertionError("RAG guard is suspended"))
    monkeypatch.setattr(rag_access, "build_rag_access_interceptor", guard)
    # Patch the already-imported binding as well on the pre-change implementation.
    monkeypatch.setattr("deerflow.mcp.interceptors.build_rag_access_interceptor", guard, raising=False)
    config = ExtensionsConfig(mcp_servers={"plain": McpServerConfig(type="http", url="http://localhost/mcp")})
    assert build_mcp_tool_interceptors(config) == []
    guard.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("builder", [build_lead_runtime_middlewares, build_subagent_runtime_middlewares])
@pytest.mark.parametrize(
    "role,allowed,denied",
    [
        ("finance", "weknora-ai_search_knowledge", "weknora-mcp_search_knowledge"),
        ("aftersales", "weknora-mcp_search_knowledge", "weknora-ai_search_knowledge"),
    ],
)
async def test_parallel_native_execution_denies_before_transport(config, catalog, builder, role, allowed, denied):
    _, provider = apply_tool_authorization(catalog, context={"user_role": role}, app_config=config)
    middlewares = builder(app_config=config, authorization_provider=provider)
    middleware = next(item for item in middlewares if isinstance(item, GuardrailMiddleware) and isinstance(item.provider, GuardrailAuthorizationAdapter))
    sent = []

    async def transport(request):
        sent.append(request.tool_call["name"])
        return ToolMessage(content="synthetic success", tool_call_id=request.tool_call["id"])

    def request(name):
        return SimpleNamespace(
            tool_call={"name": name, "args": {}, "id": name},
            tool=next((tool for tool in catalog if tool.name == name), None),
            runtime=SimpleNamespace(context={"user_id": "synthetic-user", "user_role": role}),
        )

    results = await asyncio.gather(*(middleware.awrap_tool_call(request(name), transport) for name in [allowed, denied, "weknora-ai_extra_search_knowledge"]))
    assert results[0].status == "success"
    assert [result.status for result in results[1:]] == ["error", "error"]
    assert all("authz.denied" in result.content for result in results[1:])
    assert sent == [allowed]


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [None, "user", "unknown"])
async def test_default_and_unknown_role_cannot_execute_mcp(config, catalog, role):
    _, provider = apply_tool_authorization(catalog, context={"user_role": role}, app_config=config)
    middleware = next(item for item in build_lead_runtime_middlewares(app_config=config, authorization_provider=provider) if isinstance(item, GuardrailMiddleware))
    transport = AsyncMock()
    request = SimpleNamespace(tool_call={"name": catalog[0].name, "args": {}, "id": "denied"}, tool=catalog[0], runtime=SimpleNamespace(context={"user_role": role}))
    result = await middleware.awrap_tool_call(request, transport)
    assert result.status == "error"
    transport.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("role,allowed_alias,denied_alias", [("finance", "weknora-ai", "weknora-mcp"), ("aftersales", "weknora-mcp", "weknora-ai")])
async def test_discovered_adapter_in_graph_uses_native_guard_before_mcp_session(config, monkeypatch, role, allowed_alias, denied_alias):
    """Exercise real discovery, adapters, ToolNode and native execution gating."""
    # Retained legacy ACL fields must not re-enable the suspended runtime path.
    extensions = ExtensionsConfig(
        mcp_servers={alias: McpServerConfig(type="http", url=f"http://localhost/{alias}", headers={"Authorization": "Bearer synthetic"}, rag_access=RagMcpAccessConfig(roles=["user"])) for alias in [allowed_alias, denied_alias]}
    )
    opened, sent = [], []

    class Client:
        def __init__(self, connections, *, tool_interceptors, **kwargs):
            self.connections, self.interceptors = connections, tool_interceptors

        async def get_tools(self, server_name):
            return [
                convert_mcp_tool_to_langchain_tool(
                    None,
                    MCPTool(name=name, description="synthetic", inputSchema={"type": "object", "properties": {"session_id": {"type": "string"}}}),
                    connection=self.connections[server_name],
                    server_name=server_name,
                    tool_interceptors=self.interceptors,
                    tool_name_prefix=True,
                )
                for name in ["search_knowledge", "ask"]
            ]

    class Session:
        async def initialize(self):
            pass

        async def call_tool(self, name, args, **kwargs):
            sent.append((name, args))
            return CallToolResult(content=[TextContent(type="text", text="synthetic")])

    class SessionContext:
        def __init__(self, connection, **kwargs):
            opened.append(connection["url"])

        async def __aenter__(self):
            return Session()

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr("langchain_mcp_adapters.client.MultiServerMCPClient", Client)
    monkeypatch.setattr("langchain_mcp_adapters.tools.create_session", SessionContext)
    tools = await get_mcp_tools(extensions_config=extensions)
    assert all("session_id" in tool.args_schema["properties"] for tool in tools)
    _, provider = apply_tool_authorization(tools, context={"user_role": role}, app_config=config)
    middleware = next(item for item in build_lead_runtime_middlewares(app_config=config, authorization_provider=provider) if isinstance(item, GuardrailMiddleware))
    # Include the denied tool deliberately to test Layer 2 independently of
    # assembly-time hiding. It must never open a remote session.
    graph = StateGraph(AgentState, context_schema=dict)
    graph.add_node("tools", ToolNode(tools, awrap_tool_call=middleware.awrap_tool_call))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    result = await graph.compile().ainvoke(
        {"messages": [AIMessage(content="", tool_calls=[{"name": f"{alias}_search_knowledge", "args": {}, "id": alias} for alias in [allowed_alias, denied_alias]])]}, context={"user_id": "synthetic-user", "user_role": role}
    )
    messages = {message.tool_call_id: message for message in result["messages"] if message.type == "tool"}
    assert messages[allowed_alias].status == "success"
    assert messages[denied_alias].status == "error"
    assert "authz.denied" in messages[denied_alias].content
    assert opened == [f"http://localhost/{allowed_alias}"]
    assert sent == [("search_knowledge", {})]


@pytest.mark.parametrize("role,own,other", [("finance", "weknora-ai", "weknora-mcp"), ("aftersales", "weknora-mcp", "weknora-ai")])
def test_reference_role_policies_allow_only_assigned_read_tools(role, own, other):
    root = Path(__file__).resolve().parents[2]
    roles = yaml.safe_load((root / "config.native-rbac-mcp.example.yaml").read_text(encoding="utf-8"))["authorization"]["provider"]["config"]["roles"]
    provider = RbacAuthorizationProvider(roles=roles)
    read_tools = ["list_knowledge_bases", "search_knowledge", "grep_chunks", "list_documents", "read_document", "ask", "wiki_search", "wiki_read_page", "wiki_index"]
    denied_tools = [f"{other}_{name}" for name in read_tools] + [f"{own}_{name}" for name in ["add_document", "update_document", "delete_document", "new_remote_tool"]] + ["update_agent", "weknora-agent_search_knowledge"]
    principal = Principal(role=role)
    assert provider.filter_resources(principal, "tool", [f"{own}_{name}" for name in read_tools]) == [f"{own}_{name}" for name in read_tools]
    assert provider.filter_resources(principal, "tool", denied_tools) == []
    assert all(not provider.authorize(AuthzRequest(principal=principal, resource="tool", action="call", target=name)).allow for name in denied_tools)


def test_reference_connections_use_environment_headers_without_rag_access(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    for name in ["WEKNORA_FINANCE_AUTHORIZATION", "WEKNORA_AFTERSALES_AUTHORIZATION"]:
        monkeypatch.setenv(name, "Bearer synthetic-credential")
    extensions = ExtensionsConfig.from_file(str(root / "extensions_config.example.json"))
    for alias in ["weknora-ai", "weknora-mcp"]:
        server = extensions.mcp_servers[alias]
        assert server.enabled is False
        assert server.type == "http" and server.tool_name_prefix is True
        assert server.rag_access is None
        assert server.headers["Authorization"] == "Bearer synthetic-credential"
