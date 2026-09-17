"""Regression coverage for safe local ``.env`` loading."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from support.shell import require_script_bash

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVE_SH = REPO_ROOT / "scripts" / "serve.sh"


def _extract_shell_function(name: str) -> str:
    text = SERVE_SH.read_text(encoding="utf-8")
    marker = f"{name}() {{"
    start = text.index(marker)
    depth = 0
    chunks: list[str] = []

    for line in text[start:].splitlines(keepends=True):
        chunks.append(line)
        depth += line.count("{") - line.count("}")
        if depth == 0:
            return "".join(chunks)

    raise AssertionError(f"Could not extract shell function {name}")


def _run_loader(env_file: Path, body: str) -> subprocess.CompletedProcess[str]:
    bash = require_script_bash()
    script = "\n".join(
        [
            "set -e",
            _extract_shell_function("_load_dotenv"),
            f"_load_dotenv {shlex.quote(str(env_file))}",
            body,
        ]
    )
    return subprocess.run(
        [bash, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )


def test_load_dotenv_exports_values_without_executing_shell(tmp_path: Path) -> None:
    marker = tmp_path / "must-not-exist"
    env_file = tmp_path / ".env"
    env_file.write_text(
        f'# comment\nPLAIN=value\nQUOTED="value with spaces"\nUNSAFE=$(touch {marker})\n',
        encoding="utf-8",
    )

    result = _run_loader(env_file, 'printf \'%s\\n\' "$PLAIN" "$QUOTED" "$UNSAFE"')

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "value",
        "value with spaces",
        f"$(touch {marker})",
    ]
    assert not marker.exists()


def test_load_dotenv_rejects_yaml_with_line_number(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("VALID=value\n  - id: misplaced-model\n", encoding="utf-8")

    result = _run_loader(env_file, "exit 0")

    assert result.returncode != 0
    assert f"{env_file}:2" in result.stderr
    assert "expected KEY=value" in result.stderr
