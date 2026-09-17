"""Regression coverage for service startup port waits."""

from __future__ import annotations

import subprocess
from pathlib import Path

from support.shell import require_script_bash

REPO_ROOT = Path(__file__).resolve().parents[2]
WAIT_FOR_PORT = REPO_ROOT / "scripts" / "wait-for-port.sh"
SERVE_SH = REPO_ROOT / "scripts" / "serve.sh"


def test_wait_for_port_fails_when_service_process_exits() -> None:
    bash = require_script_bash()
    process = subprocess.Popen([bash, "-c", "exit 7"])
    process.wait(timeout=5)

    result = subprocess.run(
        [bash, str(WAIT_FOR_PORT), "65431", "30", "Test service", str(process.pid)],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 2
    assert "Test service exited before opening port 65431" in result.stdout


def test_serve_tracks_started_process_during_port_wait() -> None:
    serve = SERVE_SH.read_text(encoding="utf-8")

    assert "local service_pid" in serve
    assert 'wait-for-port.sh "$port" "$timeout" "$name" "$service_pid"' in serve


def test_serve_port_preflight_checks_windows_host() -> None:
    serve = SERVE_SH.read_text(encoding="utf-8")
    function_start = serve.index("_is_port_listening() {")
    function_end = serve.index("\n}\n", function_start)
    function = serve[function_start:function_end]

    assert "powershell.exe" in function
    assert "Get-NetTCPConnection" in function


def test_serve_renders_nginx_for_configured_frontend_port() -> None:
    serve = SERVE_SH.read_text(encoding="utf-8")

    assert 'DEER_FLOW_FRONTEND_PORT="${DEER_FLOW_FRONTEND_PORT:-3000}"' in serve
    assert 'LOCAL_NGINX_CONFIG="$REPO_ROOT/temp/nginx.local.conf"' in serve
    assert "server 127\\\\.0\\\\.0\\\\.1:3000;" in serve
    assert "server 127.0.0.1:${DEER_FLOW_FRONTEND_PORT};" in serve
