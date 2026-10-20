#!/usr/bin/env bash
#
# nginx-local-conf.sh — Print the nginx config path for local (non-Docker) runs.
#
# docker/nginx/nginx.local.conf listens on loopback only, matching the Docker
# stack's default BIND_HOST. When BIND_HOST names another address, render a
# copy under temp/ that listens there instead and print that path, so local
# runs honor the same opt-in as the Docker stack. PORT and
# DEER_FLOW_FRONTEND_PORT select the ingress and frontend ports. Gateway and
# frontend stay on loopback either way: nginx is the only entry point.
#
# Usage: NGINX_CONF="$(bash ./scripts/nginx-local-conf.sh)"

set -e

REPO_ROOT="$(builtin cd "$(dirname "${BASH_SOURCE[0]}")/.." >/dev/null 2>&1 && pwd -P)"
SOURCE_CONF="$REPO_ROOT/docker/nginx/nginx.local.conf"
RENDERED_CONF="$REPO_ROOT/temp/nginx.local.conf"

bind_host="${BIND_HOST:-127.0.0.1}"
nginx_port="${PORT:-2026}"
frontend_port="${DEER_FLOW_FRONTEND_PORT:-3000}"
validate_port() {
    local name="$1" value="$2"
    case "$value" in
        ''|*[!0-9]*) echo "$name must be a numeric TCP port." >&2; exit 1 ;;
    esac
    if [ "$value" -lt 1 ] || [ "$value" -gt 65535 ]; then
        echo "$name must be between 1 and 65535." >&2
        exit 1
    fi
}
validate_port PORT "$nginx_port"
validate_port DEER_FLOW_FRONTEND_PORT "$frontend_port"
if [ "$bind_host" = "127.0.0.1" ] && [ "$nginx_port" = "2026" ] && [ "$frontend_port" = "3000" ]; then
    # Drop a copy rendered for an earlier BIND_HOST so its listen lines do not linger.
    rm -f "$RENDERED_CONF"
    printf '%s\n' "$SOURCE_CONF"
    exit 0
fi

# Dotted-quad IPv4, every octet 0-255 without leading zeros. nginx resolves
# shorthand forms itself ("0" binds 0.0.0.0, "1.2.3" binds 1.2.0.3).
is_ipv4() {
    local IFS=. octet
    local -a octets
    case "$1" in ''|*[!0-9.]*|.*|*.|*..*) return 1 ;; esac
    read -r -a octets <<< "$1"
    [ "${#octets[@]}" -eq 4 ] || return 1
    for octet in "${octets[@]}"; do
        case "$octet" in 0|[1-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5]) ;; *) return 1 ;; esac
    done
}

# IPv6 literal: up to eight 1-4 digit hex groups, at most one "::", and an
# optional trailing dotted-quad that counts as two groups. No zone index:
# nginx rejects "%eth0" in listen.
is_ipv6() {
    local addr="$1" groups=0 group rest
    case "$addr" in *:*) ;; *) return 1 ;; esac
    case "$addr" in *[!0-9A-Fa-f:.]*|*:::*|*::*::*) return 1 ;; esac
    case "$addr" in :[!:]*|*[!:]:) return 1 ;; esac
    if [ "${addr%.*}" != "$addr" ]; then
        is_ipv4 "${addr##*:}" || return 1
        addr="${addr%:*}:0:0"
    fi
    rest="$addr:"
    while [ -n "$rest" ]; do
        group="${rest%%:*}"
        rest="${rest#*:}"
        case "$group" in
            '') ;;
            ?|??|???|????) case "$group" in *[!0-9A-Fa-f]*) return 1 ;; esac; groups=$((groups + 1)) ;;
            *) return 1 ;;
        esac
    done
    case "$addr" in
        *::*) [ "$groups" -le 7 ] ;;
        *) [ "$groups" -eq 8 ] ;;
    esac
}

# RFC 1123 hostname: dot-separated labels of letters, digits and inner hyphens,
# 1-63 characters each, 253 in all. All-numeric values are IPv4 or nothing.
# The character check covers the whole value: read below stops at a newline.
is_hostname() {
    local IFS=. label
    local -a labels
    [ "${#1}" -le 253 ] || return 1
    case "$1" in ''|*[!A-Za-z0-9.-]*|.*|*.|*..*) return 1 ;; esac
    case "$1" in *[!0-9.]*) ;; *) return 1 ;; esac
    read -r -a labels <<< "$1"
    for label in "${labels[@]}"; do
        [ "${#label}" -le 63 ] || return 1
        case "$label" in -*|*-) return 1 ;; esac
    done
}

# The value is written into an nginx listen directive, so it must be exactly
# one address or hostname; brackets are accepted around an IPv6 address only.
invalid_bind_host() {
    echo "BIND_HOST must be an IP address or hostname: ${BIND_HOST}" >&2
    exit 1
}
case "$bind_host" in
    \[*\]) bind_host="${bind_host#\[}"; bind_host="${bind_host%\]}"; is_ipv6 "$bind_host" || invalid_bind_host ;;
    *[][]*) invalid_bind_host ;;
    *:*) is_ipv6 "$bind_host" || invalid_bind_host ;;
    *) is_ipv4 "$bind_host" || is_hostname "$bind_host" || invalid_bind_host ;;
esac

case "$bind_host" in
    127.0.0.1) listen_lines="listen 127.0.0.1:$nginx_port;\nlisten [::1]:$nginx_port;" ;;
    0.0.0.0) listen_lines="listen $nginx_port;\nlisten [::]:$nginx_port;" ;;
    *:*) listen_lines="listen [$bind_host]:$nginx_port;" ;;
    *) listen_lines="listen $bind_host:$nginx_port;" ;;
esac

# awk -v expands the \n separator; BSD awk rejects a literal newline there.
mkdir -p "$REPO_ROOT/temp"
awk -v listen_lines="$listen_lines" -v frontend_port="$frontend_port" '
    /^[[:space:]]*listen 127\.0\.0\.1:2026;[[:space:]]*$/ {
        match($0, /^[[:space:]]*/)
        indent = substr($0, 1, RLENGTH)
        n = split(listen_lines, lines, "\n")
        for (i = 1; i <= n; i++) print indent lines[i]
        replaced++
        next
    }
    /^[[:space:]]*listen \[::1\]:2026;[[:space:]]*$/ { next }
    { sub(/server 127\.0\.0\.1:3000;/, "server 127.0.0.1:" frontend_port ";") }
    { print }
    END { if (replaced != 1) exit 1 }
' "$SOURCE_CONF" > "$RENDERED_CONF.tmp" || {
    rm -f "$RENDERED_CONF.tmp"
    echo "Could not find the loopback listen directive in $SOURCE_CONF" >&2
    exit 1
}
mv "$RENDERED_CONF.tmp" "$RENDERED_CONF"
printf '%s\n' "$RENDERED_CONF"
