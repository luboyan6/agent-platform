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

NGINX_CONF="$(bash "$REPO_ROOT/scripts/nginx-local-conf.sh")"
NGINX_RUN_USER="$(id -un)"
exec nginx -g "user $NGINX_RUN_USER; daemon off;" -c "$NGINX_CONF" -p "$REPO_ROOT"
