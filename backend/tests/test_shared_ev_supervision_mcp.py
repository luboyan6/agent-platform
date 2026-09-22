"""DeerFlow-side configuration contract for the shared EV supervision MCP."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.mcp.client import build_server_params


def _example_path() -> Path:
    return Path(__file__).resolve().parents[2] / "extensions_config.example.json"


def test_example_registers_shared_ev_as_opt_in_http_only_service() -> None:
    example = json.loads(_example_path().read_text(encoding="utf-8"))
    raw = example["mcpServers"]["shared_ev_supervision"]

    assert raw["enabled"] is False
    assert raw["type"] == "http"
    assert raw["url"] == "$SHARED_EV_MCP_URL"
    assert raw["headers"] == {"X-MCP-Auth-Token": "$SHARED_EV_MCP_TOKEN"}
    assert raw["tool_name_prefix"] is True
    assert raw["routing"]["mode"] == "prefer"
    assert {"头盔监管", "案件处理", "自动巡查", "订单汇总"} <= set(raw["routing"]["keywords"])
    assert {"command", "args", "cwd", "env"}.isdisjoint(raw)
    assert "SHARED_EV_API_AUTH" not in json.dumps(raw)


def test_shared_ev_http_connection_resolves_only_the_mcp_boundary_credentials(
    tmp_path: Path,
    monkeypatch,
) -> None:
    mcp_token = "synthetic-shared-ev-mcp-token"
    monkeypatch.setenv("SHARED_EV_MCP_URL", "https://shared-ev-mcp.internal.example/mcp")
    monkeypatch.setenv("SHARED_EV_MCP_TOKEN", mcp_token)
    example = json.loads(_example_path().read_text(encoding="utf-8"))
    entry = deepcopy(example["mcpServers"]["shared_ev_supervision"])
    entry["enabled"] = True
    config_path = tmp_path / "extensions_config.json"
    config_path.write_text(json.dumps({"mcpServers": {"shared_ev_supervision": entry}}), encoding="utf-8")

    server = ExtensionsConfig.from_file(str(config_path)).mcp_servers["shared_ev_supervision"]

    assert build_server_params("shared_ev_supervision", server) == {
        "transport": "http",
        "url": "https://shared-ev-mcp.internal.example/mcp",
        "headers": {"X-MCP-Auth-Token": mcp_token},
    }
