"""Regression coverage for service startup port waits."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from support.shell import require_script_bash

REPO_ROOT = Path(__file__).resolve().parents[2]
WAIT_FOR_PORT = REPO_ROOT / "scripts" / "wait-for-port.sh"
SERVE_SH = REPO_ROOT / "scripts" / "serve.sh"
NGINX_SH = REPO_ROOT / "scripts" / "nginx.sh"


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


def test_nginx_standalone_renders_config_from_dotenv(tmp_path: Path) -> None:
    bash = require_script_bash()
    worktree = tmp_path / "repo"
    scripts_dir = worktree / "scripts"
    scripts_dir.mkdir(parents=True)
    shutil.copy(NGINX_SH, scripts_dir / "nginx.sh")
    shutil.copytree(REPO_ROOT / "docker" / "nginx", worktree / "docker" / "nginx")
    (worktree / ".env").write_text("PORT=8080\nDEER_FLOW_FRONTEND_PORT=3100\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_nginx = bin_dir / "nginx"
    fake_nginx.write_text('#!/usr/bin/env sh\nprintf "%s\\n" "$@" > "$CAPTURE_NGINX_ARGS"\n', encoding="utf-8")
    fake_nginx.chmod(0o755)

    captured_args = tmp_path / "nginx-args.txt"
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["CAPTURE_NGINX_ARGS"] = str(captured_args)

    result = subprocess.run(
        [bash, str(scripts_dir / "nginx.sh")],
        cwd=worktree,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    rendered = (worktree / "temp" / "nginx.local.conf").read_text(encoding="utf-8")
    assert "server 127.0.0.1:3100;" in rendered
    assert "listen 8080;" in rendered
    assert "listen [::]:8080;" in rendered
    assert "-c" in captured_args.read_text(encoding="utf-8")
