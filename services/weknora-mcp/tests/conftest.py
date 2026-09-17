from __future__ import annotations

import pytest

from weknora_mcp.config import Settings

KB_ID = "11111111-1111-4111-8111-111111111111"
OTHER_KB_ID = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def valid_env() -> dict[str, str]:
    return {
        "WEKNORA_BASE_URL": "https://weknora.example/api/v1",
        "WEKNORA_API_KEY": "test-api-secret",
        "WEKNORA_KB_IDS": KB_ID,
        "WEKNORA_TENANT_ID": "tenant-1",
        "MCP_SERVER_AUTH_TOKEN": "test-mcp-token-with-enough-entropy",
        "MCP_ALLOWED_HOSTS": "127.0.0.1:*,localhost:*",
        "MCP_ALLOWED_ORIGINS": "https://deerflow.example",
    }


@pytest.fixture
def settings(valid_env: dict[str, str]) -> Settings:
    return Settings.from_env(valid_env)
