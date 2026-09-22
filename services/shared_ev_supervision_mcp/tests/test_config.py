from __future__ import annotations

from pathlib import Path

import pytest

from shared_ev_supervision_mcp.config import ConfigError, ServiceSettings


def _write_secret(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)


def test_settings_read_existing_authorization_header_without_exposing_it(tmp_path: Path) -> None:
    auth_file = tmp_path / "authorization.header"
    _write_secret(auth_file, "Authorization: Bearer synthetic.jwt.value  \n")

    settings = ServiceSettings.from_environ(
        {
            "SHARED_EV_API_BASE_URL": "http://backend.example/prod-api/",
            "SHARED_EV_API_AUTH_FILE": str(auth_file),
        }
    )

    assert settings.api_base_url == "http://backend.example/prod-api"
    assert settings.api_authorization.get_secret_value() == "Bearer synthetic.jwt.value"
    assert settings.host == "127.0.0.1"
    assert settings.port == 8765
    assert settings.mcp_auth_token is None
    assert "synthetic.jwt.value" not in repr(settings)


def test_settings_reject_world_readable_secret_file(tmp_path: Path) -> None:
    auth_file = tmp_path / "authorization.header"
    _write_secret(auth_file, "Bearer synthetic.jwt.value")
    auth_file.chmod(0o644)

    with pytest.raises(ConfigError, match="permissions") as error:
        ServiceSettings.from_environ(
            {
                "SHARED_EV_API_BASE_URL": "http://backend.example/prod-api",
                "SHARED_EV_API_AUTH_FILE": str(auth_file),
            }
        )

    assert "synthetic.jwt.value" not in str(error.value)


def test_non_loopback_http_binding_requires_mcp_authentication(tmp_path: Path) -> None:
    auth_file = tmp_path / "authorization.header"
    _write_secret(auth_file, "Bearer synthetic.jwt.value")

    with pytest.raises(ConfigError, match="SHARED_EV_MCP_AUTH_TOKEN"):
        ServiceSettings.from_environ(
            {
                "SHARED_EV_API_BASE_URL": "http://backend.example/prod-api",
                "SHARED_EV_API_AUTH_FILE": str(auth_file),
                "SHARED_EV_MCP_HOST": "0.0.0.0",
            }
        )


def test_non_loopback_binding_accepts_a_separate_mcp_token_file(tmp_path: Path) -> None:
    auth_file = tmp_path / "authorization.header"
    mcp_token_file = tmp_path / "mcp.token"
    _write_secret(auth_file, "Bearer synthetic.jwt.value")
    _write_secret(mcp_token_file, "synthetic-mcp-token-value")

    settings = ServiceSettings.from_environ(
        {
            "SHARED_EV_API_BASE_URL": "http://backend.example/prod-api",
            "SHARED_EV_API_AUTH_FILE": str(auth_file),
            "SHARED_EV_MCP_HOST": "0.0.0.0",
            "SHARED_EV_MCP_AUTH_TOKEN_FILE": str(mcp_token_file),
        }
    )

    assert settings.mcp_auth_token is not None
    assert settings.mcp_auth_token.get_secret_value() == "synthetic-mcp-token-value"
