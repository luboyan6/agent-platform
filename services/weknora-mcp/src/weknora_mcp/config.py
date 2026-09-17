"""Validated environment configuration for the standalone MCP service."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

_DEFAULT_ALLOWED_HOSTS = "127.0.0.1:*,localhost:*,[::1]:*"
_MAX_KNOWLEDGE_BASES = 8


class ConfigurationError(ValueError):
    """Raised when service configuration is incomplete or unsafe."""


@dataclass(frozen=True)
class Settings:
    """Fully validated service settings.

    Upstream credentials and scope live only in this process. DeerFlow receives
    the separate MCP service token and endpoint.
    """

    weknora_base_url: str
    weknora_api_key: str = field(repr=False)
    knowledge_base_ids: tuple[str, ...]
    mcp_auth_token: str = field(repr=False)
    tenant_id: str | None = None
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8000
    allowed_hosts: tuple[str, ...] = ("127.0.0.1:*", "localhost:*", "[::1]:*")
    allowed_origins: tuple[str, ...] = ()
    request_timeout_seconds: float = 30.0
    response_limit_bytes: int = 2 * 1024 * 1024
    max_concurrency: int = 4
    max_content_characters: int = 4000

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        source = os.environ if environ is None else environ
        base_url = _parse_base_url(_required(source, "WEKNORA_BASE_URL", secret=False))
        api_key = _required_header_value(source, "WEKNORA_API_KEY")
        knowledge_base_ids = _parse_knowledge_base_ids(_required(source, "WEKNORA_KB_IDS", secret=False))
        mcp_auth_token = _required_header_value(source, "MCP_SERVER_AUTH_TOKEN")
        if len(mcp_auth_token) < 16:
            raise ConfigurationError("MCP_SERVER_AUTH_TOKEN must contain at least 16 characters")
        if mcp_auth_token == api_key:
            raise ConfigurationError("MCP_SERVER_AUTH_TOKEN must be distinct from WEKNORA_API_KEY")

        tenant_id = _optional_header_value(source, "WEKNORA_TENANT_ID")
        mcp_host = _parse_bind_host(source.get("MCP_HOST", "0.0.0.0"))
        mcp_port = _parse_port(source.get("MCP_PORT", "8000"))
        allowed_hosts = _parse_allowed_hosts(source.get("MCP_ALLOWED_HOSTS", _DEFAULT_ALLOWED_HOSTS))
        allowed_origins = _parse_allowed_origins(source.get("MCP_ALLOWED_ORIGINS", ""))

        return cls(
            weknora_base_url=base_url,
            weknora_api_key=api_key,
            knowledge_base_ids=knowledge_base_ids,
            mcp_auth_token=mcp_auth_token,
            tenant_id=tenant_id,
            mcp_host=mcp_host,
            mcp_port=mcp_port,
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        )


def _required(source: Mapping[str, str], name: str, *, secret: bool) -> str:
    value = source.get(name)
    if value is None or not value:
        raise ConfigurationError(f"{name} is required")
    if value != value.strip() or _has_control_characters(value):
        suffix = "secret" if secret else "value"
        raise ConfigurationError(f"{name} contains an invalid {suffix}")
    return value


def _required_header_value(source: Mapping[str, str], name: str) -> str:
    value = _required(source, name, secret=True)
    if not value.isascii():
        raise ConfigurationError(f"{name} contains an invalid secret")
    return value


def _optional_header_value(source: Mapping[str, str], name: str) -> str | None:
    value = source.get(name)
    if value is None or value == "":
        return None
    return _required_header_value(source, name)


def _has_control_characters(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def _parse_base_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as exc:
        raise ConfigurationError("WEKNORA_BASE_URL is not a valid URL") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ConfigurationError("WEKNORA_BASE_URL must use http or https")
    if parsed.username is not None or parsed.password is not None:
        raise ConfigurationError("WEKNORA_BASE_URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ConfigurationError("WEKNORA_BASE_URL must not contain a query or fragment")
    if parsed.hostname in {"0.0.0.0", "::"}:
        raise ConfigurationError("WEKNORA_BASE_URL must identify a reachable host")
    path = parsed.path.rstrip("/")
    if not path.endswith("/api/v1"):
        raise ConfigurationError("WEKNORA_BASE_URL must end with /api/v1")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _parse_knowledge_base_ids(value: str) -> tuple[str, ...]:
    parsed: list[str] = []
    for raw_id in value.split(","):
        candidate = raw_id.strip()
        if not candidate:
            raise ConfigurationError("WEKNORA_KB_IDS must contain only knowledge-base UUIDs")
        try:
            normalized = str(UUID(candidate))
        except ValueError as exc:
            raise ConfigurationError("WEKNORA_KB_IDS must contain only knowledge-base UUIDs") from exc
        if normalized not in parsed:
            parsed.append(normalized)
    if not parsed:
        raise ConfigurationError("WEKNORA_KB_IDS must contain at least one knowledge-base UUID")
    if len(parsed) > _MAX_KNOWLEDGE_BASES:
        raise ConfigurationError(f"WEKNORA_KB_IDS may contain at most {_MAX_KNOWLEDGE_BASES} knowledge bases")
    return tuple(parsed)


def _parse_bind_host(value: str) -> str:
    if (
        not value
        or value != value.strip()
        or _has_control_characters(value)
        or any(character.isspace() for character in value)
    ):
        raise ConfigurationError("MCP_HOST is invalid")
    return value


def _parse_port(value: str) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError("MCP_PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ConfigurationError("MCP_PORT must be between 1 and 65535")
    return port


def _parse_allowed_hosts(value: str) -> tuple[str, ...]:
    hosts = _split_csv(value)
    if not hosts:
        raise ConfigurationError("MCP_ALLOWED_HOSTS must contain at least one host")
    for host in hosts:
        if "://" in host or "/" in host or any(character.isspace() for character in host):
            raise ConfigurationError("MCP_ALLOWED_HOSTS contains an invalid host")
    return hosts


def _parse_allowed_origins(value: str) -> tuple[str, ...]:
    origins = _split_csv(value)
    for origin in origins:
        parsed = urlsplit(origin.removesuffix(":*"))
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ConfigurationError("MCP_ALLOWED_ORIGINS contains an invalid origin")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ConfigurationError("MCP_ALLOWED_ORIGINS contains an invalid origin")
    return origins


def _split_csv(value: str) -> tuple[str, ...]:
    result: list[str] = []
    for item in value.split(","):
        candidate = item.strip()
        if candidate and candidate not in result:
            result.append(candidate)
    return tuple(result)
