"""Command line: recast one clip end to end.

    recast run --drive clip.mp4 --character anyone.png --character-text "..." --out runs/me
    recast run --drive clip.mp4 --style anime --out runs/anime          # restyle, no character
    recast run --drive clip.mp4 --character robot.png --character-text "..." \\
        --location mars.jpg --style comic --out runs/combo
    recast run --drive clip.mp4 --reference ready.png --out runs/manual  # bring your own reference
    recast run --drive duo.mp4 --character a.png --character-text "..." \
        --character2 b.png --character2-text "..." --subject cat --out runs/duo  # two performers, left/right

Any of --character / --location / --style / --scene new builds a matched
reference first (see recast.reference): the clip's first frame, changed.
Prompts are composed from those choices; --appearance / --motion override.
`recast match` runs only the reference step; `recast styles` lists looks.
`--dry-run` writes the graphs without touching a GPU.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import crop, describe, graph, media, pose, prompts, recipe, styles
from . import reference as reflib


def _wants_match(a: argparse.Namespace) -> bool:
    return bool(a.character or a.location or a.style or a.scene == "new" or a.outfit or a.product)


def _prepare(a: argparse.Namespace, out: Path) -> tuple[graph.RecastParams, Path, Path]:
    info = media.validate_upload(a.drive)
    a.box = media.content_box(a.drive)
    layout = a.layout or (media.layout_for(*a.box[:2]) if a.box else info.layout)
    fps = 16
    usable = min(info.seconds, a.seconds or media.MAX_SECONDS)
    segments = a.segments or min(graph.MAX_SEGMENTS, graph.segments_for(round(usable * fps)))
    seconds = min(usable, graph.frames_for(segments) / fps)
    tmp = out / "drive.tmp.mp4"
    media.normalize(a.drive, tmp, layout=layout, seconds=seconds, start=a.start, fps=fps, box=a.box)
    drive = tmp.rename(out / f"drive_{recipe.sha256(tmp)[:12]}.mp4")
    if a.reference:
        ref = media.fit_image(a.reference, out / "reference.png", layout=layout, mode=a.fit)
        ref = ref.rename(out / f"reference_{recipe.sha256(ref)[:12]}.png")
    else:
        ref = _match(a, out, layout)
        if ref is None:  # dry run: stand-in so the recast graph can still be written
            ref = media.frame_at(a.drive, out / "reference.png", layout=layout, start=a.start, box=a.box)
    params = graph.RecastParams(
        reference=ref.name, drive=drive.name,
        appearance=a.appearance or prompts.appearance(
            subject=a.subject, character_text=a.character_text or "", style=a.style or "",
            scene=a.scene, background=a.background or "",
            has_location=bool(a.location or a.place_from_character),
            wearing=a.outfit_text or "", holding=a.product_text or "",
            character2_text=a.character2_text or "", two=bool(a.character2)),
        motion=a.motion or prompts.motion(subject=a.subject, two=bool(a.character2)),
        layout=layout, segments=segments, fps=fps, seed=a.seed, steps=a.steps,
        prefix=f"recast/{a.name or out.name}")
    params.validate()
    return params, ref, drive


def _show(ev: dict) -> None:
    if ev["kind"] == "progress" and ev.get("step"):
        print(f"\r  {ev.get('node')}: step {ev['step']}/{ev['steps']}   ", end="", flush=True)
    elif ev["kind"] != "progress":
        print(f"\n  {ev}")


def _match(a: argparse.Namespace, out: Path, layout: str) -> Path | None:
    """Build the matched reference. Returns None on a dry run."""
    def named(path: Path, stem: str) -> Path:
        return path.rename(out / f"{stem}_{recipe.sha256(path)[:12]}{path.suffix}")

    frame = named(media.frame_at(a.drive, out / "first_frame.png", layout=layout, start=a.start, box=a.box), "frame")
    base = "character" if a.place_from_character else "location" if a.location and a.character else "frame"
    images = {}
    for slot, src in (("character", a.character), ("character2", a.character2)):
        if not src:
            continue
        if slot == base:  # the whole photo is the scene, in the clip's shape
            images[slot] = named(crop.to_shape(media.clean_image(src, out / f"{slot}_full.png"),
                                               out / f"{slot}.png", layout), slot)
            continue
        img = src if a.keep_outfit else crop.head_and_shoulders(src, out / f"{slot}_head.png")
        if img is None:
            print(f"note: no face found in {src}; using the whole image (its pose may leak)")
            img = src
        images[slot] = named(media.clean_image(img, out / f"{slot}.png"), slot)
    for slot, src in (("outfit", a.outfit), ("product", a.product)):
        if src:
            images[slot] = named(media.clean_image(src, out / f"{slot}.png"), slot)
    if a.location:
        loc = media.clean_image(a.location, out / "location_full.png")
        images["location"] = named(crop.to_shape(loc, out / "location.png", layout) if base == "location" else loc,
                                   "location")
    arms = pose.read_arms(frame) if a.product else None  # free hand by picture side, from keypoints
    room = images.get("location") or (images[base] if base != "frame" else frame)
    mp = reflib.MatchParams(frame=frame.name if base == "frame" else None, base=base,
                            character_text=a.character_text or "",
                            product_hand=arms.free if arms else "", other_hand=arms.other() if arms and arms.free else "",
                            character2_text=a.character2_text or "", pose=a.pose or "", pose2=a.pose2 or "",
                            cutout_colour=media.edge_colour(room) if a.scene == "keep" else reflib.CUTOUT_GREY,
                            outfit_text=a.outfit_text or "", product_text=a.product_text or "",
                            style=a.style or "", subject=a.subject, scene=a.scene,
                            background=a.background or "", quality=a.match_quality, seed=a.match_seed,
                            prefix=f"recast/{a.name or out.name}_ref",
                            **{k: v.name for k, v in images.items()})
    g = reflib.build(mp)
    (out / "reference_graph.json").write_text(json.dumps(g, indent=1, ensure_ascii=False))
    print(f"reference prompt: {reflib.prompt_for(mp)}")
    if a.dry_run:
        return None

    from comfy_sdk import Comfy

    from . import runner

    t0 = time.time()
    with Comfy(timeout=120) as client:
        if (mp.character is not None or mp.outfit is not None or mp.product is not None) and not (a.pose or a.pose2) \
                and not a.no_describe:
            # fix A, automatically: the clip's poses in words, read from the first frame
            dj = runner.follow(runner.submit_graph(
                client, lambda: describe.build(client.assets.from_file(frame), prefix=f"recast/{a.name or out.name}_describe"),
                out / "describe_submission.json"))
            files = runner.download(dj, out / "describe", node_id=describe.FINAL_NODE)
            found = describe.parse(files[0].read_text()) if files else []
            print(f"read from the clip: {found}")
            problem = describe.mismatch(found, performers=2 if a.character2 else 1,
                                        subject="animal" if a.subject in ("cat", "dog", "animal") else "person")
            if problem:
                print(f"warning: {problem}")
            elif len(found) == (2 if a.character2 else 1):
                mp.pose = found[0].pose
                mp.pose2 = found[1].pose if a.character2 else ""
                if mp.base != "frame":  # the clip isn't in the edit: its layout travels as words too
                    mp.side, mp.shot = found[0].side, found[0].shot
                    mp.shot2 = found[1].shot if a.character2 else ""
                print(f"reference prompt: {reflib.prompt_for(mp)}")

        def make():
            if mp.base == "frame":
                mp.frame = client.assets.from_file(frame)
            for k, v in images.items():
                setattr(mp, k, client.assets.from_file(v))
            return reflib.build(mp)
        # the state file is keyed by the graph: a re-run with other choices is a new job, never a reattach
        key = recipe.graph_sha(reflib.build(mp))[:10]
        job = runner.follow(runner.submit_graph(client, make, out / f"reference_submission_{key}.json"), _show)
        files = runner.download(job, out / "reference_render", node_id=reflib.FINAL_NODE)
    if not files:
        raise media.MediaError("reference job finished without an image")
    print(f"\nreference matched in {time.time() - t0:.0f}s -> {files[0]}")
    ref = media.fit_image(files[0], out / "reference.png", layout=layout, mode="crop")
    return ref.rename(out / f"reference_{recipe.sha256(ref)[:12]}.png")


def cmd_match(a: argparse.Namespace) -> int:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    info = media.validate_upload(a.drive)
    a.box = media.content_box(a.drive)
    ref = _match(a, out, a.layout or (media.layout_for(*a.box[:2]) if a.box else info.layout))
    print("dry run: reference_graph.json written" if ref is None else f"reference: {ref}")
    return 0


def cmd_run(a: argparse.Namespace) -> int:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    params, ref, drive = _prepare(a, out)
    g = graph.build(params)
    (out / "graph.json").write_text(json.dumps(g, indent=1, ensure_ascii=False))
    print(f"prepared: {params.layout} {params.size[0]}x{params.size[1]}, {params.segments} segment(s), "
          f"{graph.frames_for(params.segments)} frames max")
    if a.dry_run:
        return 0

    from comfy_sdk import Comfy

    from . import runner

    t0 = time.time()
    with Comfy(timeout=120) as client:
        params.reference, params.drive = ref, drive  # uploaded as SDK assets
        # no job metadata: comfy-api-proxy 0.1.6 rejects the map comfy-sdk 0.5.0 sends
        job = runner.submit(client, params, out / f"submission_{recipe.graph_sha(g)[:10]}.json")
        print(f"job {job.id}")
        job = runner.follow(job, _show)
        print()
        files = runner.download(job, out / "render")
    seconds = round(time.time() - t0, 1)
    if not files:
        print("job finished without a video output", file=sys.stderr)
        return 1
    native = media.with_source_audio(files[0], drive, out / "recast_native.mp4")
    final = media.deliver(native, out / "recast.mp4", layout=params.layout)  # exact aspect, native pixels
    compare = media.side_by_side(drive, final, out / "compare.mp4", vertical=params.layout.startswith("landscape"))
    params.reference, params.drive = ref.name, drive.name
    recipe.write(out / "recipe.json", params=params, g=g, inputs={"reference": ref, "drive": drive},
                 outputs={"recast": final, "compare": compare}, job_id=job.id, seconds=seconds)
    print(f"done in {seconds}s -> {final}  {compare}")
    return 0


def cmd_styles(a: argparse.Namespace) -> int:
    for s in styles.STYLES.values():
        print(f"{s.key:12} {s.name}")
    return 0


def _change_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--character", help="any character image: who replaces the performer")
    p.add_argument("--character-text", help="who the character is: shape, build, colours, clothing")
    p.add_argument("--character2", help="a second character, for the performer on the picture's right "
                                        "(--character then takes the one on the left)")
    p.add_argument("--character2-text")
    p.add_argument("--keep-outfit", action="store_true",
                   help="use the whole character image; by default it is cropped to head and shoulders "
                        "so its pose can't leak into the result")
    p.add_argument("--pose", help="what the (left) performer's body is doing, in concrete, picture-relative words")
    p.add_argument("--pose2", help="the same for the performer on the right")
    p.add_argument("--no-describe", action="store_true",
                   help="don't read the poses from the clip's first frame (they are read by default "
                        "when a character is given and --pose is not)")
    p.add_argument("--outfit", help="swap: a garment the performer now wears (the performer stays themselves)")
    p.add_argument("--outfit-text", help="what the garment is")
    p.add_argument("--product", help="swap: an object the performer now holds, in the hand that stays in view")
    p.add_argument("--product-text", help="what the product is")
    p.add_argument("--place-from-character", action="store_true",
                   help="perform in the place in the (left) character's own photo")
    p.add_argument("--location", help="an image of the place to perform in (with --character, it is the scene)")
    p.add_argument("--style", choices=sorted(styles.STYLES), help="redraw everything in this look")
    p.add_argument("--subject", choices=reflib.SUBJECTS, default="person", help="what the performer is")
    p.add_argument("--scene", choices=["keep", "new"], default="keep",
                   help="keep the clip's own place, or replace it with --background")
    p.add_argument("--background", help="the new background (with --scene new)")
    p.add_argument("--match-quality", choices=["fast", "high"], default="fast")
    p.add_argument("--match-seed", type=int, default=1)


def _clip_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--drive", required=True, help="performance clip")
    p.add_argument("--out", required=True)
    p.add_argument("--name")
    p.add_argument("--layout", choices=sorted(graph.SIZES))
    p.add_argument("--start", type=float, default=0.0)
    p.add_argument("--dry-run", action="store_true")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="recast")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="recast one clip")
    _clip_args(r)
    _change_args(r)
    r.add_argument("--reference", help="a ready reference still (skips the matching step)")
    r.add_argument("--appearance", help="override the composed appearance prompt")
    r.add_argument("--motion", help="override the composed motion prompt")
    r.add_argument("--segments", type=int)
    r.add_argument("--seconds", type=float, help="use at most this many seconds of the clip")
    r.add_argument("--seed", type=int, default=graph.DEFAULT_SEED)
    r.add_argument("--steps", type=int, default=10)
    r.add_argument("--fit", choices=["pad", "crop"], default="pad")
    r.set_defaults(fn=cmd_run)

    m = sub.add_parser("match", help="only build the matched reference")
    _clip_args(m)
    _change_args(m)
    m.set_defaults(fn=cmd_match, reference=None)

    s = sub.add_parser("styles", help="list restyle looks")
    s.set_defaults(fn=cmd_styles)

    a = ap.parse_args(argv)
    if a.cmd in ("run", "match"):
        if a.character and not a.character_text:
            ap.error("--character needs --character-text")
        if a.character2 and not (a.character and a.character2_text):
            ap.error("--character2 needs --character and --character2-text")
        for img, text, flag in ((a.outfit, a.outfit_text, "--outfit"), (a.product, a.product_text, "--product")):
            if img and not text:
                ap.error(f"{flag} needs {flag}-text")
        if a.place_from_character and not a.character:
            ap.error("--place-from-character needs --character")
        if a.reference and _wants_match(a):
            ap.error("--reference is a finished reference; it can't be combined with "
                     "--character / --location / --style / --scene new / --outfit / --product")
        if not a.reference and not _wants_match(a):
            ap.error("say what changes: --character, --style, --location, --scene new, or --reference")
    try:
        return a.fn(a)
    except Exception as e:
        from .runner import RenderFailed
        if not isinstance(e, (media.MediaError, graph.ParamError, reflib.ReferenceError, ValueError, RenderFailed)):
            raise
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
