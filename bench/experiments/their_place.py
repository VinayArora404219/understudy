"""The start picture for "the character's place": the clip's performers, recast, in the (left) character's own photo.

The recipe that put two cats dancing in one cat's kitchen (recast/reference.py, base="character"): the
character's photo is image1, so its room is the room; the second character is content only (head and
shoulders, cut out); the clip frame is not an input at all, its layout, poses and props come as words.
The picture is then animated by the clip's motion (bench/experiments/scail.py --mode animate).

    python bench/experiments/their_place.py --layout square --character left.png --text "..." \\
        --character2 right.png --text2 "..." --pose "..." --pose2 "..." [--props "..."] --out bench/runs/x
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from comfy_sdk import Comfy

from recast import crop, media, recipe, runner
from recast import reference as reflib


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--layout", required=True)
    ap.add_argument("--character", required=True, type=Path, help="whose place it is; the performer on the left")
    ap.add_argument("--text", required=True)
    ap.add_argument("--character2", type=Path)
    ap.add_argument("--text2", default="")
    ap.add_argument("--pose", default="")
    ap.add_argument("--pose2", default="")
    ap.add_argument("--props", default="")
    ap.add_argument("--subject", default="person")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)

    base = crop.to_shape(media.clean_image(a.character, a.out / "character_full.png"), a.out / "character.png",
                         a.layout)
    images = {"character": base}
    if a.character2:
        head = crop.head_and_shoulders(a.character2, a.out / "character2_head.png") or a.character2
        images["character2"] = media.clean_image(head, a.out / "character2.png")
    mp = reflib.MatchParams(frame=None, base="character", character_text=a.text, character2_text=a.text2,
                            pose=a.pose, pose2=a.pose2, props=a.props, subject=a.subject,
                            cutout_colour=media.edge_colour(base), seed=a.seed, prefix="recast/their_place",
                            **{k: v.name for k, v in images.items()})
    g = reflib.build(mp)
    (a.out / "graph.json").write_text(json.dumps(g, indent=1, ensure_ascii=False))
    print(f"prompt: {reflib.prompt_for(mp)}", flush=True)

    t0 = time.time()
    with Comfy(timeout=120) as client:
        def make():
            for k, v in images.items():
                setattr(mp, k, client.assets.from_file(v))
            return reflib.build(mp)
        job = runner.follow(runner.submit_graph(client, make, a.out / f"submission_{recipe.graph_sha(g)[:10]}.json"))
        files = runner.download(job, a.out / "render", node_id=reflib.FINAL_NODE)
    if not files:
        raise SystemExit("the edit finished without an image")
    still = media.fit_image(files[0], a.out / "start.png", layout=a.layout, mode="crop")
    print(f"done in {time.time() - t0:.0f}s -> {still}")


if __name__ == "__main__":
    main()
