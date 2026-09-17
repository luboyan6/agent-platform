from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_NGINX_CONFIG = REPO_ROOT / "docker/nginx/nginx.local.conf"


def test_local_nginx_uses_repo_owned_temp_directories() -> None:
    config = LOCAL_NGINX_CONFIG.read_text(encoding="utf-8")

    for temp_kind in ("client_body", "proxy", "fastcgi", "uwsgi", "scgi"):
        assert f"{temp_kind}_temp_path temp/{temp_kind}_temp;" in config


def test_local_launchers_create_every_configured_nginx_temp_directory() -> None:
    serve_script = (REPO_ROOT / "scripts/serve.sh").read_text(encoding="utf-8")
    nginx_script = (REPO_ROOT / "scripts/nginx.sh").read_text(encoding="utf-8")

    expected_paths = "temp/client_body_temp temp/proxy_temp temp/fastcgi_temp temp/uwsgi_temp temp/scgi_temp"
    assert f"mkdir -p {expected_paths}" in serve_script
    assert f"mkdir -p {expected_paths}" in nginx_script


def test_local_nginx_runtime_directory_is_gitignored() -> None:
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "/temp/" in gitignore.splitlines()


def test_local_launchers_run_nginx_workers_as_the_calling_user() -> None:
    serve_script = (REPO_ROOT / "scripts/serve.sh").read_text(encoding="utf-8")
    nginx_script = (REPO_ROOT / "scripts/nginx.sh").read_text(encoding="utf-8")

    assert 'NGINX_RUN_USER="$(id -un)"' in serve_script
    assert "-g 'user $NGINX_RUN_USER; daemon off;'" in serve_script
    assert 'NGINX_RUN_USER="$(id -un)"' in nginx_script
    assert '-g "user $NGINX_RUN_USER; daemon off;"' in nginx_script
