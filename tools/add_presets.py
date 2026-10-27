"""Install the ready-made motions ("Use one of ours") into RECAST_DATA/presets/, from the example clips.

    python3 tools/add_presets.py [--clips examples/clips]

Each becomes presets/<id>/clip.mp4, thumb.jpg and preset.json; the running server lists them at once. The clips
are Pexels videos with sound added (examples/README.md has the sources and licences); they are not in git.
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recast import media  # noqa: E402

PRESETS = [  # id (file name), title, subtitle, credit: the Pexels creator
    ("dance_trio", "Dance trio", "Three dancers, far apart, music", "Yan Krukau / Pexels"),
    ("dance_duo_studio", "Studio duo", "Two dancers, white studio, music", "Polina Tankilevitch / Pexels"),
    ("dance_breaking", "Breaking", "Floor work and legs overhead, music", "Allan Mas / Pexels"),
    ("dance_ballet_balcony", "Balcony kicks", "High kicks on a narrow balcony, music", "Los Muertos Crew / Pexels"),
    ("dance_man_and_dog", "Man and dog", "A man and his dog dance together, music", "K / Pexels"),
    ("group_office", "Office chat", "Six coworkers talking, room sound", "Diva Plavalaguna / Pexels"),
    ("street_sunglasses", "Sunglasses off", "She takes her sunglasses off in the street", "Connor Scott McManus / Pexels"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", default=str(Path(__file__).resolve().parents[1] / "examples" / "clips"))
    a = ap.parse_args()
    out = Path(os.environ.get("RECAST_DATA", "runs/app")).resolve() / "presets"
    for pid, title, subtitle, credit in PRESETS:
        src = Path(a.clips) / f"{pid}.mp4"
        if not src.exists():
            print(f"skipped {pid}: no {src}")
            continue
        d = out / pid
        d.mkdir(parents=True, exist_ok=True)
        clip = Path(shutil.copy(src, d / "clip.mp4"))
        info = media.validate_upload(clip)
        box = media.content_box(clip)
        w, h = box[:2] if box else (info.width, info.height)
        media.frame_at(clip, d / "thumb.jpg", layout=media.layout_for(w, h), long_side=640, box=box)
        (d / "preset.json").write_text(json.dumps({"title": title, "subtitle": subtitle, "credit": credit,
                                                   "seconds": round(info.seconds, 2)}, indent=1))
        print(f"{pid}: {info.seconds:.1f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
