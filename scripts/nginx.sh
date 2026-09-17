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

mkdir -p logs
mkdir -p temp/client_body_temp temp/proxy_temp temp/fastcgi_temp temp/uwsgi_temp temp/scgi_temp

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
if [ "$DEER_FLOW_FRONTEND_PORT" != "3000" ]; then
    LOCAL_NGINX_CONFIG="$REPO_ROOT/temp/nginx.local.conf"
    sed "s/server 127\\.0\\.0\\.1:3000;/server 127.0.0.1:${DEER_FLOW_FRONTEND_PORT};/" \
        "$REPO_ROOT/docker/nginx/nginx.local.conf" > "$LOCAL_NGINX_CONFIG"
fi

NGINX_RUN_USER="$(id -un)"
exec nginx -g "user $NGINX_RUN_USER; daemon off;" -c "$LOCAL_NGINX_CONFIG" -p "$REPO_ROOT"
