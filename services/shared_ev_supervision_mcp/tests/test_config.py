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


@pytest.mark.parametrize("credential", ["synthetic.jwt.value", "Bearer synthetic.jwt.value"])
def test_startup_loads_local_cookie_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, credential: str) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.local.toml").write_text(
        f'api_base_url = "http://backend.example/prod-api/"\nAdmin-Token-Ev = "{credential}"\n', encoding="utf-8"
    )

    settings = ServiceSettings.from_config(environ={})

    assert settings.api_base_url == "http://backend.example/prod-api"
    assert settings.api_authorization.get_secret_value() == "Bearer synthetic.jwt.value"
    assert "synthetic.jwt.value" not in repr(settings)


def test_environment_overrides_local_defaults(tmp_path: Path) -> None:
    config = tmp_path / "config.local.toml"
    config.write_text('api_base_url = "http://local.example/prod-api"\nAdmin-Token-Ev = "synthetic.local.token"\n', encoding="utf-8")
    auth_file = tmp_path / "authorization.header"
    _write_secret(auth_file, "synthetic.environment.token")

    settings = ServiceSettings.from_config(
        config,
        {
            "SHARED_EV_API_BASE_URL": "http://environment.example/prod-api",
            "SHARED_EV_API_AUTH_FILE": str(auth_file),
            "SHARED_EV_MCP_PORT": "18765",
        },
    )

    assert settings.api_base_url == "http://environment.example/prod-api"
    assert settings.api_authorization.get_secret_value() == "Bearer synthetic.environment.token"
    assert settings.port == 18765


@pytest.mark.parametrize(
    "content",
    [
        'Admin-Token-Ev = "synthetic.jwt.value',
        'Admin-Token-Ev = "short"',
        'Admin-Token-Ev = ""',
        'Admin-Token-Ev = ["synthetic.jwt.value"]',
        'unexpected = "synthetic.jwt.value"',
    ],
)
def test_invalid_local_configuration_errors_do_not_expose_credentials(tmp_path: Path, content: str) -> None:
    config = tmp_path / "config.local.toml"
    config.write_text(content, encoding="utf-8")

    with pytest.raises(ConfigError) as error:
        ServiceSettings.from_config(config, {"SHARED_EV_API_BASE_URL": "http://backend.example/prod-api"})

    assert "synthetic.jwt.value" not in str(error.value)
    assert "short" not in str(error.value)


def test_missing_optional_local_config_preserves_environment_startup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    auth_file = tmp_path / "authorization.header"
    _write_secret(auth_file, "synthetic.jwt.value")

    settings = ServiceSettings.from_config(
        environ={"SHARED_EV_API_BASE_URL": "http://backend.example/prod-api", "SHARED_EV_API_AUTH_FILE": str(auth_file)}
    )

    assert settings.api_authorization.get_secret_value() == "Bearer synthetic.jwt.value"


def test_explicit_missing_local_file_fails(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot be read"):
        ServiceSettings.from_config(tmp_path / "missing.toml", {})


def test_local_token_keeps_non_loopback_authentication_requirement(tmp_path: Path) -> None:
    config = tmp_path / "config.local.toml"
    config.write_text('Admin-Token-Ev = "synthetic.jwt.value"\n', encoding="utf-8")

    with pytest.raises(ConfigError, match="SHARED_EV_MCP_AUTH_TOKEN"):
        ServiceSettings.from_config(config, {"SHARED_EV_API_BASE_URL": "http://backend.example/prod-api", "SHARED_EV_MCP_HOST": "0.0.0.0"})
