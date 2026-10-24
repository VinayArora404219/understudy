"""Local backend for the web app: one person, one GPU.

Speaks the API the web app expects (web/src/api/types.ts) on top of the
recast package. Previews (Qwen-Edit) and renders (Animate-2) go through the
Comfy SDK to the comfy-api-proxy named by COMFY_BASE_URL, one at a time, in
the order asked. State is plain files under RECAST_DATA (default runs/app),
so a restart keeps the library and a render that was running reattaches
instead of rendering twice.

This is the self-host server. The hosted judge build (docs/APP_DESIGN.md)
puts sign-in, per-link quotas and a database in front of the same pipeline.

    tools/serve_local.sh        # this server + the web app, wired together
"""

from __future__ import annotations

import json
import logging
import os
import queue
import random
import shutil
import threading
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from recast import composite, crop, describe, graph, keep, media, people, pose, prompts, recipe, scail, styles, vace
from recast import reference as reflib

log = logging.getLogger("recast.server")

DATA = Path(os.environ.get("RECAST_DATA", "runs/app")).resolve()
RENDERS_TOTAL = int(os.environ.get("RECAST_RENDERS", "50"))
FPS = 16
STEPS = 10
SEGMENTS = {5: 1, 10: 2, 15: 3, 20: 4}  # UI length chip -> Animate-2 segments (81 + 80n frames at 16 fps)
FINISH_SHORT_SIDE = {"720p": 720, "1080p": 1080}
CHARGED = {"queued", "rendering", "finishing", "done"}  # failed and cancelled renders cost nothing
ACTIVE_STATES = {"matching", "queued", "rendering", "finishing"}
SWATCH = {"anime": ("#7dd3fc", "#f0abfc"), "toy": ("#f9a8d4", "#fde68a"), "pixel": ("#86efac", "#3b82f6"),
          "watercolor": ("#fde2e4", "#bde0fe"), "comic": ("#fde047", "#ef4444"), "neon": ("#d946ef", "#06b6d4"),
          "wool": ("#fdba74", "#a78bfa"), "paper": ("#fcd34d", "#fb7185"), "lowpoly": ("#5eead4", "#6366f1")}


class UserError(ValueError):
    """A problem the visitor can fix; its message is shown as is."""


# ------------------------------------------------------------------ state

LOCK = threading.RLock()
UPLOADS: dict[str, dict[str, Any]] = {}
JOBS: dict[str, dict[str, Any]] = {}
TASKS: "queue.Queue[tuple[str, str, Any]]" = queue.Queue()
RUNNING: dict[str, Any] = {}  # job id -> the SDK job currently on the GPU for it (for cancel)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(path)


def _job_dir(jid: str) -> Path:
    return DATA / "jobs" / jid


def _url(path: Path) -> str:
    return f"/api/files/{path.relative_to(DATA).as_posix()}"


def _public(record: dict) -> dict:
    """What the browser sees: private bookkeeping keys start with '_'. A job also says its delivered
    shape once its clip is prepared, so every player box is drawn in the video's own aspect."""
    out = {k: v for k, v in record.items() if not k.startswith("_")}
    layout = (record.get("_work") or {}).get("layout")
    if layout:
        out["aspect"] = list(media.delivery_size(layout))
    if "params" in record:
        out["inputs"] = _inputs(record["params"])
    return out


def _inputs(p: dict) -> list[dict]:
    """The job's input assets, as the result page lists them: the clip, then each image by role."""
    found = []
    def add(uid: str | None, label: str) -> None:
        u = UPLOADS.get(uid or "")
        if u:
            found.append({"label": label, "kind": u["kind"], "thumb_url": u["thumb_url"]})
    add((p.get("motion") or {}).get("upload_id"), "Motion")
    chars = p.get("characters") or []
    for i, c in enumerate(chars):
        add(c.get("upload_id"), ("Left" if i == 0 else "Right") if len(chars) == 2 else "Character")
    add((p.get("outfit") or {}).get("upload_id"), "Outfit")
    add((p.get("prop") or {}).get("upload_id"), "Product")
    add((p.get("place") or {}).get("upload_id"), "Place")
    return found


def _update(j: dict, **fields) -> None:
    with LOCK:
        j.update(fields)
        _write_json(_job_dir(j["id"]) / "job.json", j)


def _cancelled(j: dict) -> bool:
    with LOCK:
        return j["state"] == "cancelled"


def _renders_left() -> int:
    with LOCK:
        used = sum(j["cost_renders"] for j in JOBS.values() if j["state"] in CHARGED)
    return max(0, RENDERS_TOTAL - used)


def _load() -> None:
    for sub in ("uploads", "jobs"):
        (DATA / sub).mkdir(parents=True, exist_ok=True)
    for p in (DATA / "uploads").glob("*/upload.json"):
        u = json.loads(p.read_text())
        # people still being found when the server stopped: the page asks again
        u["people"] = {k: v for k, v in (u.get("people") or {}).items() if v.get("state") == "ready"}
        UPLOADS[u["id"]] = u
    for p in (DATA / "jobs").glob("*/job.json"):
        j = json.loads(p.read_text())
        JOBS[j["id"]] = j
        if j["state"] == "matching":  # a preview is cheap; ask again rather than resume
            _update(j, state="failed", error={"message": "The preview was interrupted. Try again.", "refunded": False})
        elif j["state"] in ("queued", "rendering", "finishing"):
            TASKS.put(("render", j["id"], None))  # the stored submission reattaches to the GPU job


# ------------------------------------------------------------------ pipeline

def _named(path: Path, stem: str) -> Path:
    """Content-addressed name, so the GPU side never sees two different files under one name."""
    return path.rename(path.parent / f"{stem}_{recipe.sha256(path)[:12]}{path.suffix}")


def _upload_path(uid: str, kind: str) -> Path:
    """The upload's file: for a video the original, for an image its decoded, metadata-free PNG."""
    u = UPLOADS.get(uid)
    if u is None or u["kind"] != kind:
        raise UserError(f"That {kind} upload is missing. Upload it again.")
    raw = DATA / u["_file"]
    return raw.parent / "image.png" if kind == "image" else raw


def _clip_layout(uid: str, shape: str | None) -> tuple[str, tuple | None]:
    """The delivered shape and the picture inside any letterbox bars, the same for every use of a clip."""
    src = _upload_path(uid, "video")
    up = UPLOADS[uid]
    found = up["_box"] if "_box" in up else media.content_box(src)  # uploads from before bar detection
    box = tuple(found) if found else None
    shape = shape or "auto"
    return (shape if shape in graph.SIZES else media.layout_for(*box[:2]) if box else media.probe(src).layout), box


def _people_key(start: float, layout: str) -> str:
    return f"{float(start):.2f}_{layout}"


def _people_dir(uid: str, key: str) -> Path:
    return DATA / "uploads" / uid / f"people_{key}"


FIND_RETRIES = (5, 20)  # seconds before each automatic second and third look


def find_people(uid: str, arg: tuple) -> None:
    """Everyone in the clip's start frame, one mask each, for the visitor to choose who is recast."""
    from recast import runner

    key, start, layout, box = arg
    u = UPLOADS[uid]
    d = _people_dir(uid, key)
    d.mkdir(parents=True, exist_ok=True)
    entry: dict = {"state": "ready", "people": []}
    for attempt in range(len(FIND_RETRIES) + 1):
        try:  # this runs on the GPU worker thread: nothing here may raise past it
            frame = media.frame_at(_upload_path(uid, "video"), d / "frame.png", layout=layout, start=start, box=box)
            entry["frame_url"] = _url(frame)
            with _comfy() as client:
                gjob = runner.submit_graph(
                    client, lambda: people.build_detect(client.assets.from_file(frame), prefix=f"recast/people_{uid}"),
                    d / "detect_submission.json")
                gjob = runner.follow(gjob)
                files = runner.download(gjob, d / "detected", node_id=people.FINAL_NODE)
            entry["people"] = [{**vars(f), "mask_url": _url(d / f.mask)} for f in people.read(sorted(files), d)]
            entry.pop("error", None)
            break
        except Exception:  # nobody found reads as "we couldn't find anyone", never a stuck spinner
            log.exception("finding people in %s failed (attempt %d)", uid, attempt + 1)
            entry["error"] = "We couldn't look for people in this frame. Try again, or pick another start point."
            if attempt < len(FIND_RETRIES):
                # A short outage (a model folder that briefly didn't answer, the GPU machine restarting) heals by
                # itself: look again with a fresh submission before the visitor sees an error.
                (d / "detect_submission.json").unlink(missing_ok=True)
                time.sleep(FIND_RETRIES[attempt])
    with LOCK:
        u.setdefault("people", {})[key] = entry
        _write_json(DATA / "uploads" / uid / "upload.json", u)


def _prepare(j: dict) -> dict:
    """Trim and normalize the clip and grab its first frame, once per job."""
    work = j.get("_work") or {}
    if work.get("drive"):
        return work
    d, p = _job_dir(j["id"]), j["params"]
    src = _upload_path(p["motion"]["upload_id"], "video")
    info = media.probe(src)
    layout, box = _clip_layout(p["motion"]["upload_id"], p.get("shape"))
    start = float(p["motion"]["start"])
    usable = info.seconds - start
    if usable < media.MIN_SECONDS:
        raise UserError("The start point is too close to the end of the clip. Pick an earlier start.")
    segments = min(SEGMENTS[p["motion"]["length"]], graph.segments_for(round(usable * FPS)))
    seconds = min(usable, graph.frames_for(segments) / FPS)
    tmp = d / "drive.mp4"
    media.normalize(src, tmp, layout=layout, seconds=seconds, start=start, fps=FPS, box=box)
    drive = _named(tmp, "drive")
    frame = _named(media.frame_at(src, d / "frame.png", layout=layout, start=start, box=box), "frame")
    work = {"drive": drive.name, "frame": frame.name, "layout": layout, "segments": segments,
            "seconds": round(seconds, 2), "has_audio": info.has_audio}
    picks = p["motion"].get("picks")
    if picks:  # the chosen performers' start masks, at the size SAM3 tracks the clip in
        src_dir = _people_dir(p["motion"]["upload_id"], _people_key(start, layout))
        found_people = people.load(src_dir)
        dv = media.probe(drive)
        masks = people.write_picks(found_people, picks, src_dir, d, (dv.width, dv.height))
        work["picks"] = [_named(m, f"pick{k}").name for k, m in enumerate(masks)]
        work["others"] = [_named(m, f"other{k}").name for k, m in
                          enumerate(people.write_others(found_people, picks, src_dir, d, (dv.width, dv.height)))]
        work["pick_crop"] = list(people.crop_box(found_people, picks))
        work["people_dir"] = src_dir.relative_to(DATA).as_posix()
        work["pick_masks"] = [f.mask for f in found_people if f.id in picks]
    _update(j, _work=work)
    return work


def _scene(p: dict) -> tuple[str, str]:
    place = p["place"]
    if place["mode"] == "describe":
        return "new", (place.get("text") or "").strip()
    return "keep", ""


def _characters(p: dict) -> list[dict]:
    return p.get("characters") or ([dict(p["character"], keep_outfit=True)] if p.get("character") else [])


def _mode(p: dict) -> str:
    """recast | restyle | swap. Jobs from before modes existed are classified by what they change."""
    if p.get("mode"):
        return p["mode"]
    return "recast" if _characters(p) else "restyle" if p.get("style") else "swap"


def _lower_article(text: str) -> str:
    """"A young woman…" read mid-sentence: "becomes a young woman…"."""
    t = text.strip()
    return t[0].lower() + t[1:] if t.split(" ", 1)[0] in ("A", "An", "The") else t


def _summary(p: dict) -> str:
    parts = []
    chars = [{**c, "text": _lower_article(c["text"])} for c in _characters(p)]
    if p.get("outfit"):
        return f"The performer stays themselves, now wearing {p['outfit']['text'].strip()}; everything else as filmed."
    if p.get("prop"):
        return (f"The performer stays themselves, now holding {p['prop']['text'].strip()}; everything else as filmed.")
    if len(chars) == 2:
        parts.append(f"The performer on the left becomes {chars[0]['text'].strip()} and the one on the right "
                     f"becomes {chars[1]['text'].strip()}")
    elif chars:
        parts.append(f"The performer becomes {chars[0]['text'].strip()}")
    else:
        parts.append("The performers stay themselves" if p.get("performers") == 2 else "The performer stays themselves")
    if p.get("style"):
        parts.append(f"drawn as {styles.get(p['style']).name}")
    mode = p["place"]["mode"]
    parts.append("in the original place" if mode == "keep" else
                 f"in the place you described: {p['place'].get('text', '').strip()}" if mode == "describe" else
                 ("in the place from the left character's photo" if len(chars) == 2 else
                  "in the place from the character's photo") if mode == "character" else "in the place from your image")
    return ", ".join(parts) + "."


def _comfy():
    from comfy_sdk import Comfy
    return Comfy(timeout=120)


def _read_clip(j: dict, work: dict, frame: Path) -> list[describe.Performer]:
    """Who is in the first frame and what each body does; once per job (re-rolls reuse it)."""
    from recast import runner

    if "performers_seen" in work:
        return [describe.Performer(**x) for x in work["performers_seen"]]
    d = _job_dir(j["id"])
    ask = describe.prompt_for(len(work["picks"])) if work.get("picks") else describe.PROMPT
    with _comfy() as client:
        gjob = runner.submit_graph(client, lambda: describe.build(client.assets.from_file(frame), prompt=ask,
                                                                  prefix=f"recast/app_{j['id']}_describe"),
                                   d / "describe_submission.json")
        RUNNING[j["id"]] = gjob
        try:
            gjob = runner.follow(gjob)
        finally:
            RUNNING.pop(j["id"], None)
        files = runner.download(gjob, d / "describe", node_id=describe.FINAL_NODE)
    found = describe.parse(files[0].read_text()) if files else []
    _update(j, _work={**work, "performers_seen": [vars(f) for f in found]})
    return found


def _read_scene(j: dict, work: dict) -> str:
    """Restyle's prompt: who, where and what appears later, read from four moments of the clip; once per job."""
    from recast import runner

    if work.get("scene"):
        return work["scene"]
    d = _job_dir(j["id"])
    sheet = media.moments_sheet(d / work["drive"], d / "moments.png")
    with _comfy() as client:
        gjob = runner.submit_graph(client, lambda: describe.build_role(client.assets.from_file(sheet), "scene",
                                                                       prefix=f"recast/app_{j['id']}_scene"),
                                   d / "scene_submission.json")
        RUNNING[j["id"]] = gjob
        try:
            gjob = runner.follow(gjob)
        finally:
            RUNNING.pop(j["id"], None)
        files = runner.download(gjob, d / "scene", node_id=describe.FINAL_NODE)
    scene = describe.parse_role(files[0].read_text(), "scene") if files else ""
    _update(j, _work={**work, "scene": scene})
    return scene


def _read_lower(j: dict, work: dict) -> str:
    """Swap: what the performer wears below the waist, read from four moments of the clip; once per job."""
    from recast import runner

    if "lower" in work:
        return work["lower"]
    d = _job_dir(j["id"])
    sheet = media.moments_sheet(d / work["drive"], d / "moments.png")
    with _comfy() as client:
        gjob = runner.submit_graph(client, lambda: describe.build_role(client.assets.from_file(sheet), "lower",
                                                                       prefix=f"recast/app_{j['id']}_lower"),
                                   d / "lower_submission.json")
        RUNNING[j["id"]] = gjob
        try:
            gjob = runner.follow(gjob)
        finally:
            RUNNING.pop(j["id"], None)
        files = runner.download(gjob, d / "lower", node_id=describe.FINAL_NODE)
    lower = describe.parse_role(files[0].read_text(), "lower") if files else ""
    _update(j, _work={**work, "lower": lower})
    return lower


def _chosen_frame(work: dict, d: Path, frame: Path) -> Path:
    """The start frame with the other people greyed out, cropped around the chosen ones, so the reader's poses
    are theirs. Measured on the test clips: a crop alone described the man standing next to the one chosen;
    greying out everything but the chosen also hid what they touch (a dog's "hands on the keyboard" became
    "hands near the ground"), so only the others go, and the room and props stay."""
    if not work.get("picks"):
        return frame
    from PIL import Image, ImageFilter

    img = Image.open(frame).convert("RGB")
    W, H = img.size
    chosen = Image.new("L", (W, H), 0)
    for name in work["picks"]:
        chosen.paste(255, mask=Image.open(d / name).convert("L").resize((W, H), Image.NEAREST))
    chosen = chosen.filter(ImageFilter.MaxFilter(9))  # a little room, so hands and hair edges stay
    others = Image.new("L", (W, H), 0)
    src = DATA / work["people_dir"] if work.get("people_dir") else None
    for f in people.load(src) if src and src.exists() else []:
        if f.mask not in work.get("pick_masks", []):
            others.paste(255, mask=Image.open(src / f.mask).convert("L").resize((W, H), Image.NEAREST))
    hide = Image.composite(Image.new("L", (W, H), 0), others, chosen)  # never grey out the chosen ones
    shown = Image.composite(Image.new("RGB", (W, H), (128, 128, 128)), img, hide)
    x, y, w, h = work["pick_crop"]
    out = d / "frame_chosen.png"
    shown.crop((round(x * W), round(y * H), round((x + w) * W), round((y + h) * H))).save(out)
    return out


PICKED = (200, 245, 96)  # the page's accent colour


def _picked_frame(work: dict, d: Path, frame: Path) -> Path:
    """The start frame as the preview shows it: the chosen performers outlined, everything else dimmed, so the
    visitor checks who is replaced next to who replaces them."""
    if not work.get("picks"):
        return frame
    from PIL import Image, ImageChops, ImageFilter

    img = Image.open(frame).convert("RGB")
    W, H = img.size
    chosen = Image.new("L", (W, H), 0)
    for name in work["picks"]:
        chosen.paste(255, mask=Image.open(d / name).convert("L").resize((W, H), Image.NEAREST))
    edge = ImageChops.subtract(chosen.filter(ImageFilter.MaxFilter(5)), chosen.filter(ImageFilter.MinFilter(3)))
    out = Image.composite(img, Image.eval(img, lambda v: v * 2 // 5), chosen)
    out.paste(PICKED, mask=edge)
    dst = d / "frame_picked.png"
    out.save(dst)
    return _named(dst, "frame_picked")


def _cut_out(uid: str, photo: Path, dst: Path, colour: int) -> Path | None:
    """The character alone from their photo (people.cut_out); the people found are kept per upload."""
    from recast import runner

    src = _upload_path(uid, "image").parent / "cutout_people"
    try:
        if not (src / "people.json").exists():
            with _comfy() as client:
                gjob = runner.submit_graph(
                    client, lambda: people.build_detect(client.assets.from_file(photo), prefix=f"recast/cut_{uid}"),
                    src.parent / "cutout_submission.json")
                files = runner.download(runner.follow(gjob), src / "detected", node_id=people.FINAL_NODE)
            people.read(sorted(files), src)
        return people.cut_out(photo, people.load(src), src, dst, colour)
    except Exception:  # the whole photo still works; the cut-out only keeps its other things out
        log.exception("cutting the character out of %s failed", uid)
        return None


def _seen(found: list[describe.Performer]) -> str:
    where = {"left": " on the left", "right": " on the right", "center": ""}
    return "We read your clip as: " + "; ".join(
        f"a {f.what or f.kind}{where[f.side]}" + (f" ({f.pose})" if f.pose else "") for f in found) + "."


def run_preview(j: dict, seed: int) -> None:
    from recast import runner

    first = j["params"]
    if _mode(first) == "swap" and not first["motion"].get("picks") and not (j.get("_work") or {}).get("drive"):
        # Made before the start frame's people were found (a place swap needs no picture, so the visitor can be
        # quick). GPU tasks run in order, so the search queued at upload has finished by now.
        again = json.loads(json.dumps(first))
        _swap_picks(again, again.get("performers", 1))
        if again["motion"].get("picks"):
            _update(j, params=again)
    work = _prepare(j)
    d, p = _job_dir(j["id"]), j["params"]
    frame = d / work["frame"]
    chars = _characters(p)
    notes: list[str] = []
    poses, shots, bodies, side = ["", ""], ["", ""], ["", ""], ""
    found: list[describe.Performer] = []
    seen = ""
    item = p.get("outfit") or p.get("prop")
    hand = other_hand = ""
    swap = _mode(p) == "swap"
    if chars or item or swap:  # a character, an item or a swap needs the clip read in words; a restyle keeps it
        try:
            found = _read_clip(j, work, _chosen_frame(work, d, frame))
        except Exception:  # the description helps; it must never block a preview
            log.exception("describing %s failed", j["id"])
            found = []
        # a place swap takes anyone; an outfit needs one person, and chosen performers are already known
        problem = None if work.get("picks") or (swap and not item) else describe.mismatch(
            found, performers=p.get("performers", 1), subject=p["subject"])
        if problem:
            raise UserError(problem)
        if work.get("picks") and found:  # chosen in the frame, so nobody said person or animal: the reader does
            kind = "animal" if all(f.kind == "animal" for f in found) else "person"
            if kind != p["subject"]:
                p = {**p, "subject": kind}
                _update(j, params=p)
        if len(found) == max(1, len(chars)) and not (swap and item):  # an outfit's edit keeps the clip's framing:
            # pose words for a selfie start ("walks forward, hands by sides") zoomed it out and drew trousers
            poses = [f.pose for f in found] + [""]
            shots = [f.shot for f in found] + [""]
            bodies = [f.body or f.pose for f in found] + [""]
            side = found[0].side

        seen = _seen(found) if found else ""
    if p.get("prop"):  # which hand is free, by picture side, from keypoints (never from words: they mirror)
        arms = pose.read_arms(frame)
        if arms and arms.free:
            hand, other_hand = arms.free, arms.other()
        else:
            notes.append("We couldn't tell which hand is free in your first frame, so the product may sit in "
                         "either hand. If it looks wrong, try another version.")
    # Recast runs on SCAIL-2 (recast/scail.py): in the clip's place it replaces the performers in the clip
    # itself; anywhere else it animates a start picture whose room is that place.
    engine: dict = {}
    if _mode(p) == "recast":
        replace = p["place"]["mode"] == "keep"
        engine = {"engine": "scail", "replace": replace, "people": len(chars),
                  "track": scail.track_words([f.find or f.what for f in found], p["subject"]),
                  # In the clip's place the clip itself drives every frame, and the reader's first-frame pose
                  # cost accessories: with it, sunglasses put on mid-clip were missing; without, they came
                  # back (same seed, private regression clip). Another place is posed by the words, so keeps them.
                  "poses": [] if replace else bodies[:len(chars)]}
    elif swap:
        # The performer is recast as themselves (SCAIL-2, like Recast), so the clip still drives every frame:
        # on Animate-2, animating one edited still, sunglasses put on later never appeared, a car that drives
        # off stayed parked, and the jeans changed with the shirt (private regression clip). In the clip's
        # place for an outfit: their edited still is the character. A new place animates that still.
        # The first frame often hides the legs (a selfie start), so the render invented trousers: black with a
        # new top, red in a new place. What they wear below the waist is read over four moments of the clip.
        try:
            lower = _read_lower(j, j["_work"]) if len(found) <= 1 else ""
        except Exception:  # the words help; they must never block a preview
            log.exception("reading the lower clothes of %s failed", j["id"])
            lower = ""
        work = j["_work"]
        with_lower = f", with {lower}" if lower else ""
        who = [f.what or f.kind for f in found][:2] or ["the person"]
        if work.get("picks"):  # one description per chosen person, so the prompt matches who is tracked
            who = (who + ["the person"] * 2)[:len(work["picks"])]
        if p.get("outfit"):
            engine = {"engine": "scail", "replace": True, "people": 1, "poses": [],
                      "track": scail.track_words([f.find or f.what for f in found][:1], "person"),
                      "texts": [f"the same person as in the video, now wearing {p['outfit']['text'].strip()}"
                                f"{with_lower}"]}
        else:
            engine = {"engine": "scail", "replace": False, "people": len(work.get("picks") or who),
                      "poses": bodies[:len(who)],
                      "track": scail.track_words([f.find or f.what for f in found][:2], p["subject"]),
                      "texts": [who[0] + with_lower, *who[1:]]}
    elif _mode(p) == "restyle":  # video to video: every frame's depth, so later objects and motion survive
        mine = j.get("scene") or {}
        if mine.get("edited"):  # the visitor's own words win over a re-read
            scene = mine["text"]
        else:
            _update(j, scene={"state": "reading", "text": ""})  # shown as progress; not editable yet
            try:
                scene = _read_scene(j, work)
            except Exception:  # the line helps; without it the look alone still carries the render
                log.exception("describing the scene of %s failed", j["id"])
                scene = ""
            _update(j, scene={"state": "ready", "text": scene, "edited": False})
        work = j["_work"]
        engine = {"engine": "vace", "scene": scene or "the scene in the video"}
    kind = "still"
    changes = bool(chars or item or p.get("style") or p["place"]["mode"] != "keep")
    if engine.get("replace") and chars:  # nothing to generate: who replaces whom, cut out of their photos
        colour = media.edge_colour(frame)  # the room's own colour, so a leak of the backdrop blends in
        photos = []
        for i, c in enumerate(chars):
            whole = media.clean_image(_upload_path(c["upload_id"], "image"), d / f"cast_{i}.png")
            photos.append(_cut_out(c["upload_id"], whole, d / f"cast_{i}_cut.png", colour) or whole)
        picks = p["motion"].get("picks") or []
        found = people.load(DATA / work["people_dir"]) if picks and work.get("people_dir") else []
        boxes = [f.box for f in found if f.id in picks]
        if len(boxes) == len(photos):  # each character where their performer stands (scail.placed_sheet)
            dv = media.probe(d / work["drive"])
            ref = scail.placed_sheet(photos, boxes, (dv.width, dv.height), d / "reference.png", colour)
        else:
            ref = scail.reference_sheet(photos, d / "reference.png")
        kind = "cast"
    elif engine and p["place"]["mode"] == "character" and len(chars) == 1:  # their photo, as it is, is the start
        src = media.clean_image(_upload_path(chars[0]["upload_id"], "image"), d / "character_full.png")
        ref = crop.to_shape(src, d / "reference.png", work["layout"])
    elif not changes:  # nothing to redraw: the performer is their own reference
        ref = media.fit_image(frame, d / "reference.png", layout=work["layout"], mode="crop")
    else:
        # Whose place the result is in decides image1 (reference.BASES). A recast into another place
        # starts from that place's own picture; the clip frame then only lends its layout, as words.
        mode = p["place"]["mode"]
        base = "frame" if not chars else {"character": "character", "image": "location"}.get(mode, "frame")
        images: dict[str, Path] = {}
        for slot, c in zip(("character", "character2"), chars):
            src = _upload_path(c["upload_id"], "image")
            img = src
            if slot == base:  # the whole photo is the scene: shape it like the clip, never crop to the head
                images[slot] = _named(crop.to_shape(media.clean_image(src, d / f"{slot}_full.png"),
                                                    d / f"{slot}.png", work["layout"]), slot)
                continue
            if not c.get("keep_outfit"):
                img = crop.head_and_shoulders(src, d / f"{slot}_head.png") or src
                if img == src:
                    notes.append("We couldn't find a face in "
                                 + ("the character image" if len(chars) == 1 else f"the {'left' if slot == 'character' else 'right'} character image")
                                 + ", so all of it was used. If the preview copies that picture's pose, "
                                   "try a head-and-shoulders picture.")
            images[slot] = _named(media.clean_image(img, d / f"{slot}.png"), slot)
        for slot in ("outfit", "prop"):
            if p.get(slot):
                src = _upload_path(p[slot]["upload_id"], "image")
                name = "product" if slot == "prop" else slot
                images[name] = _named(media.clean_image(src, d / f"{name}.png"), name)
        if mode == "image":
            src = media.clean_image(_upload_path(p["place"]["upload_id"], "image"), d / "location_full.png")
            loc = crop.to_shape(src, d / "location.png", work["layout"]) if base == "location" else src
            images["location"] = _named(loc, "location")
        scene, background = _scene(p)
        # cut-outs sit on the colour of the picture whose place the result is in, so a leak blends into it
        room = images.get("location") or (images[base] if base != "frame" else frame)
        mp = reflib.MatchParams(
            frame=frame.name if base == "frame" else None, base=base,
            character_text=chars[0]["text"] if chars else "",
            character2_text=chars[1]["text"] if len(chars) > 1 else "",
            # in another place, the bodies without the clip's objects (the place keeps its own things)
            pose=(poses if base == "frame" else bodies)[0], pose2=(poses if base == "frame" else bodies)[1],
            side=side if base != "frame" else "", shot=shots[0] if base != "frame" else "",
            shot2=shots[1] if base != "frame" else "",
            cutout_colour=media.edge_colour(room) if mode in ("keep", "image", "character") else reflib.CUTOUT_GREY,
            outfit_text=(p.get("outfit") or {}).get("text", ""), product_text=(p.get("prop") or {}).get("text", ""),
            product_hand=hand if p.get("prop") else "", other_hand=other_hand if p.get("prop") and hand else "",
            style=p.get("style") or "", scene=scene, background=background,
            subject=p["subject"] if base == "frame" else reflib.cast_word([c["text"] for c in chars]),
            quality="fast", seed=seed, prefix=f"recast/app_{j['id']}_ref",
            **{k: v.name for k, v in images.items()})
        try:
            mp.validate()
        except reflib.ReferenceError as e:
            raise UserError(str(e).capitalize() + ".") from e
        g = reflib.build(mp)
        # keyed by what is asked, not just the seed: a changed prompt must never reattach to an old job
        key = f"{seed}_{recipe.graph_sha(g)[:10]}"
        (d / f"reference_graph_{key}.json").write_text(json.dumps(g, indent=1))
        with _comfy() as client:
            def make():
                if base == "frame":
                    mp.frame = client.assets.from_file(frame)
                for k, v in images.items():
                    setattr(mp, k, client.assets.from_file(v))
                return reflib.build(mp)
            gjob = runner.submit_graph(client, make, d / f"reference_submission_{key}.json")
            RUNNING[j["id"]] = gjob
            try:
                gjob = runner.follow(gjob)
            finally:
                RUNNING.pop(j["id"], None)
            files = runner.download(gjob, d / f"reference_render_{key}", node_id=reflib.FINAL_NODE)
        if not files:
            raise RuntimeError("the preview job finished without an image")
        ref = media.fit_image(files[0], d / "reference.png", layout=work["layout"], mode="crop")
        engine["edited"] = True
    ref = _named(ref, "reference")
    if _cancelled(j):
        return
    mine = j.get("scene") or {}
    if engine.get("engine") == "vace" and mine.get("edited"):  # edited while the still was being drawn
        engine["scene"] = mine["text"]
    shown = _picked_frame(work, d, frame)
    _update(j, state="awaiting_approval", error=None,
            _work={**work, "reference": ref.name, "edited": False, **engine},
            preview={"frame_url": _url(shown), "reference_url": _url(ref), "seed": seed, "kind": kind,
                     "prompt_summary": _summary(p), "notes": notes, "seen": seen})


def run_render(j: dict, _arg: Any = None) -> None:
    work, d, p = j["_work"], _job_dir(j["id"]), j["params"]
    ref, drive = d / work["reference"], d / work["drive"]
    scene, background = _scene(p)
    chars = _characters(p)
    two = p.get("performers") == 2
    if work.get("engine") == "scail":
        place = background if scene == "new" else ""
        rp = scail.ScailParams(
            drive=drive.name, reference=ref.name, layout=work["layout"], chunks=work["segments"],
            prompt=scail.prompt(work.get("texts") or [c["text"] for c in chars], work.get("poses") or [],
                                replace=work["replace"], place=place),
            track=work["track"], people=work["people"], replace=work["replace"], picks=work.get("picks"),
            keep_points=[[list(pt) for pt in keep.inside_points(d / name)] for name in work["picks"]]
            if work.get("picks") and work["replace"] else None,
            others=list(work.get("others") or []) if work.get("picks") and work["replace"] else None,
            seed=p.get("seed") or graph.DEFAULT_SEED, prefix=f"recast/app_{j['id']}")
        engine, steps, models = scail, scail.STEPS, scail.MODELS
    elif work.get("engine") == "vace":
        rp = vace.VaceParams(drive=drive.name, reference=ref.name, layout=work["layout"], chunks=work["segments"],
                             prompt=vace.prompt(work["scene"], p["style"]),
                             seed=p.get("seed") or graph.DEFAULT_SEED, prefix=f"recast/app_{j['id']}")
        engine, steps, models = vace, vace.STEPS, vace.MODELS
    else:
        rp = _animate2_params(j, work, p, ref, drive, chars, two, scene, background)
        engine, steps, models = graph, STEPS, recipe.MODELS
    try:
        rp.validate()
    except (scail.ScailError, vace.VaceError, graph.ParamError) as e:
        raise UserError(f"This job can't be rendered: {e}.") from e
    g = engine.build(rp)
    (d / "graph.json").write_text(json.dumps(g, indent=1, ensure_ascii=False))
    _render_and_finish(j, work, d, p, rp, g, ref, drive, engine, steps, models)


def _animate2_params(j, work, p, ref, drive, chars, two, scene, background) -> graph.RecastParams:
    return graph.RecastParams(
        reference=ref.name, drive=drive.name,
        appearance=prompts.appearance(subject=p["subject"], character_text=chars[0]["text"] if chars else "",
                                      character2_text=chars[1]["text"] if len(chars) > 1 else "", two=two,
                                      style=p.get("style") or "", scene=scene, background=background,
                                      has_location=p["place"]["mode"] in ("image", "character"),
                                      wearing=(p.get("outfit") or {}).get("text", ""),
                                      holding=(p.get("prop") or {}).get("text", "")),
        motion=prompts.motion(subject=p["subject"], two=two), layout=work["layout"], segments=work["segments"],
        fps=FPS, seed=p.get("seed") or graph.DEFAULT_SEED, steps=STEPS, prefix=f"recast/app_{j['id']}")


def _render_and_finish(j, work, d, p, rp, g, ref, drive, engine, steps, models) -> None:
    """Submit, report progress (steps restart at each segment or chunk), deliver, write the recipe."""
    from recast import runner

    total = work["segments"] * steps
    clock = {"seg": 1, "last": 0, "first": None, "first_done": 0}

    def on_event(ev: dict) -> None:
        if _cancelled(j):
            return
        if ev["kind"] == "status":
            if ev["status"] == "queued":
                _update(j, state="queued", progress={"stage": "waiting_for_gpu",
                                                     "queue_position": ev.get("queue_position"),
                                                     "eta_seconds": work["segments"] * 520})
            elif ev["status"] == "running" and clock["first"] is None:
                _update(j, state="rendering", progress={"stage": "loading_models",
                                                        "eta_seconds": work["segments"] * 480})
        elif ev["kind"] == "progress" and ev.get("steps") == steps and ev.get("step"):
            step = int(ev["step"])
            if step < clock["last"]:
                clock["seg"] = min(work["segments"], clock["seg"] + 1)
            clock["last"] = step
            done = (clock["seg"] - 1) * steps + step
            now = time.time()
            if clock["first"] is None:
                clock["first"], clock["first_done"] = now, done
            rate = (now - clock["first"]) / max(1, done - clock["first_done"]) if done > clock["first_done"] else 45.0
            _update(j, state="rendering", progress={
                "stage": "rendering", "segment": clock["seg"], "segments": work["segments"],
                "step": step, "steps": steps, "eta_seconds": round(rate * (total - done) + 25)})

    t0 = time.time()
    with _comfy() as client:
        def make():  # uploaded as SDK assets
            rp.reference, rp.drive = client.assets.from_file(ref), client.assets.from_file(drive)
            if getattr(rp, "picks", None):
                rp.picks = [client.assets.from_file(d / name) for name in work["picks"]]
            if getattr(rp, "others", None):
                rp.others = [client.assets.from_file(d / name) for name in work["others"]]
            return engine.build(rp)
        gjob = runner.submit_graph(client, make, d / f"render_submission_{recipe.graph_sha(g)[:10]}.json")
        RUNNING[j["id"]] = gjob
        try:
            gjob = runner.follow(gjob, on_event)
        finally:
            RUNNING.pop(j["id"], None)
        if _cancelled(j):
            return
        _update(j, state="finishing", progress={"stage": "finishing", "eta_seconds": 20})
        files = runner.download(gjob, d / "render", node_id=engine.FINAL_NODE)
        kept = None
        if files and getattr(rp, "keep_points", None):
            kept = [runner.download(gjob, d / "render", node_id=node)[0]
                    for node in (scail.KEEP_OTHERS_NODE, scail.KEEP_NEW_NODE, scail.KEEP_MASK_NODE)]
    if not files:
        raise RuntimeError("the render finished without a video")
    if kept:  # everyone not recast, as filmed (recast/keep.py)
        files = [composite.keep_others(drive, files[0], *kept, d / "render_kept.mp4")]

    native = graph.SIZES[work["layout"]]
    if p["audio"] == "mute":
        final = media.without_audio(files[0], d / "recast_native.mp4")
    else:
        final = media.with_source_audio(files[0], drive, d / "recast_native.mp4")
    short = FINISH_SHORT_SIDE.get(p["finish"])  # None: native pixels, cropped to the exact shape
    final = media.deliver(final, d / "recast.mp4", layout=work["layout"], short_side=short)
    w, h = media.delivery_size(work["layout"], short)
    delivered = f"{w}×{h}" + (" (upscaled)" if short else "")
    compare = media.side_by_side(drive, final, d / "compare.mp4", vertical=work["layout"].startswith("landscape"))
    seconds = round(time.time() - t0, 1)
    rp.reference, rp.drive = ref.name, drive.name  # SDK assets hold a live client: the recipe names files
    picks = work.get("picks") or []
    if getattr(rp, "picks", None):
        rp.picks = list(picks)
    if getattr(rp, "others", None):
        rp.others = list(work["others"])
    recipe.write(d / "recipe.json", params=rp, g=g,
                 inputs={"reference": ref, "drive": drive, **{f"pick{k}": d / n for k, n in enumerate(picks)}},
                 outputs={"recast": final, "compare": compare}, job_id=gjob.id, seconds=seconds, models=models)
    if _cancelled(j):
        return
    _update(j, state="done", progress=None, result={
        "video_url": _url(final), "compare_url": _url(compare), "share_url": _url(compare),
        "recipe_url": _url(d / "recipe.json"), "source_url": _url(drive), "render_seconds": seconds,
        "native_resolution": f"{native[0]}×{native[1]} @ {FPS} fps", "delivered_resolution": delivered,
        "models": _model_names(engine, work)})


def _model_names(engine, work: dict) -> str:
    """The models that made this video, for the result page (recipe.json has the files and licenses)."""
    video = {scail: "SCAIL-2 (Wan2.1 14B), SAM 3.1", vace: "Wan2.1 VACE 14B, Depth Anything V2"}.get(engine,
                                                                                                  "Wan Animate-2")
    return video + (", Qwen-Image-Edit-2511" if work.get("edited") else "")


def _friendly(e: Exception) -> str:
    from recast.runner import RenderFailed

    if isinstance(e, UserError):
        return str(e)
    if isinstance(e, RenderFailed):
        return f"The GPU job failed: {e.reason}"
    if isinstance(e, (media.MediaError, graph.ParamError)):
        return f"The clip could not be prepared: {e}"
    if isinstance(e, (ConnectionError, OSError)) or "connect" in type(e).__name__.lower():
        return "Can't reach the GPU. Check that the tunnel and comfy-api-proxy are running, then try again."
    return f"Something went wrong ({type(e).__name__}). Details are in the job's error.log."


def describe_upload(uid: str, role: str) -> None:
    """Write the words for one uploaded image in its role (a character, an outfit, a product)."""
    from recast import runner

    u = UPLOADS[uid]
    img = _upload_path(uid, "image")
    d = img.parent
    try:
        with _comfy() as client:
            gjob = runner.submit_graph(
                client, lambda: describe.build_role(client.assets.from_file(img), role, prefix=f"recast/describe_{uid}"),
                d / f"describe_{role}_submission.json")
            gjob = runner.follow(gjob)
            files = runner.download(gjob, d / f"describe_{role}", node_id=describe.FINAL_NODE)
        text = describe.parse_role(files[0].read_text(), role) if files else ""
    except Exception:  # a missing description only means the visitor types one
        log.exception("describing upload %s as %s failed", uid, role)
        text = ""
    with LOCK:
        u.setdefault("descriptions", {})[role] = text
        u["describing"] = [r for r in u.get("describing", []) if r != role]
        _write_json(d / "upload.json", u)


def _worker() -> None:
    while True:
        kind, jid, arg = TASKS.get()
        if kind in ("describe_upload", "find_people"):
            (describe_upload if kind == "describe_upload" else find_people)(jid, arg)
            continue
        j = JOBS.get(jid)
        if j is None or _cancelled(j):
            continue
        try:
            (run_preview if kind == "preview" else run_render)(j, arg)
        except Exception as e:  # one job's failure never stops the queue
            (_job_dir(jid) / "error.log").write_text(traceback.format_exc())
            log.exception("%s %s failed", kind, jid)
            if not _cancelled(j):
                _update(j, state="failed", progress=None,
                        error={"message": _friendly(e), "refunded": kind == "render"})


# ------------------------------------------------------------------ http

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    _load()
    threading.Thread(target=_worker, name="gpu-worker", daemon=True).start()
    yield


app = FastAPI(title="Performance Recast (local)", docs_url=None, redoc_url=None, lifespan=_lifespan)


@app.exception_handler(UserError)
async def _user_error(_req, e: UserError):
    return JSONResponse({"message": str(e)}, status_code=400)


@app.exception_handler(HTTPException)
async def _http_error(_req, e: HTTPException):
    return JSONResponse({"message": str(e.detail)}, status_code=e.status_code)


@app.get("/api/session")
def session() -> dict:
    return {"kind": "user", "name": "Local GPU", "renders_left": _renders_left(), "renders_total": RENDERS_TOTAL}


@app.get("/api/presets")
def presets() -> list:
    return []  # ready-made motions ship once cleared clips exist


@app.get("/api/styles")
def style_list() -> list:
    return [{"key": s.key, "name": s.name, "swatch": list(SWATCH.get(s.key, ("#94a3b8", "#475569")))}
            for s in styles.STYLES.values()]


@app.get("/api/gallery")
def gallery() -> list:
    return []


@app.post("/api/uploads")
async def upload(file: UploadFile = File(...), kind: str = Form(...)) -> dict:
    if kind not in ("video", "image"):
        raise UserError("Unknown upload kind.")
    uid = _new_id("up")
    d = DATA / "uploads" / uid
    d.mkdir(parents=True)
    suffix = "".join(ch for ch in Path(file.filename or "").suffix.lower() if ch.isalnum() or ch == ".")[:6]
    raw = d / f"original{suffix}"
    size = 0
    with raw.open("wb") as out:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > media.MAX_UPLOAD_BYTES:
                out.close()
                shutil.rmtree(d)
                raise UserError(f"That file is over {media.MAX_UPLOAD_BYTES // 2**20} MB.")
            out.write(chunk)
    u = {"id": uid, "kind": kind, "_file": raw.relative_to(DATA).as_posix()}
    try:
        u.update(_describe_video(raw, d) if kind == "video" else _describe_image(raw, d))
    except media.MediaError as e:
        shutil.rmtree(d)
        raise UserError(f"This file can't be used: {e}.") from e
    _write_json(d / "upload.json", u)
    with LOCK:
        UPLOADS[uid] = u
    return _public(u)


def _describe_video(raw: Path, d: Path) -> dict:
    info = media.validate_upload(raw)
    box = media.content_box(raw)
    w, h = box[:2] if box else (info.width, info.height)
    layout = media.layout_for(w, h)
    thumb = media.frame_at(raw, d / "thumb.jpg", layout=layout, long_side=640, box=box)
    checks = [
        {"id": "length", "level": "ok" if info.seconds >= 4 else "warn",
         "message": f"{info.seconds:.1f} s" + (", long enough" if info.seconds >= 4 else ", short"),
         **({} if info.seconds >= 4 else {"hint": "4 s or more gives the motion room to read."})},
        {"id": "size", "level": "ok", "message": f"{w}×{h}, {layout}"
         + (" (black bars removed)" if box else "")},
        {"id": "audio", "level": "ok", "message": "Sound included" if info.has_audio else "No sound; the result will be silent"},
        {"id": "performer", "level": "ok", "message": "Performer and camera checks are not automatic yet",
         "hint": "Best results: one person, whole body or waist-up, camera on a stand."},
    ]
    return {"url": _url(raw), "thumb_url": _url(thumb), "checks": checks, "_box": list(box) if box else None,
            "info": {"width": w, "height": h, "seconds": round(info.seconds, 2),
                     "fps": round(info.fps, 2), "has_audio": info.has_audio}}


def _describe_image(raw: Path, d: Path) -> dict:
    img = media.clean_image(raw, d / "image.png")
    info = media.probe(img)
    short = min(info.width, info.height)
    checks = [{"id": "size", "level": "block" if short < 256 else "warn" if short < 512 else "ok",
               "message": f"{info.width}×{info.height}",
               **({"hint": "Use an image at least 512 px on its short side."} if short < 512 else {})}]
    return {"url": _url(img), "thumb_url": _url(img), "checks": checks,
            "info": {"width": info.width, "height": info.height}}


@app.get("/api/uploads/{uid}")
def get_upload(uid: str) -> dict:
    u = UPLOADS.get(uid)
    if u is None:
        raise HTTPException(404, "That upload is gone. Upload it again.")
    return _public(u)


@app.post("/api/uploads/{uid}/describe")
def describe_upload_request(uid: str, body: dict) -> dict:
    """Queue the words for an image in a role; the page polls GET /api/uploads/{uid} for them."""
    role = (body or {}).get("role")
    if role not in describe.ROLE_PROMPTS:
        raise UserError("Unknown image role.")
    u = UPLOADS.get(uid)
    if u is None or u["kind"] != "image":
        raise HTTPException(404, "That image is gone. Upload it again.")
    with LOCK:
        if role not in u.get("descriptions", {}) and role not in u.get("describing", []):
            u.setdefault("describing", []).append(role)
            TASKS.put(("describe_upload", uid, role))
    return _public(u)


@app.post("/api/uploads/{uid}/people")
def find_people_request(uid: str, body: dict | None = None) -> dict:
    """Queue finding everyone in the start frame; the page polls GET /api/uploads/{uid} for people[key]."""
    body = body or {}
    u = UPLOADS.get(uid)
    if u is None or u["kind"] != "video":
        raise HTTPException(404, "That clip is gone. Upload it again.")
    start = float(body.get("start") or 0)
    if start < 0 or (u.get("info") or {}).get("seconds", 1e9) <= start:
        raise UserError("That start point is outside the clip.")
    if (body.get("shape") or "auto") not in ("auto", *graph.SIZES):
        raise UserError("Unknown shape.")
    layout, box = _clip_layout(uid, body.get("shape"))
    key = _people_key(start, layout)
    with LOCK:
        found = u.setdefault("people", {})
        if key not in found or (body.get("retry") and found[key].get("state") == "ready"
                                and (found[key].get("error") or not found[key].get("people"))):
            found[key] = {"state": "finding"}
            TASKS.put(("find_people", uid, (key, start, layout, box)))
    return {"key": key, **_public(u)}


@app.get("/api/files/{path:path}")
def files(path: str):
    p = (DATA / path).resolve()
    if DATA not in p.parents or not p.is_file() or p.suffix == ".json" and p.name != "recipe.json":
        raise HTTPException(404, "Not found.")
    return FileResponse(p)


def _title(p: dict) -> str:
    chars = _characters(p)
    what = ("Duo recast" if len(chars) == 2 else "Recast" if chars
            else styles.get(p["style"]).name if p.get("style")
            else "Outfit swap" if p.get("outfit") else "Product swap" if p.get("prop") else "Place swap")
    return f"{what} · {p['motion']['length']} s"


def _check_mode(params: dict, chars: list, place: dict, performers: int) -> None:
    """Each mode changes its own thing (see web/src/pages/CreatePage.tsx: MODES)."""
    mode = params.get("mode")
    items = [k for k in ("outfit", "prop") if params.get(k)]
    if mode == "recast":
        if not chars:
            raise UserError("Recast needs a character image.")
        if items:
            raise UserError("Outfits and products are swapped on the performer: use Swap.")
    elif mode == "restyle":
        if not params.get("style"):
            raise UserError("Pick a look.")
        if chars or items or place["mode"] != "keep":
            raise UserError("Restyle changes only the look. Use Recast or Swap for the rest.")
    elif mode == "swap":
        if params.get("prop"):  # measured: a held product showed only while its hand stayed in view
            raise UserError("Swapping a product in hand isn't offered: swap the outfit or the place.")
        if chars or params.get("style"):
            raise UserError("Swap keeps the performer and the look; it changes one thing.")
        changes = len(items) + (place["mode"] != "keep")
        if changes != 1:
            raise UserError("Swap one thing at a time: the outfit or the place.")
        if place["mode"] == "character":
            raise UserError("“Where my character is” belongs to Recast.")
        if items and (performers != 1 or params.get("subject") != "person"):
            raise UserError("An outfit swap needs one person in the clip.")
        for k in items:
            _upload_path((params[k] or {}).get("upload_id", ""), "image")
            if len((params[k].get("text") or "").strip()) < 3:
                raise UserError(f"Say what the {'product' if k == 'prop' else 'outfit'} is in a few words.")
    else:
        raise UserError("Pick Recast, Restyle or Swap.")


CLEAR = 0.25  # of the biggest person's area: smaller is a passer-by or a ball, never chosen for the visitor


def _swap_picks(params: dict, performers: int) -> int:
    """Swap chooses its performer itself, from the people found in the start frame: the biggest one for an
    outfit, everyone clearly in view (up to two) for a place. Words picked the wrong person: the clip reader
    named a pedestrian in red far behind the performer, and those words also chose whom to track. Returns the
    performer count; without anyone found yet, the job goes on by words as before."""
    m = params["motion"]
    if params.get("mode") != "swap" or not m.get("upload_id") or m.get("upload_id") not in UPLOADS:
        return performers
    layout, _ = _clip_layout(m["upload_id"], params.get("shape"))
    entry = (UPLOADS[m["upload_id"]].get("people") or {}).get(_people_key(m.get("start", 0), layout)) or {}
    found = entry.get("people") or [] if entry.get("state") == "ready" else []
    if not found:
        m.pop("picks", None)
        return performers
    biggest = max(found, key=lambda x: x["area"])
    clear = [x for x in found if x["area"] >= CLEAR * biggest["area"]]
    chosen = [biggest] if params.get("outfit") or len(clear) > 2 else clear
    m["picks"] = sorted(x["id"] for x in chosen)
    params["performers"] = len(chosen)
    return len(chosen)


def _check_picks(params: dict, performers: int) -> None:
    """Who in the clip is recast or swapped: chosen in the start frame. Restyle redraws everyone and drops it."""
    m = params["motion"]
    if m.get("picks") is None:
        return
    if _mode(params) not in ("recast", "swap"):
        m.pop("picks")
        return
    picks = m["picks"]
    if (not isinstance(picks, list) or len(picks) != performers or len(set(picks)) != len(picks)
            or not all(isinstance(x, int) for x in picks)):
        raise UserError("Choose one person in your clip for each performer." if performers == 1
                        else "Choose two different people in your clip, one for each performer.")
    layout, _ = _clip_layout(m["upload_id"], params.get("shape"))
    entry = (UPLOADS[m["upload_id"]].get("people") or {}).get(_people_key(m.get("start", 0), layout)) or {}
    if entry.get("state") != "ready" or not set(picks) <= {x["id"] for x in entry.get("people", [])}:
        raise UserError("We don't have those people for this start point any more. Choose who to replace again.")


@app.post("/api/jobs")
def create_job(params: dict) -> dict:
    m = params.get("motion") or {}
    if m.get("preset_id"):
        raise UserError("Ready-made motions aren't on this server yet. Upload your own clip.")
    _upload_path(m.get("upload_id", ""), "video")
    if m.get("length") not in SEGMENTS or float(m.get("start", 0)) < 0:
        raise UserError("Pick a length of 5, 10, 15 or 20 seconds.")
    if params.get("subject") is None and params.get("mode") == "recast" and m.get("picks"):
        params["subject"] = "person"  # chosen in the frame: the clip reader says person or animal (run_preview)
    if params.get("subject") not in ("person", "animal"):
        raise UserError("Say whether the performer is a person or an animal.")
    performers = params.get("performers", 1)
    if performers not in (1, 2):
        raise UserError("Up to two performers for now.")
    chars = params.get("characters") or []
    if len(chars) not in (0, performers):
        raise UserError("Add one character per performer, or none.")
    for c in chars:
        _upload_path(c.get("upload_id", ""), "image")
        if len((c.get("text") or "").strip()) < 3:
            raise UserError("Describe each character in a few words.")
    if len(chars) == 2 and chars[0]["text"].strip().lower() == chars[1]["text"].strip().lower():
        # measured: identity follows the words, so two identical descriptions give two copies of one person
        raise UserError("Both characters have the same description, so they would come out alike. "
                        "Describe each one as they look.")
    if params.get("style") and params["style"] not in styles.STYLES:
        raise UserError("That look doesn't exist.")
    place = params.get("place") or {"mode": "keep"}
    if place.get("mode") not in ("keep", "describe", "image", "character"):
        raise UserError("Unknown place option.")
    if place["mode"] == "image":
        _upload_path(place.get("upload_id", ""), "image")
    if place["mode"] == "character" and not chars:
        raise UserError("“Where my character is” needs a character.")
    _check_mode(params, chars, place, performers)
    performers = _swap_picks(params, performers)
    _check_picks(params, performers)
    if (params.get("shape") or "auto") not in ("auto", *graph.SIZES):
        raise UserError("Unknown shape.")
    if params.get("finish") not in ("480p", "720p", "1080p") or params.get("audio") not in ("original", "mute"):
        raise UserError("Unknown finish or sound option.")
    jid = _new_id("job")
    _job_dir(jid).mkdir(parents=True)
    j = {"id": jid, "created_at": datetime.now(timezone.utc).isoformat(), "state": "draft",
         "title": _title(params), "params": params, "cost_renders": SEGMENTS[m["length"]]}
    with LOCK:
        JOBS[jid] = j
        _update(j)
    return _public(j)


def _get(jid: str) -> dict:
    j = JOBS.get(jid)
    if j is None:
        raise HTTPException(404, "This render does not exist.")
    return j


@app.post("/api/jobs/{jid}/preview")
def preview(jid: str, body: dict | None = None) -> dict:
    j = _get(jid)
    with LOCK:
        if j["state"] not in ("draft", "awaiting_approval", "failed"):
            raise HTTPException(409, "This render is already under way.")
        new_seed = bool((body or {}).get("new_seed"))
        seed = random.randrange(1, 2**31) if new_seed else (j.get("preview") or {}).get("seed", 1)
        _update(j, state="matching", error=None)
    TASKS.put(("preview", jid, seed))
    return _public(j)


@app.post("/api/jobs/{jid}/approve")
def approve(jid: str) -> dict:
    j = _get(jid)
    with LOCK:
        # a render that failed after its preview was approved (and was refunded) can run again from that preview
        rerun = j["state"] == "failed" and (j.get("error") or {}).get("refunded") and (j.get("_work") or {}).get("reference")
        if j["state"] != "awaiting_approval" and not rerun:
            raise HTTPException(409, "Approve the preview first.")
        if _renders_left() < j["cost_renders"]:
            raise HTTPException(402, "No renders left on this server.")
        _update(j, state="queued", error=None, progress={"stage": "waiting_for_gpu", "queue_position": TASKS.qsize() + 1,
                                             "eta_seconds": j["_work"]["segments"] * 520})
    TASKS.put(("render", jid, None))
    return _public(j)


SCENE_EDITABLE = {"matching", "awaiting_approval", "failed"}  # never once a render is queued or running


@app.post("/api/jobs/{jid}/scene")
def edit_scene(jid: str, body: dict) -> dict:
    """The visitor corrects how we read their clip (Restyle). The render uses these words."""
    j = _get(jid)
    text = " ".join(str(body.get("text") or "").split())
    if not 3 <= len(text) <= describe.MAX_SCENE:
        raise UserError(f"Describe the clip in 3 to {describe.MAX_SCENE} characters.")
    with LOCK:
        if (j.get("scene") or {}).get("state") != "ready":
            raise HTTPException(409, "We're still reading your clip. Edit it once the line appears.")
        if j["state"] not in SCENE_EDITABLE or (j["state"] == "failed" and (j.get("error") or {}).get("refunded")):
            raise HTTPException(409, "This video is already rendering; its description can't change now.")
        _update(j, scene={"state": "ready", "text": text, "edited": True},
                _work={**(j.get("_work") or {}), "scene": text})
    return _public(j)


@app.post("/api/jobs/{jid}/cancel")
def cancel(jid: str) -> dict:
    j = _get(jid)
    with LOCK:
        active = j["state"] in ACTIVE_STATES
        if active:
            _update(j, state="cancelled", progress=None,
                    error={"message": "Cancelled. Nothing was charged.", "refunded": True})
        gjob = RUNNING.get(jid) if active else None
    try:  # our own job on the GPU; nobody else's is touched
        if gjob is not None:
            gjob.cancel()
        elif active:  # not followed yet (the server just restarted): cancel it by its stored id
            _cancel_stored(jid)
    except Exception:
        log.exception("cancel of %s did not reach the GPU", jid)
    return _public(j)


def _cancel_stored(jid: str) -> None:
    """Cancel the job's latest GPU submission by the id we stored when submitting it."""
    subs = sorted(_job_dir(jid).glob("*submission*.json"), key=lambda f: f.stat().st_mtime)
    job_id = json.loads(subs[-1].read_text()).get("job_id") if subs else None
    if job_id:
        with _comfy() as client:
            client.jobs.get(job_id).cancel()


@app.get("/api/jobs/{jid}")
def job(jid: str) -> dict:
    return _public(_get(jid))


@app.get("/api/jobs")
def job_list() -> list:
    with LOCK:
        return [_public(j) for j in sorted(JOBS.values(), key=lambda j: j["created_at"], reverse=True)]
