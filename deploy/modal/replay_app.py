"""Replay a finished job's request through a running server's HTTP API, end to end.

    .venv/bin/python deploy/modal/replay_app.py <old job.json> --api http://127.0.0.1:8781 \\
        --data runs/app_modal --uploads-from runs/app [--render]

Creates a job with the same params as the old one, asks for the preview (the server's default
seed, as the original had), and with --render approves it and waits for the video. The uploads
the params name are copied into the target server's data dir first, so the server must be
started AFTER this has copied them (it loads uploads at startup): run once with --copy-only,
start the server, then run again.

This is the path a judge takes (web app -> server -> comfy-sdk -> proxy -> ComfyUI), minus the
browser; tools/e2e_browser.py covers the browser. Prints each state change with its time.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import urllib.request
from pathlib import Path


def call(api: str, method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else (b"{}" if method == "POST" else None)
    req = urllib.request.Request(api + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def upload_ids(params: dict) -> list[str]:
    ids = [(params.get("motion") or {}).get("upload_id")]
    ids += [c.get("upload_id") for c in params.get("characters") or []]
    ids += [(params.get(k) or {}).get("upload_id") for k in ("outfit", "prop", "place")]
    return [i for i in ids if i]


def wait(api: str, jid: str, until: set[str], t0: float, deadline_s: int) -> dict:
    last = None
    while time.time() - t0 < deadline_s:
        j = call(api, "GET", f"/api/jobs/{jid}")
        stage = (j["state"], (j.get("progress") or {}).get("stage"))
        if stage != last:
            print(f"  {time.time() - t0:7.0f}s  {j['state']}  {stage[1] or ''}", flush=True)
            last = stage
        if j["state"] in until:
            return j
        time.sleep(5)
    raise TimeoutError(f"{jid} not in {until} after {deadline_s}s")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("job_json", type=Path)
    ap.add_argument("--api", default="http://127.0.0.1:8781")
    ap.add_argument("--data", type=Path, required=True, help="the target server's RECAST_DATA")
    ap.add_argument("--uploads-from", type=Path, required=True, help="the original server's RECAST_DATA")
    ap.add_argument("--copy-only", action="store_true")
    ap.add_argument("--render", action="store_true", help="approve the preview and wait for the video")
    a = ap.parse_args()

    old = json.loads(a.job_json.read_text())
    params = old["params"]
    for uid in upload_ids(params):
        dst = a.data / "uploads" / uid
        if not dst.exists():
            shutil.copytree(a.uploads_from / "uploads" / uid, dst)
            print(f"copied upload {uid}")
    if a.copy_only:
        return 0

    t0 = time.time()
    j = call(a.api, "POST", "/api/jobs", params)
    print(f"{j['id']} replays {old['id']} ({params.get('mode')}, {params['motion']['length']} s)", flush=True)
    call(a.api, "POST", f"/api/jobs/{j['id']}/preview")
    j = wait(a.api, j["id"], {"awaiting_approval", "failed"}, t0, 3600)
    timing = {"job": j["id"], "replays": old["id"], "preview_s": round(time.time() - t0, 1)}
    if j["state"] == "awaiting_approval" and a.render:
        t1 = time.time()
        call(a.api, "POST", f"/api/jobs/{j['id']}/approve")
        j = wait(a.api, j["id"], {"done", "failed"}, t1, 4 * 3600)
        timing["render_s"] = round(time.time() - t1, 1)
        timing["render_seconds_server"] = (j.get("result") or {}).get("render_seconds")
    timing["state"] = j["state"]
    timing["error"] = j.get("error")
    print(json.dumps(timing), flush=True)
    return 0 if j["state"] in ("awaiting_approval", "done") else 1


if __name__ == "__main__":
    sys.exit(main())
