"""RAG admission tests through the native adapter and real account repository."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from langchain.agents import AgentState
from langchain_core.messages import AIMessage
from langchain_core.tools import ToolException
from langchain_mcp_adapters.interceptors import MCPToolCallRequest
from langchain_mcp_adapters.tools import convert_mcp_tool_to_langchain_tool
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from mcp.types import CallToolResult, TextContent
from mcp.types import Tool as MCPTool
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.gateway import rag_mcp_access as gateway_access
from app.gateway.auth.local_provider import LocalAuthProvider
from app.gateway.auth.models import User
from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
from deerflow.config.extensions_config import ExtensionsConfig, atomic_write_extensions_config
from deerflow.mcp import rag_access
from deerflow.mcp.interceptors import build_mcp_tool_interceptors, compose_tool_interceptors
from deerflow.mcp.tools import get_mcp_tools
from deerflow.persistence.user.model import UserRow


def endpoint(roles, token="Bearer fixture-token"):
    return {"type": "http", "url": "http://localhost/" + roles[0] if roles else "http://localhost/empty", "headers": {"Authorization": token}, "rag_access": {"roles": roles}}


def actor(role="user", source="session", user_id="actor"):
    return {"user_id": user_id, "user_role": role, "authz_attributes": {"auth_source": source}, "is_internal": source == "internal"}


@pytest.fixture
def policy(tmp_path, monkeypatch):
    path = tmp_path / "extensions.json"
    data = {"mcpServers": {"reader": endpoint(["user"], "Bearer reader-fixture"), "restricted": endpoint(["admin"], "Bearer admin-fixture")}, "skills": {}}
    atomic_write_extensions_config(path, data)
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(path))
    # Config API tests reload this singleton; restore the previous process state
    # after each fixture so later suites cannot inherit an expired temp config.
    monkeypatch.setattr("deerflow.config.extensions_config._extensions_config", None)
    previous_aliases = rag_access.reset_rag_protected_aliases()
    previous_resolver = rag_access.set_rag_role_resolver(AsyncMock(return_value="user"))
    try:
        yield path, data
    finally:
        rag_access.set_rag_role_resolver(previous_resolver)
        rag_access.reset_rag_protected_aliases(previous_aliases)


def request(alias="reader", name="search_knowledge", context=None, args=None, headers=None):
    return MCPToolCallRequest(name=name, args=args or {}, server_name=alias, headers=headers, runtime=SimpleNamespace(context=actor() if context is None else context))


@pytest.mark.asyncio
async def test_parallel_admission_denies_only_forbidden_business_call(policy):
    guard = rag_access.build_rag_access_interceptor(ExtensionsConfig.from_file())
    sent = []

    async def transport(req):
        sent.append(req.server_name)
        return "ok"

    results = await asyncio.gather(guard(request(), transport), guard(request("restricted"), transport), return_exceptions=True)
    assert results[0] == "ok"
    assert isinstance(results[1], ToolException) and "RAG_ACCESS_DENIED" in str(results[1])
    assert sent == ["reader"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change,code",
    [
        ("revoke", "RAG_ACCESS_DENIED"),
        ("remove_policy", "RAG_ACCESS_DENIED"),
        ("disable", "RAG_ACCESS_DENIED"),
        ("delete", "RAG_ACCESS_DENIED"),
        ("url", "RAG_CONNECTION_CHANGED"),
        ("token", "RAG_CONNECTION_CHANGED"),
        ("invalid", "RAG_AUTH_UNAVAILABLE"),
        ("missing", "RAG_AUTH_UNAVAILABLE"),
    ],
)
async def test_cached_call_rereads_policy_and_connection(policy, change, code):
    path, data = policy
    guard = rag_access.build_rag_access_interceptor(ExtensionsConfig.from_file())
    transport = AsyncMock(return_value="ok")
    assert await guard(request(), transport) == "ok"
    transport.reset_mock()
    if change == "revoke":
        data["mcpServers"]["reader"]["rag_access"]["roles"] = []
    elif change == "remove_policy":
        del data["mcpServers"]["reader"]["rag_access"]
    elif change == "disable":
        data["mcpServers"]["reader"]["enabled"] = False
    elif change == "delete":
        del data["mcpServers"]["reader"]
    elif change == "url":
        data["mcpServers"]["reader"]["url"] = "http://localhost/changed"
    elif change == "token":
        data["mcpServers"]["reader"]["headers"]["Authorization"] = "Bearer changed-fixture"
    if change == "invalid":
        path.write_text("{")
    elif change == "missing":
        path.unlink()
    else:
        atomic_write_extensions_config(path, data)
    with pytest.raises(ToolException, match=code):
        await guard(request(), transport)
    transport.assert_not_awaited()
    if change == "remove_policy":
        rebuilt = rag_access.build_rag_access_interceptor(ExtensionsConfig.from_file())
        with pytest.raises(ToolException, match=code):
            await rebuilt(request(), transport)


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["pat", "internal", "auth_disabled", None, "cli"])
async def test_non_web_sources_denied_even_with_admin_role(policy, source):
    guard = rag_access.build_rag_access_interceptor(ExtensionsConfig.from_file())
    transport = AsyncMock()
    with pytest.raises(ToolException, match="RAG_ACCESS_DENIED"):
        await guard(request(context=actor("admin", source)), transport)
    transport.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [None, "unknown", "admin"])
async def test_no_deleted_account_default_role_or_admin_bypass(policy, role):
    rag_access.set_rag_role_resolver(AsyncMock(return_value=role))
    transport = AsyncMock()
    with pytest.raises(ToolException, match="RAG_ACCESS_DENIED"):
        await rag_access.build_rag_access_interceptor(ExtensionsConfig.from_file())(request(), transport)
    transport.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("resolver", [None, AsyncMock(side_effect=RuntimeError("database fixture unavailable"))])
async def test_missing_or_failed_account_authority_has_no_fallback(policy, resolver):
    rag_access.set_rag_role_resolver(resolver)
    transport = AsyncMock()
    with pytest.raises(ToolException, match="RAG_AUTH_UNAVAILABLE"):
        await rag_access.build_rag_access_interceptor(ExtensionsConfig.from_file())(request(), transport)
    transport.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("name,args,code", [("delete_knowledge_base", {}, "RAG_TOOL_DENIED"), ("ask", {"question": "q", "session_id": "foreign-session"}, "RAG_SESSION_REUSE_DENIED")])
async def test_forged_tool_or_session_cannot_reach_transport(policy, name, args, code):
    transport = AsyncMock()
    with pytest.raises(ToolException, match=code):
        await rag_access.build_rag_access_interceptor(ExtensionsConfig.from_file())(request(name=name, args=args), transport)
    transport.assert_not_awaited()


@pytest.mark.asyncio
async def test_final_guard_sees_custom_interceptor_modifications(policy):
    guard = rag_access.build_rag_access_interceptor(ExtensionsConfig.from_file())
    transport = AsyncMock()

    async def substitute(req, handler):
        return await handler(req.override(name="delete_knowledge_base"))

    chain = compose_tool_interceptors([substitute, guard], transport)
    with pytest.raises(ToolException, match="RAG_TOOL_DENIED"):
        await chain(request())
    with pytest.raises(ToolException, match="RAG_CONNECTION_CHANGED"):
        await guard(request(headers={"authorization": "Bearer other-fixture"}), transport)
    transport.assert_not_awaited()


@pytest.mark.asyncio
async def test_live_policy_added_after_tool_construction_is_enforced(policy):
    path, data = policy
    del data["mcpServers"]["reader"]["rag_access"]
    atomic_write_extensions_config(path, data)
    guard = rag_access.build_rag_access_interceptor(ExtensionsConfig.from_file())
    data["mcpServers"]["reader"]["rag_access"] = {"roles": ["admin"]}
    atomic_write_extensions_config(path, data)
    transport = AsyncMock()
    with pytest.raises(ToolException, match="RAG_ACCESS_DENIED"):
        await guard(request(), transport)
    transport.assert_not_awaited()


@pytest.mark.asyncio
async def test_discovered_native_adapter_tools_parallel_and_fresh_ask(policy, monkeypatch):
    # Opt into the retained RAG guard/schema wrapper explicitly. Production
    # assembly suspends both while native RBAC is being tested.
    def retained_interceptors(config, **kwargs):
        return [*build_mcp_tool_interceptors(config, **kwargs), rag_access.build_rag_access_interceptor(config)]

    monkeypatch.setattr("deerflow.mcp.tools.build_mcp_tool_interceptors", retained_interceptors)
    business_calls, opened = [], []

    class Client:
        def __init__(self, connections, *, tool_interceptors, **kwargs):
            self.connections, self.interceptors = connections, tool_interceptors

        async def get_tools(self, server_name):
            return [
                convert_mcp_tool_to_langchain_tool(
                    None,
                    MCPTool(name=name, description="Reuse session_id", inputSchema={"type": "object", "properties": {"question": {"type": "string"}, "session_id": {"type": "string"}}}),
                    connection=self.connections[server_name],
                    server_name=server_name,
                    tool_interceptors=self.interceptors,
                    tool_name_prefix=True,
                )
                for name in ("search_knowledge", "ask", "delete_knowledge_base")
            ]

    class Session:
        def __init__(self, connection):
            self.connection = connection

        async def initialize(self):
            pass

        async def call_tool(self, name, args, **kwargs):
            business_calls.append((self.connection["url"], self.connection["headers"]["Authorization"], name, args))
            return CallToolResult(content=[TextContent(type="text", text="fixture answer")])

    class SessionContext:
        def __init__(self, connection, **kwargs):
            opened.append(connection["url"])
            self.session = Session(connection)

        async def __aenter__(self):
            return self.session

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr("langchain_mcp_adapters.client.MultiServerMCPClient", Client)
    monkeypatch.setattr("langchain_mcp_adapters.tools.create_session", SessionContext)
    tools = [rag_access.stateless_rag_tool(tool, tool.name.split("_", 1)[1]) for tool in await get_mcp_tools()]
    ask = next(tool for tool in tools if tool.name == "reader_ask")
    assert "session_id" not in ask.args_schema["properties"]
    assert "Reuse session_id" not in ask.description
    builder = StateGraph(AgentState, context_schema=dict)
    builder.add_node("tools", ToolNode(tools))
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    graph = builder.compile()
    calls = [{"name": "reader_ask", "args": {"question": "fixture"}, "id": "ok"}, {"name": "restricted_search_knowledge", "args": {}, "id": "deny"}, {"name": "reader_delete_knowledge_base", "args": {}, "id": "write"}]
    result = await graph.ainvoke({"messages": [AIMessage(content="", tool_calls=calls)]}, context=actor())
    messages = {message.tool_call_id: message for message in result["messages"] if message.type == "tool"}
    assert messages["ok"].status == "success"
    assert "RAG_ACCESS_DENIED" in messages["deny"].content
    assert "RAG_TOOL_DENIED" in messages["write"].content
    assert opened == ["http://localhost/user"]
    assert business_calls == [("http://localhost/user", "Bearer reader-fixture", "ask", {"question": "fixture", "session_id": ""})]
    business_calls.clear()
    forged = [{"name": "reader_ask", "args": {"question": "fixture", "session_id": "foreign"}, "id": "forged"}]
    result = await graph.ainvoke({"messages": [AIMessage(content="", tool_calls=forged)]}, context=actor())
    assert "RAG_SESSION_REUSE_DENIED" in result["messages"][-1].content
    assert business_calls == []
    # Independently granted parallel endpoints must keep their own credentials.
    path, data = policy
    data["mcpServers"]["restricted"]["rag_access"]["roles"].append("user")
    atomic_write_extensions_config(path, data)
    result = await graph.ainvoke({"messages": [AIMessage(content="", tool_calls=calls[:2])]}, context=actor())
    assert all(message.status == "success" for message in result["messages"] if message.type == "tool")
    assert sorted((url, token) for url, token, _name, _args in business_calls) == [("http://localhost/admin", "Bearer admin-fixture"), ("http://localhost/user", "Bearer reader-fixture")]
    business_calls.clear()
    sync_call = [{"name": "reader_ask", "args": {"question": "fixture sync"}, "id": "sync"}]
    result = await asyncio.to_thread(graph.invoke, {"messages": [AIMessage(content="", tool_calls=sync_call)]}, context=actor())
    assert result["messages"][-1].status == "success"
    assert business_calls == [("http://localhost/user", "Bearer reader-fixture", "ask", {"question": "fixture sync", "session_id": ""})]


@pytest_asyncio.fixture
async def accounts(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/users.db")
    async with engine.begin() as connection:
        await connection.run_sync(UserRow.__table__.create)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repository = SQLiteUserRepository(sessions)
    user = await repository.create_user(User(email="rag-fixture@example.com", system_role="admin"))
    monkeypatch.setattr(gateway_access, "get_local_provider", lambda: LocalAuthProvider(repository))
    try:
        yield repository, user, sessions
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("revocation", ["demote", "delete", "unavailable"])
async def test_gateway_reads_current_accounts_across_worker_loops(policy, accounts, monkeypatch, revocation):
    repository, user, sessions = accounts
    owner = str(user.id)
    guard = rag_access.build_rag_access_interceptor(ExtensionsConfig.from_file())
    transport = AsyncMock(return_value="ok")
    req = request("restricted", context=actor("admin", user_id=owner))
    async with gateway_access.rag_mcp_authority():
        assert await asyncio.to_thread(lambda: asyncio.run(guard(req, transport))) == "ok"
        if revocation == "demote":
            await repository.create_user(User(email="remaining-admin@example.com", system_role="admin"))
            await repository.update_system_role(owner, "user")
        elif revocation == "delete":
            async with sessions() as session:
                await session.execute(delete(UserRow).where(UserRow.id == owner))
                await session.commit()
        else:
            monkeypatch.setattr(repository, "get_user_by_id", AsyncMock(side_effect=RuntimeError("fixture database failure")))
        transport.reset_mock()
        code = "RAG_AUTH_UNAVAILABLE" if revocation == "unavailable" else "RAG_ACCESS_DENIED"
        with pytest.raises(ToolException, match=code):
            await asyncio.to_thread(lambda: asyncio.run(guard(req, transport)))
        transport.assert_not_awaited()


def test_bad_resolved_headers_never_expose_fixture_secret(policy, caplog):
    path, data = policy
    secret = "Bearer private-fixture\nunsafe"
    data["mcpServers"]["reader"]["headers"]["Authorization"] = secret
    atomic_write_extensions_config(path, data)
    with pytest.raises(ToolException) as exc:
        rag_access.build_rag_access_interceptor(ExtensionsConfig.from_file())
    assert "private-fixture" not in str(exc.value) + caplog.text


def test_policy_validation_error_never_exposes_resolved_secret(policy):
    path, data = policy
    data["mcpServers"]["reader"]["tool_name_prefix"] = False
    path.write_text(json.dumps(data))
    with pytest.raises(ToolException) as exc:
        rag_access.read_rag_policy()
    assert "reader-fixture" not in str(exc.value)


@pytest.mark.asyncio
async def test_read_failure_and_unstable_revision_deny_before_transport(policy, monkeypatch):
    guard = rag_access.build_rag_access_interceptor(ExtensionsConfig.from_file())
    transport = AsyncMock()
    monkeypatch.setattr(rag_access, "get_config_signature", lambda path: None)
    with pytest.raises(ToolException, match="RAG_AUTH_UNAVAILABLE"):
        await guard(request(), transport)
    transport.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_optional_config_cannot_drop_known_protection(policy, monkeypatch):
    guard = rag_access.build_rag_access_interceptor(ExtensionsConfig.from_file())
    monkeypatch.setattr(ExtensionsConfig, "resolve_config_path", lambda: None)
    transport = AsyncMock()
    with pytest.raises(ToolException, match="RAG_AUTH_UNAVAILABLE"):
        await guard(request(), transport)
    transport.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_runtime_does_not_inherit_ambient_web_authority(policy):
    transport = AsyncMock()
    req = MCPToolCallRequest(name="ask", args={"question": "fixture"}, server_name="reader", runtime=None)
    with pytest.raises(ToolException, match="RAG_ACCESS_DENIED"):
        await rag_access.build_rag_access_interceptor(ExtensionsConfig.from_file())(req, transport)
    transport.assert_not_awaited()


@pytest.mark.asyncio
async def test_already_admitted_call_completes_but_next_call_observes_revocation(policy):
    path, data = policy
    guard = rag_access.build_rag_access_interceptor(ExtensionsConfig.from_file())
    admitted, release = asyncio.Event(), asyncio.Event()
    sent = []

    async def transport(req):
        sent.append(req.server_name)
        admitted.set()
        await release.wait()
        return "ok"

    pending = asyncio.create_task(guard(request(), transport))
    try:
        await admitted.wait()
        data["mcpServers"]["reader"]["rag_access"]["roles"] = []
        atomic_write_extensions_config(path, data)
        release.set()
        assert await pending == "ok"
        with pytest.raises(ToolException, match="RAG_ACCESS_DENIED"):
            await guard(request(), transport)
        assert sent == ["reader"]
    finally:
        release.set()
        await pending


@pytest.mark.asyncio
async def test_non_rag_connection_does_not_require_web_identity_or_role_lookup(policy):
    path, data = policy
    data["mcpServers"]["legacy"] = {"type": "http", "url": "http://localhost/legacy"}
    atomic_write_extensions_config(path, data)
    rag_access.set_rag_role_resolver(None)
    guard = rag_access.build_rag_access_interceptor(ExtensionsConfig.from_file())
    transport = AsyncMock(return_value="legacy result")
    assert await guard(request("legacy", name="write", context={}), transport) == "legacy result"
    transport.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_optional_custom_interceptor_cannot_remove_guard(policy):
    config = ExtensionsConfig.from_file().model_copy(update={"mcpInterceptors": ["missing:builder"]})

    def unavailable(path):
        raise ImportError("fixture builder absent")

    chain = [*build_mcp_tool_interceptors(config, resolver=unavailable), rag_access.build_rag_access_interceptor(config)]
    transport = AsyncMock()
    with pytest.raises(ToolException, match="RAG_ACCESS_DENIED"):
        await compose_tool_interceptors(chain, transport)(request("restricted"))
    transport.assert_not_awaited()


@pytest.mark.asyncio
async def test_description_and_routing_changes_do_not_change_connection_identity(policy):
    path, data = policy
    guard = rag_access.build_rag_access_interceptor(ExtensionsConfig.from_file())
    data["mcpServers"]["reader"].update({"description": "updated description", "routing": {"mode": "off"}})
    atomic_write_extensions_config(path, data)
    transport = AsyncMock(return_value="ok")
    assert await guard(request(args={"kb_ids": ["foreign-id"], "query": "fixture question"}), transport) == "ok"
    # Resource selectors reach RAG unchanged for its endpoint-scope check.
    assert transport.call_args.args[0].args == {"kb_ids": ["foreign-id"], "query": "fixture question"}
