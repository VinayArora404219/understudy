"""Install examples already made into RECAST_DATA/gallery/, from finished jobs on this server.

    python3 tools/add_gallery.py spec.json

spec.json: {"looks": {"<style key>": "<job id>", ...},
            "items": [{"id": "office_two", "job": "<job id>", "title": "...", "line": "..."}, ...]}

A look is the start picture of a Restyle job, cropped square: the style cards show it. An item is a finished
job: its videos, recipe and a copy of every upload behind it (clip with the people found in it, photos with
their words), so anyone with a link can watch it and start from it (POST /api/gallery/<id>/recreate). Items
are listed in the spec's order. The running server lists them at once. Only use jobs made from media that
may be shown publicly (examples/README.md).
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recast import media, styles  # noqa: E402

DATA = Path(os.environ.get("RECAST_DATA", "runs/app")).resolve()
LOOK_SIDE = 480
LOOK_TOP = 0.12  # where the square starts down a tall picture: faces sit in the upper part


def _file(url: str) -> Path:
    return DATA / url.removeprefix("/api/files/")


def add_look(key: str, jid: str, out: Path) -> None:
    refs = sorted((DATA / "jobs" / jid).glob("reference_*.png"), key=lambda f: f.stat().st_mtime)
    if key not in styles.STYLES or not refs:
        raise SystemExit(f"look {key}: no such style, or job {jid} has no start picture")
    img = Image.open(refs[-1]).convert("RGB")
    side = min(img.size)
    top = round(min(img.height - side, img.height * LOOK_TOP)) if img.height > img.width else 0
    left = (img.width - side) // 2
    img.crop((left, top, left + side, top + side)).resize((LOOK_SIDE, LOOK_SIDE), Image.LANCZOS).save(
        out / f"{key}.jpg", quality=88)
    print(f"look {key}: {refs[-1].name}")


def _sha(f: Path) -> str:
    return hashlib.sha256(f.read_bytes()).hexdigest()


def _mark_preset(clip: Path) -> None:
    """An example's clip that is one of the ready-made motions says so, so recreating it picks that motion
    (no consent box: the clip is ours, not the visitor's)."""
    src = next(clip.glob("original.*"), None)
    found = src and next((d.name for d in sorted((DATA / "presets").glob("*")) if (d / "clip.mp4").exists()
                          and _sha(d / "clip.mp4") == _sha(src)), None)
    if found:
        u = json.loads((clip / "upload.json").read_text())
        (clip / "upload.json").write_text(json.dumps({**u, "_preset": found}, indent=1))


def _choices(p: dict, uploads: dict[str, dict]) -> list[dict]:
    def thumb(uid: str | None) -> str | None:
        u = uploads.get(uid or "")
        return f"uploads/{uid}/{Path(u['thumb_url']).name}" if u and u.get("thumb_url") else None
    found = [{"label": "Motion", "thumb": thumb(p["motion"]["upload_id"])}]
    chars = p.get("characters") or []
    for i, c in enumerate(chars):
        found.append({"label": ("Left" if i == 0 else "Right") if len(chars) == 2 else "Character",
                      "thumb": thumb(c.get("upload_id"))})
    outfits = [o for o in p.get("outfits") or [] if o]
    for i, o in enumerate(outfits):
        found.append({"label": "Outfit" if len(outfits) == 1 else ("Left outfit", "Right outfit")[i] if i < 2
                      else f"Outfit {i + 1}", "text": o.get("text"), "thumb": thumb(o.get("upload_id"))})
    if p.get("style"):
        found.append({"label": "Look", "text": styles.get(p["style"]).name})
    place = p.get("place") or {}
    if place.get("mode") == "describe":
        found.append({"label": "Place", "text": place.get("text")})
    elif place.get("upload_id"):
        found.append({"label": "Place", "thumb": thumb(place["upload_id"])})
    return found


def add_item(spec: dict, order: int, out: Path) -> None:
    jdir = DATA / "jobs" / spec["job"]
    j = json.loads((jdir / "job.json").read_text())
    if j.get("state") != "done":
        raise SystemExit(f"item {spec['id']}: job {spec['job']} is {j.get('state')}, not done")
    p, r = j["params"], j["result"]
    d = out / spec["id"]
    if d.exists():
        shutil.rmtree(d)
    (d / "uploads").mkdir(parents=True)
    for name, url in (("after.mp4", r["video_url"]), ("before.mp4", r["source_url"]), ("compare.mp4", r["compare_url"]),
                      ("poster.jpg", r["poster_url"]), ("recipe.json", r["recipe_url"])):
        shutil.copy(_file(url), d / name)
    ids = [p["motion"]["upload_id"], (p.get("place") or {}).get("upload_id"),
           *(c.get("upload_id") for c in p.get("characters") or []),
           *(o.get("upload_id") for o in p.get("outfits") or [] if o)]
    uploads = {}
    for uid in filter(None, ids):
        shutil.copytree(DATA / "uploads" / uid, d / "uploads" / uid, dirs_exist_ok=True)
        uploads[uid] = json.loads((d / "uploads" / uid / "upload.json").read_text())
    _mark_preset(d / "uploads" / p["motion"]["upload_id"])
    layout = (j.get("_work") or {}).get("layout")
    item = {"title": spec["title"], "line": spec.get("line", ""), "order": order,
            "summary": (j.get("preview") or {}).get("prompt_summary", ""),
            "aspect": list(media.delivery_size(layout)) if layout else None,
            "job": spec["job"], "params": p, "choices": _choices(p, uploads)}
    (d / "item.json").write_text(json.dumps(item, indent=1))
    print(f"item {spec['id']}: {spec['job']} ({p['mode']}, {len(uploads)} uploads)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    a = ap.parse_args()
    spec = json.loads(Path(a.spec).read_text())
    looks, items = DATA / "gallery" / "looks", DATA / "gallery" / "items"
    looks.mkdir(parents=True, exist_ok=True)
    items.mkdir(parents=True, exist_ok=True)
    for key, jid in spec.get("looks", {}).items():
        add_look(key, jid, looks)
    for i, it in enumerate(spec.get("items", [])):
        add_item(it, i, items)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
