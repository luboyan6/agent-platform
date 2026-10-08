"""Role projection and per-call admission for fixed read-only RAG endpoints.

The host owns account lookup; the harness owns endpoint policy and transport
admission. Discovery caches never grant access, and connection digests stay
private rather than entering tool metadata or model-visible payloads.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
from collections.abc import Awaitable, Callable, Mapping
from copy import deepcopy
from typing import Any

from langchain_core.tools import BaseTool, ToolException

from deerflow.config.extensions_config import ExtensionsConfig, McpServerConfig
from deerflow.config.file_signature import get_config_signature, read_config_with_signature
from deerflow.mcp.headers import illegal_header_value_reason

logger = logging.getLogger(__name__)
RAG_RETRIEVAL_TOOLS = frozenset({"list_knowledge_bases", "search_knowledge", "ask"})
RoleResolver = Callable[[str], Awaitable[str | None]]
_role_resolver: RoleResolver | None = None
_protected_aliases: frozenset[str] = frozenset()
_registry_lock = threading.Lock()


def set_rag_role_resolver(resolver: RoleResolver | None) -> RoleResolver | None:
    global _role_resolver
    previous, _role_resolver = _role_resolver, resolver
    return previous


def reset_rag_protected_aliases(aliases: frozenset[str] = frozenset()) -> frozenset[str]:
    """Host lifecycle/test isolation only; hot reload must never forget protection."""
    global _protected_aliases
    with _registry_lock:
        previous, _protected_aliases = _protected_aliases, aliases
    return previous


def register_rag_endpoints(config: ExtensionsConfig) -> None:
    global _protected_aliases
    with _registry_lock:
        _protected_aliases |= frozenset(name for name, server in config.mcp_servers.items() if server.rag_access is not None)


def _error(code: str) -> ToolException:
    return ToolException(json.dumps({"code": code, "message": "RAG request denied" if code != "RAG_AUTH_UNAVAILABLE" else "RAG authorization unavailable"}))


def read_rag_policy() -> ExtensionsConfig:
    """Read a stable live revision with no last-known-good authorization fallback."""
    try:
        path = ExtensionsConfig.resolve_config_path()
        if path is None:
            if _protected_aliases:
                raise FileNotFoundError("protected endpoint policy missing")
            return ExtensionsConfig()
        content, signature = read_config_with_signature(path)
        config = ExtensionsConfig.model_validate(ExtensionsConfig.resolve_env_variables(json.loads(content.decode("utf-8-sig"))))
        if get_config_signature(path) != signature:
            raise ValueError("unstable policy revision")
        register_rag_endpoints(config)
        return config
    except Exception as exc:
        # Config validation exceptions can contain resolved secrets; never copy
        # their text or traceback into a tool error, trace or audit record.
        logger.warning("RAG policy unavailable error_type=%s", type(exc).__name__)
        raise _error("RAG_AUTH_UNAVAILABLE") from None


def _connection_digest(server: McpServerConfig) -> str:
    connection = {"type": server.type, "url": server.url, "headers": server.headers}
    return hashlib.sha256(json.dumps(connection, sort_keys=True).encode()).hexdigest()


def validate_rag_headers(server: McpServerConfig) -> None:
    """Validate resolved static headers before discovery can expose transport errors."""
    if server.rag_access is None:
        return
    for value in server.headers.values():
        if illegal_header_value_reason(value):
            raise _error("RAG_AUTH_UNAVAILABLE")
    token = next((value for name, value in server.headers.items() if name.lower() == "authorization"), "")
    if not token.startswith("Bearer ") or not token[7:].strip() or token[7:] != token[7:].strip():
        raise _error("RAG_AUTH_UNAVAILABLE")


def _web_actor(context: Mapping[str, Any]) -> str | None:
    attributes = context.get("authz_attributes")
    actor = context.get("user_id")
    if isinstance(attributes, Mapping) and attributes.get("auth_source") == "session" and context.get("is_internal") is not True and isinstance(actor, str) and actor.strip():
        return actor
    return None


def project_rag_tools(tools: list[BaseTool], context: Mapping[str, Any]) -> list[BaseTool]:
    """Filter a run-local catalog before general authorization/deferred assembly."""
    from deerflow.tools.mcp_metadata import get_mcp_source

    sources = [get_mcp_source(tool) for tool in tools]
    if not any(sources):
        return tools
    config = read_rag_policy()
    filtered = []
    for tool, source in zip(tools, sources, strict=True):
        if source is None or source["server_name"] not in _protected_aliases:
            filtered.append(tool)
            continue
        server = config.mcp_servers.get(source["server_name"])
        if server and server.enabled and server.rag_access is not None and _web_actor(context) and context.get("user_role") in server.rag_access.roles and source.get("original_tool_name") in RAG_RETRIEVAL_TOOLS:
            filtered.append(tool)
    return filtered


def stateless_rag_tool(tool: BaseTool, original_name: str) -> BaseTool:
    """Adapt the shared invariant contract; user filtering never mutates this tool."""
    if original_name == "ask":
        schema = deepcopy(tool.args_schema)
        if not isinstance(schema, dict):
            raise _error("RAG_AUTH_UNAVAILABLE")
        schema.get("properties", {}).pop("session_id", None)
        schema["required"] = [key for key in schema.get("required", []) if key != "session_id"]
        tool = tool.model_copy(update={"args_schema": schema, "description": "Ask a question within this endpoint's authorized knowledge bases. Each call creates a fresh RAG session. Include relevant conversation context in the question."})
    tool.handle_tool_error = True
    return tool


def _request_context(request: Any) -> Mapping[str, Any]:
    runtime = getattr(request, "runtime", None)
    # Direct/durable callers supply runtime=None. Ambient parent context must
    # not promote those calls into the web-only pilot boundary.
    context = getattr(runtime, "context", None)
    return context if isinstance(context, Mapping) else {}


def build_rag_access_interceptor(config: ExtensionsConfig) -> Any | None:
    if not isinstance(config, ExtensionsConfig):
        return None
    register_rag_endpoints(config)
    bindings = {name: _connection_digest(server) for name, server in config.mcp_servers.items()}
    protected_at_build = frozenset(name for name, server in config.mcp_servers.items() if server.rag_access is not None)
    for server in config.get_enabled_mcp_servers().values():
        validate_rag_headers(server)

    async def guard(request: Any, handler: Any) -> Any:
        alias = request.server_name
        context = _request_context(request)
        actor, role = _web_actor(context), None
        run_id = context.get("run_id")
        tool_call_id = getattr(getattr(request, "runtime", None), "tool_call_id", None)
        protected = alias in protected_at_build or alias in _protected_aliases
        try:
            current = await asyncio.to_thread(read_rag_policy)
            server = current.mcp_servers.get(alias)
            if alias not in _protected_aliases and alias not in protected_at_build:
                return await handler(request)
            protected = True
            if server is None or not server.enabled or server.rag_access is None or actor is None:
                raise _error("RAG_ACCESS_DENIED")
            validate_rag_headers(server)
            if bindings.get(alias) != _connection_digest(server):
                raise _error("RAG_CONNECTION_CHANGED")
            # Custom interceptors cannot substitute an endpoint credential or
            # add a second Authorization spelling at the final transport merge.
            if request.headers is not None and any(name not in server.headers or value != server.headers[name] for name, value in request.headers.items()):
                raise _error("RAG_CONNECTION_CHANGED")
            resolver = _role_resolver
            if resolver is None:
                raise _error("RAG_AUTH_UNAVAILABLE")
            try:
                role = await resolver(actor)
            except Exception as exc:
                logger.warning("RAG account lookup unavailable actor=%s error_type=%s", actor, type(exc).__name__)
                raise _error("RAG_AUTH_UNAVAILABLE") from None
            if role not in {"admin", "user"} or role not in server.rag_access.roles:
                raise _error("RAG_ACCESS_DENIED")
            if request.name not in RAG_RETRIEVAL_TOOLS:
                raise _error("RAG_TOOL_DENIED")
            args = dict(request.args)
            if request.name == "ask":
                if args.get("session_id"):
                    raise _error("RAG_SESSION_REUSE_DENIED")
                args["session_id"] = ""
            logger.info("RAG admission actor=%s role=%s server=%s tool=%s run=%s call=%s decision=allow", actor, role, alias, request.name, run_id, tool_call_id)
        except ToolException as exc:
            if protected:
                logger.info("RAG admission actor=%s role=%s server=%s tool=%s run=%s call=%s decision=%s", actor, role, alias, request.name, run_id, tool_call_id, str(exc))
            raise
        return await handler(request.override(args=args))

    return guard
