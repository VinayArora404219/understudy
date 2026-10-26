#!/usr/bin/env bash
# Render the edge vhost into $EDGE_DIR/edge/ and prove it is safe before the edge sees it.
#
#   EDGE_DIR=/srv/recast-edge RECAST_DOMAIN=recast.example.com deploy/vps/render.sh
#   ALLOW_FROM=cloudflare (default) | any
#
# Writes $EDGE_DIR/edge/{recast.conf,proxy.inc,tls/}. Refuses a vhost that could catch traffic
# meant for another site on the same edge: a default_server, or any server_name except
# RECAST_DOMAIN. Then runs `nginx -t` on it in a throwaway container.
set -euo pipefail
: "${EDGE_DIR:?set EDGE_DIR}"
: "${RECAST_DOMAIN:?set RECAST_DOMAIN}"
ALLOW_FROM="${ALLOW_FROM:-cloudflare}"
here="$(cd "$(dirname "$0")" && pwd)"
[[ "$RECAST_DOMAIN" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}$ ]] || { echo "bad RECAST_DOMAIN: $RECAST_DOMAIN" >&2; exit 1; }
fail() { echo "render.sh: refusing: $*" >&2; exit 1; }

stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
mkdir -p "$stage/tls"

case "$ALLOW_FROM" in
  cloudflare)
    ranges="$(curl -fsS https://www.cloudflare.com/ips-v4; echo; curl -fsS https://www.cloudflare.com/ips-v6)" || fail "could not fetch Cloudflare ranges"
    RECAST_ALLOW="$(echo "$ranges" | grep -E '^[0-9a-f:.]+/[0-9]+$' | sed 's/^/allow /; s/$/;/')"
    [ "$(echo "$RECAST_ALLOW" | wc -l)" -ge 10 ] || fail "Cloudflare range list looks wrong"
    RECAST_ALLOW="$RECAST_ALLOW"$'\n''deny all;' ;;
  any) RECAST_ALLOW="# ALLOW_FROM=any: no address filter" ;;
  *) fail "ALLOW_FROM must be cloudflare or any" ;;
esac
export RECAST_DOMAIN RECAST_ALLOW
envsubst '${RECAST_DOMAIN}' < "$here/gateway-recast.conf.in" > "$stage/recast.conf"
envsubst '${RECAST_ALLOW}' < "$here/proxy.inc.in" > "$stage/proxy.inc"

conf="$(grep -hv '^\s*#' "$stage/recast.conf" "$stage/proxy.inc")"
echo "$conf" | grep -q 'default_server' && fail "default_server would capture other sites"
names="$(grep -v '^\s*#' "$stage/recast.conf" | grep -E '^\s*server_name\s' | sed -E 's/^\s*server_name\s+//; s/;\s*$//' | tr ' ' '\n' | sort -u)"
[ "$names" = "$RECAST_DOMAIN" ] || fail "server_name must be exactly $RECAST_DOMAIN, got: $(echo $names)"
echo "$conf" | grep -q '\${' && fail "unrendered placeholder left in the file"

# The origin certificate: self-signed, kept across renders. Cloudflare Full mode accepts it.
tls="$EDGE_DIR/edge/tls"
if [ -f "$tls/fullchain.pem" ]; then cp "$tls"/*.pem "$stage/tls/"; else
  openssl req -x509 -nodes -newkey rsa:2048 -days 3650 -subj "/CN=$RECAST_DOMAIN" \
    -addext "subjectAltName=DNS:$RECAST_DOMAIN" \
    -keyout "$stage/tls/privkey.pem" -out "$stage/tls/fullchain.pem" 2>/dev/null
fi

# Test it exactly as the edge will load it. recast-web is resolved per request, so no upstream is needed.
docker run --rm -v "$stage/recast.conf:/etc/nginx/conf.d/default.conf:ro" -v "$stage:/etc/recast-edge:ro" \
  --entrypoint nginx nginx:1.27-alpine -t -q || fail "nginx -t failed"

# Written in place, never replaced: the edge bind-mounts recast.conf as a single file, and a
# replaced file (new inode) would stay invisible to it until the edge is recreated.
mkdir -p "$EDGE_DIR/edge/tls"
for f in recast.conf proxy.inc tls/fullchain.pem tls/privkey.pem; do cat "$stage/$f" > "$EDGE_DIR/edge/$f"; done
chmod 0644 "$EDGE_DIR/edge/recast.conf" "$EDGE_DIR/edge/proxy.inc" "$EDGE_DIR/edge/tls/fullchain.pem"
chmod 0600 "$EDGE_DIR/edge/tls/privkey.pem"
echo "render.sh: wrote $EDGE_DIR/edge (server_name $RECAST_DOMAIN only, allow=$ALLOW_FROM, nginx -t ok)"
