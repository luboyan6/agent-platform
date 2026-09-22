"""Environment-backed service configuration with secret-file support."""

from __future__ import annotations

import ipaddress
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import SecretStr


class ConfigError(ValueError):
    """Raised for operator configuration errors without echoing secret values."""


@dataclass(frozen=True, slots=True)
class ServiceSettings:
    api_base_url: str
    api_authorization: SecretStr = field(repr=False)
    host: str = "127.0.0.1"
    port: int = 8765
    mcp_auth_token: SecretStr | None = field(default=None, repr=False)
    request_timeout_seconds: float = 20.0
    max_response_bytes: int = 2_000_000
    request_attempts: int = 3

    def __post_init__(self) -> None:
        normalized_url = _normalize_base_url(self.api_base_url)
        object.__setattr__(self, "api_base_url", normalized_url)
        if not 1 <= self.port <= 65535:
            raise ConfigError("SHARED_EV_MCP_PORT must be between 1 and 65535")
        if not 0.1 <= self.request_timeout_seconds <= 120:
            raise ConfigError("SHARED_EV_REQUEST_TIMEOUT_SECONDS must be between 0.1 and 120")
        if not 1024 <= self.max_response_bytes <= 20_000_000:
            raise ConfigError("SHARED_EV_MAX_RESPONSE_BYTES must be between 1024 and 20000000")
        if not 1 <= self.request_attempts <= 5:
            raise ConfigError("SHARED_EV_REQUEST_ATTEMPTS must be between 1 and 5")
        if self.mcp_auth_token is None and not _is_loopback_host(self.host):
            raise ConfigError("SHARED_EV_MCP_AUTH_TOKEN or SHARED_EV_MCP_AUTH_TOKEN_FILE is required for a non-loopback host")

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> ServiceSettings:
        values = os.environ if environ is None else environ
        base_url = _required(values, "SHARED_EV_API_BASE_URL")
        auth_path = Path(_required(values, "SHARED_EV_API_AUTH_FILE"))
        api_authorization = SecretStr(_parse_authorization(_read_secret_file(auth_path, "SHARED_EV_API_AUTH_FILE")))

        mcp_token_value = values.get("SHARED_EV_MCP_AUTH_TOKEN")
        mcp_token_path = values.get("SHARED_EV_MCP_AUTH_TOKEN_FILE")
        if mcp_token_value and mcp_token_path:
            raise ConfigError("set only one of SHARED_EV_MCP_AUTH_TOKEN and SHARED_EV_MCP_AUTH_TOKEN_FILE")
        if mcp_token_path:
            mcp_token_value = _parse_mcp_token(_read_secret_file(Path(mcp_token_path), "SHARED_EV_MCP_AUTH_TOKEN_FILE"))
        elif mcp_token_value:
            mcp_token_value = _parse_mcp_token(mcp_token_value)

        return cls(
            api_base_url=base_url,
            api_authorization=api_authorization,
            host=values.get("SHARED_EV_MCP_HOST", "127.0.0.1"),
            port=_parse_int(values, "SHARED_EV_MCP_PORT", 8765),
            mcp_auth_token=SecretStr(mcp_token_value) if mcp_token_value else None,
            request_timeout_seconds=_parse_float(values, "SHARED_EV_REQUEST_TIMEOUT_SECONDS", 20.0),
            max_response_bytes=_parse_int(values, "SHARED_EV_MAX_RESPONSE_BYTES", 2_000_000),
            request_attempts=_parse_int(values, "SHARED_EV_REQUEST_ATTEMPTS", 3),
        )


def _required(values: Mapping[str, str], name: str) -> str:
    value = values.get(name)
    if value is None or not value.strip():
        raise ConfigError(f"{name} is required")
    return value.strip()


def _parse_int(values: Mapping[str, str], name: str, default: int) -> int:
    raw = values.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be an integer") from None


def _parse_float(values: Mapping[str, str], name: str, default: float) -> float:
    raw = values.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number") from None


def _read_secret_file(path: Path, setting_name: str) -> str:
    if not path.is_absolute():
        raise ConfigError(f"{setting_name} must be an absolute path")
    try:
        file_stat = path.stat()
    except OSError:
        raise ConfigError(f"{setting_name} cannot be read") from None
    if not stat.S_ISREG(file_stat.st_mode):
        raise ConfigError(f"{setting_name} must point to a regular file")
    if stat.S_IMODE(file_stat.st_mode) & 0o077:
        raise ConfigError(f"{setting_name} permissions must not grant group or other access")
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise ConfigError(f"{setting_name} cannot be read as UTF-8") from None
    if len(raw.encode("utf-8")) > 16_384:
        raise ConfigError(f"{setting_name} exceeds the size limit")
    value = raw.strip()
    if not value or "\n" in value or "\r" in value:
        raise ConfigError(f"{setting_name} must contain exactly one non-empty line")
    return value


def _parse_authorization(raw: str) -> str:
    value = raw
    if value.lower().startswith("authorization:"):
        value = value.split(":", 1)[1].strip()
    if not value.lower().startswith("bearer "):
        value = f"Bearer {value}"
    match = re.fullmatch(r"Bearer ([^\s\x00-\x1f\x7f]{16,8192})", value, flags=re.IGNORECASE)
    if match is None:
        raise ConfigError("SHARED_EV_API_AUTH_FILE does not contain a valid Bearer authorization value")
    return f"Bearer {match.group(1)}"


def _parse_mcp_token(raw: str) -> str:
    value = raw.strip()
    if value.lower().startswith("x-mcp-auth-token:"):
        value = value.split(":", 1)[1].strip()
    if not re.fullmatch(r"[^\s\x00-\x1f\x7f]{16,4096}", value):
        raise ConfigError("MCP authentication token must contain 16-4096 non-whitespace characters")
    return value


def _normalize_base_url(raw: str) -> str:
    value = raw.strip().rstrip("/")
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError:
        raise ConfigError("SHARED_EV_API_BASE_URL is invalid") from None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ConfigError("SHARED_EV_API_BASE_URL must be an HTTP(S) URL without credentials, query, or fragment")
    return value


def _is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
