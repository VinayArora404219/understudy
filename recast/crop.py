"""Head-and-shoulders crop for character images.

Measured (bench/RESULTS.md, fix C): Qwen-Image-Edit copies the pose of a
full-body character picture whatever the prompt says, and cropping the picture
to head and shoulders removes the pose while keeping the identity. So the crop
is the default for every character image; a user who wants the whole outfit
from the picture turns it off, and the pose is then held by words instead.

Faces are found with MediaPipe's face detector (model bundled in the package,
CPU only). No face (an animal, a mascot, a back view) means no crop, and the
caller says so rather than guessing a box.
"""

from __future__ import annotations

import os
from pathlib import Path

from . import media

FaceBox = tuple[float, float, float, float]  # x, y, w, h in pixels

SIDE = 4.0  # crop side, in face heights: head, hair or hat, and the top of the shoulders
HEADROOM = 0.9  # face heights kept above the face box (hair, hats)
MIN_SCORE = 0.6


def box_around(face: FaceBox, width: int, height: int, *, side: float = SIDE,
               headroom: float = HEADROOM) -> media.Box:
    """A square around `face`, slid (not shrunk) to stay inside the picture."""
    x, y, w, h = face
    s = min(round(h * side), width, height)
    s -= s % 2
    left = round(x + w / 2 - s / 2)
    top = round(y - headroom * h)
    left = max(0, min(left, width - s))
    top = max(0, min(top, height - s))
    return s, s, left, top


def find_face(path: str | Path) -> FaceBox | None:
    """The most confident face in the picture, or None."""
    os.environ.setdefault("GLOG_minloglevel", "2")  # MediaPipe is chatty on stderr
    import cv2
    import mediapipe as mp

    img = cv2.imread(str(path))
    if img is None:
        raise media.MediaError("image could not be read")
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    height, width = rgb.shape[:2]
    # model 1 is the full-range detector: faces that are small in a full-body picture
    with mp.solutions.face_detection.FaceDetection(model_selection=1, min_detection_confidence=MIN_SCORE) as fd:
        found = fd.process(rgb).detections or []
    if not found:
        return None
    best = max(found, key=lambda d: d.score[0]).location_data.relative_bounding_box
    return best.xmin * width, best.ymin * height, best.width * width, best.height * height


def head_and_shoulders(src: str | Path, dst: str | Path) -> Path | None:
    """Write the head-and-shoulders crop of `src` to `dst`; None when no face was found."""
    face = find_face(src)
    if face is None:
        return None
    info = media.probe(src)
    return media.crop_image(src, dst, box_around(face, info.width, info.height))


def shape_box(width: int, height: int, aspect: float, face: FaceBox | None) -> media.Box:
    """The largest box of `aspect` (w/h) inside the picture, centred on the face across and keeping
    it in the upper third down, or centred when there is no face."""
    if width / height > aspect:
        w, h = round(height * aspect), height
    else:
        w, h = width, round(width / aspect)
    w, h = w - w % 2, h - h % 2
    cx, cy = (face[0] + face[2] / 2, face[1] + face[3] / 2) if face else (width / 2, height / 2)
    left = max(0, min(round(cx - w / 2), width - w))
    top = max(0, min(round(cy - (h / 3 if face else h / 2)), height - h))
    return w, h, left, top


def to_shape(src: str | Path, dst: str | Path, layout: str) -> Path:
    """Crop a photo that becomes the scene (the character's own place, a place image) to the clip's
    shape, so its person and room are what fills the frame rather than what a resize squeezes."""
    info = media.probe(src)
    w, h = media.delivery_size(layout)
    return media.crop_image(src, dst, shape_box(info.width, info.height, w / h, find_face(src)))
