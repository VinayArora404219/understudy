#!/usr/bin/env bash
# Run the backend and the web app together against a ComfyUI you control.
# The only machine-specific setting is the endpoint: COMFY_BASE_URL (and COMFY_API_KEY
# when the endpoint needs one), read from .env. The same server talks to a Modal
# deployment by pointing COMFY_BASE_URL at it.
#
#   tools/serve_local.sh      # backend on :8780, web app on http://localhost:5180
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && { set -a; . ./.env; set +a; }
: "${COMFY_BASE_URL:?set COMFY_BASE_URL in .env (see .env.example)}"

.venv/bin/python -m uvicorn server.app:app --host 127.0.0.1 --port 8780 &
api=$!
trap 'kill $api 2>/dev/null' EXIT
cd web && VITE_API=live npm run dev -- --host 127.0.0.1
