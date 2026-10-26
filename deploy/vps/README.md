# Hosting the app on a VPS that already runs another site

This is how the web app (`server/` + `web/`) runs on a small CPU-only VPS whose ports 80 and 443
already belong to another site's nginx container (the *edge*). The GPU work goes to the Modal
endpoint (`deploy/modal/README.md`), so the VPS runs only FastAPI, ffmpeg and mediapipe.

Rules this layout keeps:

- **The other site never shows this app.** Recast's vhost matches only its own `server_name`. It
  has no `default_server` and no wildcard. Any other hostname, the bare IP and clients without SNI
  keep reaching the edge's own site, exactly as before. nginx chooses the block by `Host`, so a
  request naming the other site always lands there. `render.sh` refuses to write a vhost that
  breaks this rule.
- **The other site never depends on this app.** The vhost resolves its upstream per request. If
  recast is stopped, the edge still starts and reloads, and only recast's domain returns 502.
- **No shared state.** Recast runs as its own Compose project with no published ports. It is on
  its own network (`recast_edge`); only the edge joins it. Recast cannot see the other site's
  containers, and it keeps its own certificate store.
- **Nothing machine-specific in git.** Domain, keys, certificates and data live in `$EDGE_DIR`.
- **Only the CDN may connect.** Port 80 allows Cloudflare's ranges and denies everyone else.

```
browser ─HTTPS─> edge nginx :443 ──(Host = RECAST_DOMAIN)──> recast-web :80 ──/api──> recast-api :8780 ──> Modal
                 (the other site's)     network recast_edge     static + basic auth      uvicorn, 1 worker
```

## TLS: Cloudflare in front

The domain is proxied by Cloudflare, which holds the public certificate. With Flexible SSL it
reaches the edge over plain HTTP on port 80, so port 80 serves the app. A request that Cloudflare
marks `X-Forwarded-Proto: http`, meaning a visitor typed `http://`, is redirected to https before
anything asks for a password. Port 443 has a self-signed certificate that `render.sh` makes once,
so Full mode works too. Full (strict) would need a real origin certificate. Only Cloudflare's
published ranges may connect (`ALLOW_FROM=cloudflare`). Anyone else gets 403, so the origin can't be
reached around the CDN.

**Cloudflare caps a request body at 100 MB on the free plan** (measured: 95 MB passes, 110 MB gets
Cloudflare's 413 page). So the app's own limit is 90 MB: a larger clip gets the app's own message, not
Cloudflare's error page.

## Files

| File | Role |
|---|---|
| `docker-compose.yml` | The `recast` project: `recast-api` (2 CPU / 4 GiB cap) and `recast-web`. No ports. |
| `Dockerfile.api` | python 3.11 + ffmpeg + `.[server]`. Runs **one** uvicorn worker, because jobs and the GPU queue live in process memory. |
| `Dockerfile.web` | Builds the app with `VITE_API=live`, then serves it with nginx. |
| `nginx.web.conf` | SPA + `/api` proxy + basic auth + a 95 MB body limit (uploads are capped at 90 MB). |
| `gateway-recast.conf.in`, `proxy.inc.in` | The edge vhost (ports 80 and 443) and the proxy block both share. |
| `render.sh` | Renders both files, refuses unsafe ones, makes the origin certificate, and runs `nginx -t`. It writes in place, so the edge only needs `nginx -s reload`. |

## `$EDGE_DIR` (on the VPS, outside the checkout)

```
recast.env      COMFY_BASE_URL=<modal endpoint>  COMFY_API_KEY=<key>  RECAST_RENDERS=<cap>
htpasswd        basic-auth users (SHA-512 crypt; nginx:alpine cannot check bcrypt)
data/           uploads, jobs, outputs; owned by uid 10001
edge/           recast.conf, proxy.inc, tls/   -> mounted into the edge (see step 4)
```

## Steps

Point the domain at the VPS through Cloudflare (proxied) first.

1. **The app, internal only.** Nothing on the other site changes.

```bash
export EDGE_DIR=/srv/recast-edge RECAST_DOMAIN=recast.example.com
mkdir -p $EDGE_DIR/data && chown 10001 $EDGE_DIR/data
# recast.env (mode 600): COMFY_BASE_URL, COMFY_API_KEY (from deploy/modal), RECAST_RENDERS
printf 'judge:%s\n' "$(openssl passwd -6)" > $EDGE_DIR/htpasswd
docker network create recast_edge
docker compose -f deploy/vps/docker-compose.yml up -d --build
```

   Ready-made motions and Examples are made on the development machine (`tools/add_presets.py`,
   `tools/add_gallery.py`) and copied over: `rsync -a runs/app/presets runs/app/gallery <vps>:$EDGE_DIR/data/`,
   then `chown -R 10001 $EDGE_DIR/data`. The app lists them without a restart.

   If the VPS can't reach Debian's or PyPI's CDN (seen once: both timed out while other mirrors
   ran at 6 MB/s), build the images somewhere else and ship them over. Then start the stack with
   `up -d --no-build`:

```bash
docker compose -f deploy/vps/docker-compose.yml build
docker save recast-recast-api recast-recast-web | zstd -T0 -3 | ssh <vps> 'zstd -d | docker load'
```

2. **The vhost**, checked before the edge ever sees it: `deploy/vps/render.sh`.
3. **Preflight with the edge's own image and live config**, not just stock nginx. Copy the edge's
   `conf.d/default.conf` out with `docker exec`, then run `nginx -t` in a throwaway container from
   the edge's image. Mount that copy, `$EDGE_DIR/edge/recast.conf`, `$EDGE_DIR/edge` and the
   edge's own certificate mounts into it.
4. **Edge change (the one step that touches the other site).** Add the block below to the edge's
   Compose override, but on a copy first. Render `docker compose config` with the copy and with the
   original. Only the edge service's config hash may differ, and its diff must be just these lines.
   Then put the copy in place and recreate the edge alone with
   `docker compose up -d --no-deps <edge service>`. Measured: about 12 s for the whole command,
   and the outage is shorter. To roll back, restore the backup and run the same command.

```yaml
services:
  <edge service>:
    volumes:
      - ${EDGE_DIR}/edge/recast.conf:/etc/nginx/conf.d/recast.conf:ro
      - ${EDGE_DIR}/edge:/etc/recast-edge:ro
    networks: [recast_edge]
networks:
  recast_edge: { external: true }
```

Later changes need no edge restart:
- A vhost change: run `render.sh`, then `docker exec <edge> nginx -t && docker exec <edge> nginx -s reload`.
- A password change: edit `htpasswd`, then run `docker compose -p recast restart recast-web`.
- A new app version: rebuild, then `up -d`. Deploy between renders.

## Checks after the edge change

```bash
# the other site: run each of these before and after; the output must be identical
curl -s https://<other site>/ ; curl -s https://<other site>/api/... ; curl -s http://<vps ip>/
curl -sk https://<vps ip>/                          # no SNI: the other site's certificate
echo | openssl s_client -connect <vps ip>:443 -noservername 2>/dev/null | openssl x509 -noout -subject

# recast
curl -sI https://$RECAST_DOMAIN/                    # 401
curl -sI http://$RECAST_DOMAIN/                     # 301 to https, before any password
curl -sI -H "Host: $RECAST_DOMAIN" http://<vps ip>/  # 403: not via Cloudflare
curl -s -u judge:<pw> https://$RECAST_DOMAIN/api/session
docker compose -f deploy/vps/docker-compose.yml stop    # recast domain 502, other site unchanged
docker exec $EDGE_CONTAINER nginx -s reload             # still succeeds with recast down
docker compose -f deploy/vps/docker-compose.yml start
```

Every check above was run on the live edge, and before that against a simulated one: a stand-in site as the default server, with
recast mounted beside it. That covered the other site's paths `/`, `/api/session`, `/assets/` and
`/index.html`, the bare IP over http and https, unknown hosts and the no-SNI certificate. It also
covered a 150 MB upload through both nginx layers, and a reload and full restart of the edge with
recast stopped.
