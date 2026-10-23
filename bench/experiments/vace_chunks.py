"""Restyle past 5 s with the app's engine (recast/vace.py): chunked, and with a scene line that names no events.

Two questions at once (bench/RESULTS.md, "Restyle by video-to-video"): do chunk joins hold (anchor on the
previous chunk's last frames), and does the motion still come through when the prompt says only who, what
they wear and where? (vace_restyle.py's runs named the events: "takes out sunglasses", "a car drives away".)

    python bench/experiments/vace_chunks.py --drive drive.mp4 --reference styled_frame.png --style anime \\
        --scene "a young man in a white t-shirt on a city street" --chunks 2 --out bench/runs/vace_10s
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from comfy_sdk import Comfy

from recast import describe, media, recipe, runner, styles, vace


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--drive", required=True, type=Path, help="normalised clip: render size, 16 fps")
    ap.add_argument("--reference", required=True, type=Path, help="the restyled first frame")
    ap.add_argument("--style", required=True, choices=sorted(styles.STYLES))
    ap.add_argument("--scene", help="who is in the clip, what they wear, where")
    ap.add_argument("--read-scene", action="store_true",
                    help="let the clip reader write --scene from four moments of the clip, as the app does")
    ap.add_argument("--layout", default="portrait")
    ap.add_argument("--chunks", type=int, default=2)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    drive, ref = a.out / "drive.mp4", a.out / "reference.png"
    drive.write_bytes(a.drive.read_bytes())
    ref.write_bytes(a.reference.read_bytes())
    if media.probe(drive).frames < vace.frames_for(a.chunks):
        ap.error(f"{a.chunks} chunks need {vace.frames_for(a.chunks)} frames")
    if bool(a.scene) == a.read_scene:
        ap.error("give --scene or --read-scene")
    if a.read_scene:
        sheet = media.moments_sheet(drive, a.out / "moments.png")
        with Comfy(timeout=120) as client:
            dj = runner.follow(runner.submit_graph(
                client, lambda: describe.build_role(client.assets.from_file(sheet), "scene", prefix="recast/scene"),
                a.out / "scene_submission.json"))
            files = runner.download(dj, a.out / "scene", node_id=describe.FINAL_NODE)
        a.scene = describe.parse_role(files[0].read_text(), "scene") if files else ""
        print(f"clip reader: {a.scene}", flush=True)
        if not a.scene:
            raise SystemExit("the clip reader wrote nothing")
    p = vace.VaceParams(drive="drive.mp4", reference="reference.png", prompt=vace.prompt(a.scene, a.style),
                        layout=a.layout, chunks=a.chunks, seed=a.seed, prefix="recast/vace")
    g = vace.build(p)
    (a.out / "graph.json").write_text(json.dumps(g, indent=1, ensure_ascii=False))
    print(f"{a.chunks} chunk(s), {vace.frames_for(a.chunks)} frames\nprompt: {p.prompt}", flush=True)
    t0 = time.time()
    with Comfy(timeout=120) as client:
        def make():
            p.drive, p.reference = client.assets.from_file(drive), client.assets.from_file(ref)
            return vace.build(p)
        job = runner.follow(runner.submit_graph(client, make, a.out / f"submission_{recipe.graph_sha(g)[:10]}.json"),
                            lambda ev: ev["kind"] != "progress" and print(f"  {ev}", flush=True))
        files = runner.download(job, a.out / "render", node_id=vace.FINAL_NODE)
    print(f"done in {time.time() - t0:.1f}s -> {files}")


if __name__ == "__main__":
    main()
