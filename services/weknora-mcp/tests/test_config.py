from __future__ import annotations

import pytest

from weknora_mcp.config import ConfigurationError, Settings

from .conftest import KB_ID, OTHER_KB_ID


def test_settings_normalize_and_keep_credentials_separate(valid_env: dict[str, str]) -> None:
    valid_env.update(
        {
            "WEKNORA_BASE_URL": "https://weknora.example/api/v1/",
            "WEKNORA_KB_IDS": f"{KB_ID},{OTHER_KB_ID},{KB_ID}",
            "MCP_HOST": "127.0.0.1",
            "MCP_PORT": "8123",
        }
    )

    settings = Settings.from_env(valid_env)

    assert settings.weknora_base_url == "https://weknora.example/api/v1"
    assert settings.knowledge_base_ids == (KB_ID, OTHER_KB_ID)
    assert settings.mcp_host == "127.0.0.1"
    assert settings.mcp_port == 8123
    assert settings.allowed_hosts == ("127.0.0.1:*", "localhost:*")
    assert settings.allowed_origins == ("https://deerflow.example",)
    assert settings.mcp_auth_token != settings.weknora_api_key
    assert settings.weknora_api_key not in repr(settings)
    assert settings.mcp_auth_token not in repr(settings)


@pytest.mark.parametrize(
    ("updates", "removals"),
    [
        ({}, {"WEKNORA_BASE_URL"}),
        ({"WEKNORA_BASE_URL": "ftp://weknora.example/api/v1"}, set()),
        ({"WEKNORA_BASE_URL": "https://user:password@weknora.example/api/v1"}, set()),
        ({"WEKNORA_BASE_URL": "https://weknora.example/not-api"}, set()),
        ({"WEKNORA_API_KEY": " secret"}, set()),
        ({"WEKNORA_KB_IDS": "../all"}, set()),
        (
            {"WEKNORA_KB_IDS": ",".join(str(index).zfill(8) + "-1111-4111-8111-111111111111" for index in range(9))},
            set(),
        ),
        ({"MCP_SERVER_AUTH_TOKEN": "too-short"}, set()),
        ({"MCP_SERVER_AUTH_TOKEN": "test-api-secret"}, set()),
        ({"MCP_SERVER_AUTH_TOKEN": "valid-token-with-newline\n"}, set()),
        ({"MCP_PORT": "0"}, set()),
        ({"MCP_ALLOWED_HOSTS": "https://mcp.example"}, set()),
        ({"MCP_ALLOWED_ORIGINS": "mcp.example"}, set()),
    ],
)
def test_invalid_configuration_fails_closed(
    valid_env: dict[str, str],
    updates: dict[str, str],
    removals: set[str],
) -> None:
    valid_env.update(updates)
    for name in removals:
        valid_env.pop(name, None)

    with pytest.raises(ConfigurationError):
        Settings.from_env(valid_env)


def test_configuration_error_never_echoes_secrets(valid_env: dict[str, str]) -> None:
    secret = valid_env["WEKNORA_API_KEY"]
    valid_env["WEKNORA_BASE_URL"] = f"https://{secret}@weknora.example/api/v1"

    with pytest.raises(ConfigurationError) as exc_info:
        Settings.from_env(valid_env)

    assert secret not in str(exc_info.value)
