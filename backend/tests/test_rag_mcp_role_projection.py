"""Config compatibility and run-local RAG catalog isolation."""

import json
from types import SimpleNamespace

import pytest
from langchain_core.tools import StructuredTool
from pydantic import ValidationError
from test_rag_mcp_access import actor, endpoint
from test_rag_mcp_access import policy as policy

from app.gateway.routers import mcp as router
from app.gateway.services import inject_authenticated_user_context
from deerflow.authz.tool_filter import apply_tool_authorization
from deerflow.config.extensions_config import ExtensionsConfig, McpServerConfig, atomic_write_extensions_config
from deerflow.mcp import rag_access
from deerflow.tools.mcp_metadata import tag_mcp_tool


def tool(alias, original):
    item = StructuredTool.from_function(lambda: "fixture", name=f"{alias}_{original}", description="fixture")
    return tag_mcp_tool(item, server_name=alias, transport="http", original_tool_name=original)


@pytest.mark.parametrize(
    "role,source,expected", [("user", "session", ["reader_search_knowledge"]), ("admin", "session", ["restricted_search_knowledge"]), (None, "session", []), ("unknown", "session", []), ("user", "pat", []), ("admin", "internal", [])]
)
def test_projection_independent_of_general_auth_and_catalog_mutation(policy, role, source, expected):
    items = [tool("reader", "search_knowledge"), tool("restricted", "search_knowledge"), tool("reader", "delete_knowledge_base"), tool("legacy", "anything")]
    original_metadata = [dict(item.metadata) for item in items]
    # Retained RAG projection is tested explicitly; production uses native RBAC.
    projected = rag_access.project_rag_tools(items, actor(role, source))
    assert [item.name for item in projected] == expected + ["legacy_anything"]
    assert len(items) == 4
    assert [item.metadata for item in items] == original_metadata
    # A different user can build from the same shared catalog.
    assert [item.name for item in rag_access.project_rag_tools(items, actor("admin"))] == ["restricted_search_knowledge", "legacy_anything"]


def test_exact_source_metadata_prevents_prefix_ambiguity(policy):
    path, data = policy
    data["mcpServers"]["reader_extra"] = endpoint(["admin"])
    atomic_write_extensions_config(path, data)
    items = [tool("reader", "search_knowledge"), tool("reader_extra", "search_knowledge")]
    assert rag_access.project_rag_tools(items, actor()) == [items[0]]


def test_general_authorization_can_only_narrow_rag_grants(policy):
    from deerflow.config.authorization_config import AuthorizationConfig, AuthorizationProviderConfig

    config = SimpleNamespace(
        authorization=AuthorizationConfig(enabled=True, provider=AuthorizationProviderConfig(use="deerflow.authz.rbac:RbacAuthorizationProvider", config={"roles": {"user": {"tools": {"allow": ["restricted_search_knowledge"]}}}}))
    )
    rag_tools = rag_access.project_rag_tools([tool("reader", "search_knowledge"), tool("restricted", "search_knowledge")], actor())
    projected, provider = apply_tool_authorization(rag_tools, context=actor(), app_config=config)
    assert projected == []
    assert provider is not None


@pytest.mark.parametrize(
    "change",
    [
        {"rag_access": None},
        {"rag_access": {"roles": ["superuser"]}},
        {"rag_access": {"roles": ["*"]}},
        {"rag_access": {"roles": ["user"], "wildcard": True}},
        {"type": "sse"},
        {"tool_name_prefix": False},
        {"headers": {}},
        {"url": "file:///tmp/rag"},
        {"url": "https://embedded:fixture-only@rag.example/mcp"},
        {"user_auth": {"users": {}}},
        {"headers_from_context": {"headers": {"Authorization": "secret"}}},
        {"oauth": {"token_url": "http://localhost/token", "client_id": "fixture"}},
        {"task_toolsets": [{"name": "report", "submit_tool": "submit", "status_tool": "status", "cancel_tool": "cancel"}]},
    ],
)
def test_invalid_controlled_connection_rejected_without_credential_output(change):
    config = endpoint(["user"])
    config.update(change)
    with pytest.raises(ValidationError) as exc:
        McpServerConfig.model_validate(config)
    assert "fixture-token" not in str(exc.value)


def test_empty_roles_deny_and_legacy_serialization_has_no_null_policy(policy):
    path, data = policy
    data["mcpServers"]["reader"]["rag_access"] = {}
    atomic_write_extensions_config(path, data)
    assert rag_access.project_rag_tools([tool("reader", "search_knowledge")], actor()) == []
    legacy = McpServerConfig(type="http", url="http://localhost/mcp")
    assert "rag_access" not in legacy.model_dump()
    assert McpServerConfig.model_validate(legacy.model_dump()).rag_access is None


@pytest.mark.parametrize("targeted", [False, True])
def test_old_config_client_preserves_acl_and_environment_secret_reference(policy, monkeypatch, targeted):
    path, data = policy
    data["mcpServers"]["reader"]["headers"]["Authorization"] = "$RAG_FIXTURE_TOKEN"
    atomic_write_extensions_config(path, data)
    monkeypatch.setenv("RAG_FIXTURE_TOKEN", "Bearer environment-fixture")
    incoming = router.McpServerConfigResponse.model_validate({"type": "http", "url": "http://localhost/user", "headers": {"Authorization": "***"}, "description": "changed"})
    if targeted:
        router._apply_mcp_server_config_update(router.McpServerConfigUpdateRequest(server_name="reader", server=incoming))
    else:
        other = router.McpServerConfigResponse.model_validate(data["mcpServers"]["restricted"])
        router._apply_mcp_config_update(router.McpConfigUpdateRequest(mcp_servers={"reader": incoming, "restricted": other}))
    raw = json.loads(path.read_text())["mcpServers"]["reader"]
    assert raw["rag_access"] == {"roles": ["user"]}
    assert raw["headers"]["Authorization"] == "$RAG_FIXTURE_TOKEN"
    assert ExtensionsConfig.from_file().mcp_servers["reader"].rag_access.roles == ["user"]


@pytest.mark.parametrize("policy_value", [None, {"roles": ["root"]}, {"roles": ["user"], "extra": True}])
def test_api_cannot_remove_or_malform_policy(policy_value):
    with pytest.raises(ValidationError):
        router.McpServerConfigResponse.model_validate({"rag_access": policy_value})


@pytest.mark.parametrize("source", ["session", "pat", "internal", "auth_disabled", None])
def test_gateway_restamps_auth_source_and_actor_from_both_client_carriers(source):
    user = SimpleNamespace(id="real-actor", system_role="user", oauth_provider=None, oauth_id=None)
    request = SimpleNamespace(state=SimpleNamespace(user=user, auth_source=source))
    forged = {"user_id": "forged-admin", "user_role": "admin", "authz_attributes": {"auth_source": "session", "forged": True}, "is_internal": False}
    config = {"context": dict(forged), "configurable": dict(forged)}
    inject_authenticated_user_context(config, request)
    assert config["context"]["authz_attributes"] == {"auth_source": source}
    assert config["context"]["user_role"] == "user"
    assert "authz_attributes" not in config["configurable"]
    if source != "internal":
        assert config["context"]["user_id"] == "real-actor"


def test_unavailable_policy_is_an_explicit_error_instead_of_empty_catalog(policy):
    path, _data = policy
    path.write_text("{")
    from langchain_core.tools import ToolException

    with pytest.raises(ToolException, match="RAG_AUTH_UNAVAILABLE"):
        rag_access.project_rag_tools([tool("reader", "search_knowledge")], actor())


def test_disabled_example_endpoints_load_without_secret_values(monkeypatch):
    from pathlib import Path

    monkeypatch.delenv("RAG_COMMON_AUTHORIZATION", raising=False)
    monkeypatch.delenv("RAG_RESTRICTED_AUTHORIZATION", raising=False)
    example = Path(__file__).resolve().parents[2] / "extensions_config.example.json"
    config = ExtensionsConfig.from_file(str(example))
    assert config.mcp_servers["rag_common"].enabled is False
    assert config.mcp_servers["rag_restricted"].enabled is False
    assert config.mcp_servers["rag_common"].rag_access.roles == ["user", "admin"]
