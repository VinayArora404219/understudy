"""Keep the people who aren't recast as filmed.

SCAIL-2's replacement mode redraws the whole frame from the clip, not only the masked performers, so the
reference can leak: in a crowded clip the chosen man's black-rimmed glasses also appeared on the man
beside him. So everyone in the clip but the chosen performers is tracked, including anyone who walks in
later, and after the render their own pixels go back (recast/composite.py).

Only they go back, not the room. Putting the whole clip back outside the performers was tried first and
cost more than it fixed: the render's wall is lit and shaded unlike the clip's, so a ghost of the dog's
outline showed on the wall where the dog had stood, and a grey ring ran round each new character (seen by
the user on the duo clip, and measured: one colour fit per frame can't follow the render's vignette). The
room keeps the render's colour, which drifts a little (a white studio comes back slightly grey).

The new characters are found in the render too, so one standing in front of a bystander stays as rendered:
SAM3 finds each from points inside the old performer's start mask (the new character stands there), then
tracks them. A man who replaces a cat is bigger than the cat, so the cat's outline alone would cut him off.
Three masks come out: the old and new performers together (to keep them out of the colour fit), the new
characters alone, and the bystanders.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageFilter

GROW = 12  # pixels at the render size: hair and fingers sit just outside a tight mask
SOFT = 9  # blur radius of the seam
OTHERS_GROW = 6  # pixels kept as filmed around everyone not recast
EVERYONE = "person, animal"  # who else the clip may show, at any frame
EVERYONE_MAX = 12


def inside_points(mask: Path, count: int = 3) -> list[tuple[int, int]]:
    """Points well inside a mask, spread from top to bottom: one point often gives SAM a part (a bib, a
    sleeve) where several give the whole person (measured on the duo clip). The frame border counts as an
    edge, or a performer cut off by it gets a point on the border, where the new character may not be."""
    m = Image.open(mask).convert("L").point(lambda v: 255 if v > 127 else 0)
    w, h = m.size
    framed = Image.new("L", (w + 2, h + 2), 0)
    framed.paste(m, (1, 1))
    core = framed
    for _ in range(12):  # erode a little, keeping a band wide enough to place points in
        smaller = core.filter(ImageFilter.MinFilter(5))
        if sum(1 for v in smaller.getdata() if v) < 400:
            break
        core = smaller
    px = core.load()
    pts = [(x - 1, y - 1) for y in range(1, h + 1, 2) for x in range(1, w + 1, 2) if px[x, y]]
    if not pts:
        raise ValueError(f"{mask.name} is empty")
    pts.sort(key=lambda p: p[1])
    out = []
    for k in range(count):  # the middle of each horizontal band of the mask
        band = pts[len(pts) * k // count: len(pts) * (k + 1) // count] or pts
        cx = sum(p[0] for p in band) / len(band)
        cy = sum(p[1] for p in band) / len(band)
        out.append(min(band, key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2))
    return out


def add(n: Callable[..., str], *, render: list, old_track: list, sam: list,
        points: list[list[tuple[int, int]]], clip: list, others: list[Any] | None = None
        ) -> tuple[str, str, str]:
    """Add the masks for the composite to a graph built with `n(key, class, **inputs)`. Returns the keys of
    three soft mask batches as images: the old and new performers, the new characters alone, and everyone
    else in `clip` (kept as filmed). `render` has the clip's size and length. `others`: start masks (files)
    of the people found in the start frame and not chosen."""
    n("keep_first", "ImageFromBatch", image=render, batch_index=0, length=1)
    found = []
    for k, pts in enumerate(points):  # one character per list of points
        n(f"keep_find{k}", "SAM3_Detect", model=sam, image=["keep_first", 0], threshold=0.5, refine_iterations=2,
          individual_masks=False, positive_coords=json.dumps([{"x": x, "y": y} for x, y in pts]))
        found.append(n(f"keep_find{k}_img", "MaskToImage", mask=[f"keep_find{k}", 0]))
    start = found[0]
    for k in range(1, len(found)):
        start = n(f"keep_finds{k}", "ImageBatch", image1=[start, 0], image2=[found[k], 0])
    n("keep_start", "ImageToMask", image=[start, 0], channel="red")
    n("keep_new_track", "SAM3_VideoTrack", images=render, model=sam, initial_mask=["keep_start", 0],
      detection_threshold=0.5, max_objects=len(points), detect_interval=1)
    n("keep_new", "SAM3_TrackToMask", track_data=["keep_new_track", 0], object_indices="")
    n("keep_old", "SAM3_TrackToMask", track_data=old_track, object_indices="")
    n("keep_both", "MaskComposite", destination=["keep_new", 0], source=["keep_old", 0], x=0, y=0, operation="or")
    n("keep_grown", "GrowMask", mask=["keep_both", 0], expand=GROW, tapered_corners=True)
    n("keep_grown_img", "MaskToImage", mask=["keep_grown", 0])
    n("keep_soft_img", "ImageBlur", image=["keep_grown_img", 0], blur_radius=SOFT, sigma=SOFT / 2)
    # Everyone in the clip by words, looked for on every frame: someone who walks in after the start frame was
    # never found by the start-frame detector (a goalkeeper running in kept the render's kit colour). The
    # chosen performers are taken out with room to spare, so no edge of them comes back as filmed.
    n("keep_words", "CLIPTextEncode", clip=[sam[0], 1], text=EVERYONE)
    n("keep_everyone_track", "SAM3_VideoTrack", images=clip, model=sam, conditioning=["keep_words", 0],
      detection_threshold=0.5, max_objects=EVERYONE_MAX, detect_interval=1)
    bystanders = n("keep_everyone", "SAM3_TrackToMask", track_data=["keep_everyone_track", 0], object_indices="")
    if others:  # and the ones found in the start frame, tracked from their own masks (words can miss them)
        for k, other in enumerate(others):
            n(f"keep_other{k}", "LoadImage", image=other)
        start = "keep_other0"
        for k in range(1, len(others)):
            start = n(f"keep_others{k}", "ImageBatch", image1=[start, 0], image2=[f"keep_other{k}", 0])
        n("keep_others_start", "ImageToMask", image=[start, 0], channel="red")
        n("keep_others_track", "SAM3_VideoTrack", images=clip, model=sam, initial_mask=["keep_others_start", 0],
          detection_threshold=0.5, max_objects=len(others), detect_interval=1)
        n("keep_others", "SAM3_TrackToMask", track_data=["keep_others_track", 0], object_indices="")
        bystanders = n("keep_all_others", "MaskComposite", destination=[bystanders, 0], source=["keep_others", 0],
                       x=0, y=0, operation="or")
    n("keep_old_grown", "GrowMask", mask=["keep_old", 0], expand=GROW, tapered_corners=True)
    n("keep_rest", "MaskComposite", destination=[bystanders, 0], source=["keep_old_grown", 0], x=0, y=0,
      operation="subtract")
    # a few pixels past their outline: the leak sat exactly on the edge where two people touch
    n("keep_others_grown", "GrowMask", mask=["keep_rest", 0], expand=OTHERS_GROW, tapered_corners=True)
    n("keep_others_img", "MaskToImage", mask=["keep_others_grown", 0])
    n("keep_others_soft_img", "ImageBlur", image=["keep_others_img", 0], blur_radius=SOFT // 2, sigma=SOFT / 4)
    # a little room around the new characters too: SAM leaves out loose things like a cape's edge
    n("keep_new_grown", "GrowMask", mask=["keep_new", 0], expand=GROW // 2, tapered_corners=True)
    n("keep_new_grown_img", "MaskToImage", mask=["keep_new_grown", 0])
    n("keep_new_soft_img", "ImageBlur", image=["keep_new_grown_img", 0], blur_radius=SOFT // 2, sigma=SOFT / 4)
    return "keep_soft_img", "keep_new_soft_img", "keep_others_soft_img"


def build_poc(drive: Any, render: Any, picks: list[Any], points: list[list[tuple[int, int]]], frames: int, *,
              sam3: str, others: list[Any] | None = None, prefix: str = "recast/keep") -> dict[str, dict[str, Any]]:
    """The composite alone, on a finished render: for trying it without rendering again."""
    g: dict[str, dict[str, Any]] = {}

    def n(key: str, cls: str, **inputs: Any) -> str:
        g[key] = {"class_type": cls, "inputs": inputs}
        return key

    n("clip_video", "LoadVideo", file=drive)
    n("clip_parts", "GetVideoComponents", video=["clip_video", 0])
    n("clip", "ImageFromBatch", image=["clip_parts", 0], batch_index=0, length=frames)
    n("render_video", "LoadVideo", file=render)
    n("render_parts", "GetVideoComponents", video=["render_video", 0])
    n("render", "ImageFromBatch", image=["render_parts", 0], batch_index=0, length=frames)
    n("sam", "CheckpointLoaderSimple", ckpt_name=sam3)
    for k, pick in enumerate(picks):
        n(f"pick{k}", "LoadImage", image=pick)
    start = "pick0"
    for k in range(1, len(picks)):
        start = n(f"picks{k}", "ImageBatch", image1=[start, 0], image2=[f"pick{k}", 0])
    n("start_masks", "ImageToMask", image=[start, 0], channel="red")
    n("old_track", "SAM3_VideoTrack", images=["clip", 0], model=["sam", 0], initial_mask=["start_masks", 0],
      detection_threshold=0.5, max_objects=len(picks), detect_interval=1)
    union, new, kept = add(n, render=["render", 0], old_track=["old_track", 0], sam=["sam", 0], points=points,
                           clip=["clip", 0], others=others)
    for key, images in (("save_mask", union), ("save_new", new), ("save_others", kept)):
        n(f"{key}_video", "CreateVideo", images=[images, 0], fps=16.0)
        n(key, "SaveVideo", video=[f"{key}_video", 0], filename_prefix=f"{prefix}_{key}", format="auto", codec="auto")
    return g
