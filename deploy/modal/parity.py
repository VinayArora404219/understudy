"""Replay one finished job's exact graph on another backend and compare the outputs.

    .venv/bin/python deploy/modal/parity.py <job dir> <graph json in it> <box outputs dir> --out <dir>

The server saves the API graph it submitted next to the job (graph.json for a render,
reference_graph_*.json for a preview), with its inputs referenced by plain file names that
sit in the same job dir. This uploads those same files as SDK assets, submits the same graph
(same seed, same everything) through comfy-sdk to whatever COMFY_BASE_URL/COMFY_API_KEY name,
downloads every output and compares each with the backend that made the originals, frame by
frame (ffmpeg SSIM and PSNR).

That isolates the backend: the app's own code, which may have changed since the original job,
plays no part. Run it from the repo root with .venv; outputs stay in --out (keep it under an
ignored directory: test media is private).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

FILE_INPUTS = {("LoadImage", "image"), ("LoadVideo", "file"), ("VHS_LoadVideo", "video")}


def compare(a: Path, b: Path) -> dict:
    """Mean SSIM and PSNR of b against a (images or videos; b is scaled to a if sizes differ)."""
    cmd = ["ffmpeg", "-v", "info", "-nostats", "-i", str(a), "-i", str(b), "-lavfi",
           "[1:v][0:v]scale2ref=flags=bicubic[b][a];[a]split[a1][a2];[b]split[b1][b2];"
           "[a1][b1]ssim;[a2][b2]psnr", "-f", "null", "-"]
    err = subprocess.run(cmd, capture_output=True, text=True).stderr
    ssim = re.search(r"SSIM .*All:([\d.]+)", err)
    psnr = re.search(r"PSNR .*average:([\d.inf]+)", err)
    return {"ssim": float(ssim.group(1)) if ssim else None,
            "psnr_db": float(psnr.group(1)) if psnr and psnr.group(1) != "inf" else (float("inf") if psnr else None)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("job_dir", type=Path)
    ap.add_argument("graph", help="graph file inside job_dir (graph.json, reference_graph_*.json)")
    ap.add_argument("box_outputs", type=Path, help="dir holding the original outputs to compare against")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()

    from comfy_sdk import Comfy

    g = json.loads((a.job_dir / a.graph).read_text())
    a.out.mkdir(parents=True, exist_ok=True)
    report: dict = {"graph": a.graph, "job": a.job_dir.name}
    t0 = time.time()
    with Comfy(timeout=120) as client:
        for node in g.values():
            for key, val in list(node["inputs"].items()):
                if (node["class_type"], key) in FILE_INPUTS and isinstance(val, str):
                    node["inputs"][key] = client.assets.from_file(a.job_dir / val)
        job = client.submit(client.workflows.from_json(g), idempotency_key=f"parity-{uuid.uuid4().hex}")
        print(f"submitted {job.id}", flush=True)
        job = job.result()
        report["wall_s"] = round(time.time() - t0, 1)
        saves = [k for k, v in g.items() if v["class_type"].startswith("Save")]
        got = []
        for node_id in saves:
            for o in job.get_outputs(node_id):
                got.append(o.to_file(a.out / Path(o.name).name))
    print(f"done in {report['wall_s']}s, {len(got)} output(s)", flush=True)

    # pair each new output with the original of the same name minus the server's numbering
    def stem(p: Path) -> str:
        return re.sub(r"_\d{5}_$", "", p.stem)
    originals = {stem(p): p for p in a.box_outputs.iterdir() if p.is_file()}
    report["outputs"] = []
    for p in got:
        o = originals.get(stem(p))
        row = {"file": p.name, "original": o.name if o else None}
        if o:
            row |= compare(o, p)
        report["outputs"].append(row)
        print(json.dumps(row), flush=True)
    (a.out / "parity.json").write_text(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
