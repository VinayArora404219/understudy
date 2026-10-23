"""Duo experiment: two performers in one clip, each replaced by its own character.

Question: can the open stack do Genjutsu's "duo" case? The matched reference is
built by Qwen-Image-Edit-2511 with the clip's first frame as image1 and one
character per remaining slot (image2 = the performer on the picture's left,
image3 = the one on its right). Directions are frame-relative ("on the left of
the first picture"), never body-relative: body-relative ones mirror.

Both measured pose fixes are applied: each character image is cropped to head
and shoulders (fix C) and the performers' poses are spelled out (fix A), so a
failure here is about two identities, not about pose leaking.

    python bench/experiments/duo.py --frame f.png --left a.png --left-text "..." \\
        --right b.png --right-text "..." --left-subject dog --right-subject cat \\
        --left-pose "..." --right-pose "..." --out bench/runs/duo --seeds 1 2

Writes duo_ref_seed<N>.png per seed plus results.json. Render the chosen one with
`recast run --reference ... --appearance ...` (see bench/RESULTS.md, duo).
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from comfy_sdk import Comfy

from recast import media, runner
from recast import reference as reflib


def prompt(a: argparse.Namespace) -> str:
    return (f"Replace the {a.left_subject} on the left of the first picture with the person from the second "
            f"picture: {a.left_text}. Replace the {a.right_subject} on the right of the first picture with the "
            f"person from the third picture: {a.right_text}. The person on the left {a.left_pose}. The person on "
            f"the right {a.right_pose}. Each person takes the size and position of the animal they replace; use "
            f"the second and third pictures only for faces and clothing, not pose. Two people, side by side. "
            f"Same camera and framing as the first picture.")


def graph(a: argparse.Namespace, frame, left, right, seed: int) -> dict:
    mp = reflib.MatchParams(frame=frame, character=left, character_text=a.left_text, subject="animal",
                            quality=a.quality, seed=seed, prefix=f"recast/duo_s{seed}")
    g = reflib.build(mp)
    g["character2"] = {"class_type": "LoadImage", "inputs": {"image": right}}
    g["character2_rs"] = {"class_type": "FluxKontextImageScale", "inputs": {"image": ["character2", 0]}}
    for enc in ("pos", "neg"):
        g[enc]["inputs"]["image3"] = ["character2_rs", 0]
    g["pos"]["inputs"]["prompt"] = prompt(a)
    return g


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frame", required=True, type=Path, help="the clip's first frame (bars removed)")
    ap.add_argument("--left", required=True, type=Path)
    ap.add_argument("--right", required=True, type=Path)
    ap.add_argument("--left-text", required=True)
    ap.add_argument("--right-text", required=True)
    ap.add_argument("--left-subject", default="animal")
    ap.add_argument("--right-subject", default="animal")
    ap.add_argument("--left-pose", required=True, help="frame-relative, concrete: 'leans forward, both hands on ...'")
    ap.add_argument("--right-pose", required=True)
    ap.add_argument("--layout", default="square")
    ap.add_argument("--quality", choices=["fast", "high"], default="fast")
    ap.add_argument("--seeds", type=int, nargs="+", default=[1])
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)

    results_path = a.out / "results.json"
    results = json.loads(results_path.read_text()) if results_path.exists() else {}
    with Comfy(timeout=120) as client:
        for seed in a.seeds:
            t0 = time.time()
            job = runner.submit_graph(
                client, lambda: graph(a, client.assets.from_file(a.frame), client.assets.from_file(a.left),
                                      client.assets.from_file(a.right), seed),
                a.out / f"submission_seed{seed}.json")
            job = runner.follow(job)
            files = runner.download(job, a.out / f"render_seed{seed}", node_id=reflib.FINAL_NODE)
            ref = media.fit_image(files[0], a.out / f"duo_ref_seed{seed}.png", layout=a.layout, mode="crop")
            results[f"seed{seed}"] = {"seconds": round(time.time() - t0, 1), "reference": ref.name,
                                      "quality": a.quality, "prompt": prompt(a)}
            results_path.write_text(json.dumps(results, indent=1))
            print(f"seed {seed}: {ref} ({results[f'seed{seed}']['seconds']} s)")


if __name__ == "__main__":
    main()
