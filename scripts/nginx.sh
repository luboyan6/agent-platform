#!/usr/bin/env bash
#
# nginx.sh — Start nginx alone in the foreground with the local dev config.
#
# Mirrors how scripts/serve.sh launches nginx (same prefix, config, and
# pre-created directories) — keep the two in sync.
#
# Usage: make nginx  (or ./scripts/nginx.sh from anywhere)

set -e

REPO_ROOT="$(builtin cd "$(dirname "${BASH_SOURCE[0]}")/.." >/dev/null 2>&1 && pwd -P)"
cd "$REPO_ROOT"

_load_dotenv() {
    local env_file=$1
    local line line_number=0 key value

    while IFS= read -r line || [ -n "$line" ]; do
        line_number=$((line_number + 1))
        line="${line%$'\r'}"

        case "$line" in
            "" | \#*) continue ;;
        esac

        if [[ ! "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; then
            echo "Invalid dotenv entry at $env_file:$line_number; expected KEY=value" >&2
            return 1
        fi

        key="${line%%=*}"
        value="${line#*=}"
        case "$value" in
            \"*\") value="${value:1:${#value}-2}" ;;
            \'*\') value="${value:1:${#value}-2}" ;;
        esac

        # Keep dotenv content as data: command substitutions and shell
        # expansions are never evaluated.
        export "$key=$value"
    done < "$env_file"
}

if [ -f "$REPO_ROOT/.env" ]; then
    _load_dotenv "$REPO_ROOT/.env"
fi

mkdir -p logs
mkdir -p temp/client_body_temp temp/proxy_temp temp/fastcgi_temp temp/uwsgi_temp temp/scgi_temp

DEER_FLOW_NGINX_PORT="${PORT:-2026}"
case "$DEER_FLOW_NGINX_PORT" in
    "" | *[!0-9]*)
        echo "PORT must be a numeric TCP port." >&2
        exit 1
        ;;
esac
if [ "$DEER_FLOW_NGINX_PORT" -lt 1 ] || [ "$DEER_FLOW_NGINX_PORT" -gt 65535 ]; then
    echo "PORT must be between 1 and 65535." >&2
    exit 1
fi

DEER_FLOW_FRONTEND_PORT="${DEER_FLOW_FRONTEND_PORT:-3000}"
case "$DEER_FLOW_FRONTEND_PORT" in
    "" | *[!0-9]*)
        echo "DEER_FLOW_FRONTEND_PORT must be a numeric TCP port." >&2
        exit 1
        ;;
esac
if [ "$DEER_FLOW_FRONTEND_PORT" -lt 1 ] || [ "$DEER_FLOW_FRONTEND_PORT" -gt 65535 ]; then
    echo "DEER_FLOW_FRONTEND_PORT must be between 1 and 65535." >&2
    exit 1
fi

LOCAL_NGINX_CONFIG="$REPO_ROOT/docker/nginx/nginx.local.conf"
if [ "$DEER_FLOW_FRONTEND_PORT" != "3000" ] || [ "$DEER_FLOW_NGINX_PORT" != "2026" ]; then
    LOCAL_NGINX_CONFIG="$REPO_ROOT/temp/nginx.local.conf"
    sed \
        -e "s/server 127\\.0\\.0\\.1:3000;/server 127.0.0.1:${DEER_FLOW_FRONTEND_PORT};/" \
        -e "s/listen 2026;/listen ${DEER_FLOW_NGINX_PORT};/" \
        -e "s/listen \\[::\\]:2026;/listen [::]:${DEER_FLOW_NGINX_PORT};/" \
        "$REPO_ROOT/docker/nginx/nginx.local.conf" > "$LOCAL_NGINX_CONFIG"
fi

NGINX_RUN_USER="$(id -un)"
exec nginx -g "user $NGINX_RUN_USER; daemon off;" -c "$LOCAL_NGINX_CONFIG" -p "$REPO_ROOT"
