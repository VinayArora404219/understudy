"""Who is in the start frame, and which of them a recast replaces.

Words pick a performer out of a crowd only while they differ ("man in a grey suit" held one man through a
10 s crowded clip where "man" tracked a passer-by, bench/RESULTS.md), and nothing in a first frame says who
the performer is: the clip reader named a different man each time. So the visitor chooses. SAM3_Detect
finds every person and animal in the start frame, one mask each; the chosen masks then start SAM3's video
tracker (scail.build with `picks`), which follows those individuals by how they look and move, not by words,
so two people dressed alike are still told apart.

The GPU part is one detection graph. Everything else here is local: reading the masks, numbering the
people left to right, finding who a tap landed on, and writing the chosen masks at the render size.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageFilter

from . import scail

WORDS = "person:8, animal:4"  # SAM3's prompt syntax: up to 8 people and 4 animals, one mask each
MIN_AREA = 0.004  # of the frame: smaller is a far-off head in the crowd, not someone to recast
SAME = 0.6  # overlap above which two masks are one performer found by both words
FINAL_NODE = "save"


@dataclass(frozen=True)
class Person:
    id: int  # 1, 2, 3... left to right, as shown on the picture
    box: tuple[float, float, float, float]  # x, y, width, height as fractions of the frame
    area: float  # fraction of the frame
    cx: float  # centroid, fraction of the width: what "left to right" means everywhere
    mask: str  # file name in the people directory


def build_detect(frame: Any, *, prefix: str = "recast/people") -> dict[str, dict[str, Any]]:
    g: dict[str, dict[str, Any]] = {}

    def n(key: str, cls: str, **inputs: Any) -> str:
        g[key] = {"class_type": cls, "inputs": inputs}
        return key

    n("frame", "LoadImage", image=frame)
    n("sam", "CheckpointLoaderSimple", ckpt_name=scail.SAM3)
    n("words", "CLIPTextEncode", clip=["sam", 1], text=WORDS)
    n("detect", "SAM3_Detect", model=["sam", 0], image=["frame", 0], conditioning=["words", 0], threshold=0.5,
      refine_iterations=2, individual_masks=True)
    n("as_image", "MaskToImage", mask=["detect", 0])
    n("save", "SaveImage", images=["as_image", 0], filename_prefix=prefix)
    return g


def _load(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("L")) > 127


def read(mask_files: list[Path], dst: Path) -> list[Person]:
    """Number the detected people left to right; drop specks and the second copy of anyone found twice."""
    dst.mkdir(parents=True, exist_ok=True)
    masks = [m for m in (_load(f) for f in mask_files) if m.any()]
    masks.sort(key=lambda m: -m.sum())  # bigger first, so a duplicate keeps its fuller mask
    kept: list[np.ndarray] = []
    for m in masks:
        if m.mean() < MIN_AREA:
            continue
        if any((m & k).sum() / min(m.sum(), k.sum()) > SAME for k in kept):
            continue
        kept.append(m)
    kept.sort(key=lambda m: np.nonzero(m)[1].mean())
    people = []
    for i, m in enumerate(kept, start=1):
        h, w = m.shape
        ys, xs = np.nonzero(m)
        name = f"person_{i}.png"
        Image.fromarray((m * 255).astype(np.uint8)).save(dst / name)
        people.append(Person(id=i, box=(xs.min() / w, ys.min() / h, (xs.max() + 1 - xs.min()) / w,
                                        (ys.max() + 1 - ys.min()) / h),
                             area=round(float(m.mean()), 4), cx=round(float(xs.mean() / w), 4), mask=name))
    (dst / "people.json").write_text(json.dumps([asdict(p) for p in people], indent=1))
    return people


def load(src: Path) -> list[Person]:
    return [Person(**{**p, "box": tuple(p["box"])}) for p in json.loads((src / "people.json").read_text())]


def at(people: list[Person], src: Path, x: float, y: float) -> int | None:
    """Who a tap at (x, y), fractions of the frame, landed on: the smallest mask under it (the one in front)."""
    hits = []
    for p in people:
        m = _load(src / p.mask)
        h, w = m.shape
        if m[min(h - 1, int(y * h)), min(w - 1, int(x * w))]:
            hits.append(p)
    return min(hits, key=lambda p: p.area).id if hits else None


def write_picks(people: list[Person], ids: list[int], src: Path, dst: Path, size: tuple[int, int]) -> list[Path]:
    """The chosen masks at the render size, left to right: the order SCAIL-2 matches characters in."""
    chosen = sorted((p for p in people if p.id in ids), key=lambda p: p.cx)
    if len(chosen) != len(ids):
        raise ValueError("a chosen performer isn't in this frame")
    out = []
    for k, p in enumerate(chosen):
        m = Image.open(src / p.mask).convert("L").resize(size, Image.NEAREST)
        out.append(dst / f"pick_{k}.png")
        m.save(out[-1])
    return out


CROP_PAD = 0.12
CUT_PAD = 0.05  # of the cut-out's longer side, around the character
SEAL = 0.18  # gaps inside a character narrower than this share of their width are closed


def cut_out(image: Path, people: list[Person], src: Path, dst: Path, colour: int) -> Path | None:
    """The main character of a photo (the biggest person or animal found) on a plain `colour` backdrop,
    cropped round them. Everything else in the photo would count as part of them: a helmet on the desk
    beside a racer became his head-gear when the clip's performer put on sunglasses. None when nobody was
    found (a drawing SAM3 can't read), and the caller uses the whole photo."""
    if not people:
        return None
    main = max(people, key=lambda p: p.area)
    import cv2
    from scipy.ndimage import binary_fill_holes

    img = Image.open(image).convert("RGB")
    W, H = img.size
    inside = np.asarray(Image.open(src / main.mask).convert("L").resize((W, H), Image.NEAREST)) > 127
    # Something in front of them (a microphone on a stand) leaves a hole in their mask, which would become a
    # backdrop-coloured shape on their chest: close gaps narrower than SEAL of their width and paint them in
    # from what surrounds them.
    k = max(3, round(SEAL * main.box[2] * W)) | 1
    closed = cv2.morphologyEx(inside.astype(np.uint8), cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    whole = binary_fill_holes(closed > 0) | inside
    hole = (whole & ~inside).astype(np.uint8) * 255
    if hole.any():
        img = Image.fromarray(cv2.inpaint(np.asarray(img), hole, 7, cv2.INPAINT_TELEA))
    m = Image.fromarray(whole.astype(np.uint8) * 255).filter(ImageFilter.GaussianBlur(1.5))
    back = Image.new("RGB", (W, H), ((colour >> 16) & 255, (colour >> 8) & 255, colour & 255))
    x, y, w, h = main.box
    pad = CUT_PAD * max(w * W, h * H)
    box = (max(0, round(x * W - pad)), max(0, round(y * H - pad)),
           min(W, round((x + w) * W + pad)), min(H, round((y + h) * H + pad)))
    Image.composite(img, back, m).crop(box).save(dst)
    return dst


def write_others(people: list[Person], ids: list[int], src: Path, dst: Path, size: tuple[int, int]) -> list[Path]:
    """Everyone not chosen, at the render size: kept as filmed around the recast performers (recast/keep.py)."""
    out = []
    for p in people:
        if p.id not in ids:
            out.append(dst / f"other_{p.id}.png")
            Image.open(src / p.mask).convert("L").resize(size, Image.NEAREST).save(out[-1])
    return out


def crop_box(people: list[Person], ids: list[int], pad: float = CROP_PAD) -> tuple[float, float, float, float]:
    """The chosen people with some room around them, for the clip reader to describe only them."""
    boxes = [p.box for p in people if p.id in ids]
    x0 = max(0.0, min(b[0] for b in boxes) - pad)
    y0 = max(0.0, min(b[1] for b in boxes) - pad)
    x1 = min(1.0, max(b[0] + b[2] for b in boxes) + pad)
    y1 = min(1.0, max(b[1] + b[3] for b in boxes) + pad)
    return x0, y0, x1 - x0, y1 - y0
