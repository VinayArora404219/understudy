"""Write the ComfyUI API graphs the app runs to workflows/api/, built by the same code (recast/), with example
inputs in place of a visitor's files. Each job's own recipe.json holds the exact graph it ran; these are the
same graphs with readable file names, to open in ComfyUI or submit through the API or the Comfy SDK.

    python3 tools/export_workflows.py            # writes workflows/api/*.json and workflows/api/README.md
    python3 tools/export_workflows.py --check    # exits 1 if the files are out of date (tests run this)
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recast import describe, people, scail, vace  # noqa: E402
from recast import reference as reflib  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "workflows" / "api"

SHE = "A young woman with a narrow oval face, light freckles, green eyes and a pink chin-length bob, in a yellow raincoat"
HE = "A man in his fifties with a round face, olive skin, a black-and-grey handlebar moustache, in a white chef's jacket"


def graphs() -> dict[str, tuple[str, dict]]:
    """file name -> (what it does, API graph)."""
    out: dict[str, tuple[str, dict]] = {}

    def recast(**kw) -> dict:
        return scail.build(scail.ScailParams(drive="drive.mp4", reference="reference.png", layout="portrait_hd",
                                             seed=1, prefix="recast/recast", **kw))

    out["recast_one_clip_place.json"] = (
        "Recast, one chosen performer, in the clip's own place, 5 s (one chunk). Inputs: `drive.mp4` (the clip, "
        "16 fps, 576x1024), `reference.png` (the character cut out of their photo and placed where the performer "
        "stands), `pick0.png` (the performer's mask in the first frame, white on black). Putting everyone who was "
        "not chosen back as filmed is a step after this graph (recast/composite.py).",
        recast(prompt=scail.prompt([SHE], [], replace=True), track="person", people=1, replace=True,
               picks=["pick0.png"]))
    out["recast_duo_clip_place_10s.json"] = (
        "Recast, two chosen performers, in the clip's own place, 10 s: two chunks (9.8 s), the second anchored on the "
        "first's last 5 frames. Inputs as above, with `pick0.png` and `pick1.png`, left to right.",
        recast(prompt=scail.prompt([SHE, HE], [], replace=True), track="person", people=2, replace=True,
               picks=["pick0.png", "pick1.png"], chunks=2, frames=161))
    out["recast_7s_short_last_chunk.json"] = (
        "Recast, 7 s: a whole chunk and a short last one (81 + 37 frames), so only what is asked is rendered.",
        recast(prompt=scail.prompt([SHE], [], replace=True), track="person", people=1, replace=True,
               picks=["pick0.png"], chunks=2, frames=113))
    out["recast_another_place.json"] = (
        "Recast into another place: SCAIL-2 animates `reference.png`, a start picture of the character already "
        "in the new place (made with `start_picture_another_place.json`). The performer is found by words.",
        recast(prompt=scail.prompt([SHE], ["stands facing forward, both hands at the sides"], replace=False,
                                   place="a neon-lit arcade at night"),
               track="person", people=1, replace=False))
    out["restyle.json"] = (
        "Restyle, 5 s: Wan2.1 VACE redraws every frame from its depth map, in the look of `reference.png` (the "
        "first frame restyled, made with `start_picture_restyle.json`).",
        vace.build(vace.VaceParams(drive="drive.mp4", reference="reference.png", layout="portrait",
                                   prompt=vace.prompt("Two women dancing in a white studio", "anime"),
                                   seed=1, prefix="recast/restyle")))
    out["start_picture_another_place.json"] = (
        "Qwen-Image-Edit-2511: the character from `character.png` in the place described, posed like the clip.",
        reflib.build(reflib.MatchParams(frame=None, base="character", character="character.png",
                                        character_text=SHE, scene="keep", side="center", shot="whole body",
                                        pose="stands facing forward, both hands at the sides", seed=1,
                                        prefix="recast/reference")))
    out["start_picture_restyle.json"] = (
        "Qwen-Image-Edit-2511: the clip's first frame `frame.png`, redrawn in a look.",
        reflib.build(reflib.MatchParams(frame="frame.png", style="anime", seed=1, prefix="recast/reference")))
    out["restage_outfit.json"] = (
        "Restage, new outfit: the performer's first frame `frame.png` in the garment from `outfit.png`. The video "
        "is then a Recast of the performer as themselves, with this picture as the reference.",
        reflib.build(reflib.MatchParams(frame="frame.png", outfit="outfit.png", outfit_text="a red leather biker jacket",
                                        seed=1, prefix="recast/reference")))
    out["find_people.json"] = (
        "SAM 3.1 finds everyone in `frame.png`, one mask each: the picker the visitor taps.",
        people.build_detect("frame.png"))
    out["describe_character.json"] = (
        "Qwen3-VL writes a character's words from `character.png`.",
        describe.build_role("character.png", "character"))
    return out


def readme(gs: dict[str, tuple[str, dict]]) -> str:
    rows = "\n".join(f"| [`{name}`]({name}) | {what} |" for name, (what, _) in gs.items())
    return f"""# API workflows

The graphs the app runs, in ComfyUI's API format, written by `tools/export_workflows.py` from the same code
the server builds them with (`recast/`). The input file names are examples: put your own files in ComfyUI's
`input/` folder under those names, or change the names in the graph. Every job the app runs also saves the
exact graph it ran, with its own file names and seed, in its `recipe.json`.

ComfyUI's editor opens API-format files as graphs: drag one onto the canvas. (Checked by loading
`recast_one_clip_place.json` into ComfyUI v0.41.3: all 30 nodes and their links.)

The models and custom nodes they need are listed, with sources and hashes, in
[`manifests/models.json`](../../manifests/models.json).

| Workflow | What it does |
|---|---|
{rows}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    gs = graphs()
    files = {name: json.dumps(g, indent=1, ensure_ascii=False) + "\n" for name, (_, g) in gs.items()}
    files["README.md"] = readme(gs)
    stale = [n for n, text in files.items() if not (OUT / n).exists() or (OUT / n).read_text() != text]
    extra = sorted(p.name for p in OUT.glob("*.json") if p.name not in files) if OUT.exists() else []
    if a.check:
        if stale or extra:
            print("out of date:", *stale, *extra)
            return 1
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    for n in stale:
        (OUT / n).write_text(files[n])
    for n in extra:
        (OUT / n).unlink()
    print(f"wrote {len(stale)}, removed {len(extra)}, in {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
