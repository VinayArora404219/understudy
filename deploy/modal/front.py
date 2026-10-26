"""comfy-api-proxy 0.1.6 behind Modal's HTTPS edge.

This is the proxy's own app (`make_app`) with the proxy's own bearer-token gate
(`make_bearer_auth_middleware`, the same check `comfy-api-proxy run --token` installs).
It adds one middleware the CLI has no flag for:

The proxy builds every absolute link it returns (job urls, Output.url, Asset.url) from
the scheme and Host of the request it received, and deliberately ignores X-Forwarded-*.
Modal terminates TLS at its edge and forwards plain HTTP, so unpatched the proxy hands
the SDK `http://...` links. comfy-sdk treats those as a different origin from the
`https://...` COMFY_BASE_URL and, by design, does not attach the key to them, so the
first output download fails with 401. The only way into this container is Modal's
HTTPS edge, so the scheme a client used is always https: say so before the proxy
builds anything. Host is left alone; Modal forwards the public host unchanged.

Run by app.py as `python front.py`; the key comes from the COMFY_API_KEY secret.
"""

from __future__ import annotations

import os
import sys

from aiohttp import web
from comfy_api_proxy.app import make_app
from comfy_api_proxy.auth import make_bearer_auth_middleware
from comfy_api_proxy.middleware import make_origin_only_middleware


@web.middleware
async def https_edge(request: web.Request, handler):
    return await handler(request.clone(scheme="https"))


def main() -> int:
    token = os.environ.get("COMFY_API_KEY", "").strip()
    if not token:
        # A public URL with no key is an open GPU. Refuse rather than serve.
        print("COMFY_API_KEY is not set; refusing to serve the proxy unauthenticated", file=sys.stderr)
        return 2
    app = make_app(
        os.environ.get("COMFY_URL", "http://127.0.0.1:8188"),
        state_dir=os.environ["PROXY_STATE_DIR"],
        max_upload_bytes=int(os.environ.get("PROXY_MAX_UPLOAD_MB", "100")) * 1024 * 1024,  # the CLI default
        # the CLI's order (CORS, origin guard, auth), with the scheme fix outermost so every
        # handler and link builder sees it
        middlewares=[https_edge, make_origin_only_middleware([]), make_bearer_auth_middleware(token)],
    )
    web.run_app(app, host="0.0.0.0", port=int(os.environ.get("PROXY_PORT", "8000")), print=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
