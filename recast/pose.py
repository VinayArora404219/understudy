"""Which arm does what, by the side of the PICTURE it is on, from body keypoints.

A held product must go in the hand the performer keeps free, and the other arm
must be named too, or the edit swaps the arms (measured: Qwen-Image-Edit put the
product in the raised hand's place and mirrored the pose). A vision-language
model asked for "the hand on the picture's left" answered body-relative instead
(mirrored), so sides come from geometry: MediaPipe Pose keypoints (bundled
model, CPU), where the picture's left is simply the smaller x.

People only: product and outfit swaps are offered for one person in the clip.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

from . import media

MIN_VISIBLE = 0.3


@dataclass(frozen=True)
class Point:
    x: float  # pixels
    y: float
    visible: float


@dataclass(frozen=True)
class Arm:
    shoulder: Point
    elbow: Point
    wrist: Point


@dataclass(frozen=True)
class Arms:
    left: str  # what the arm on the picture's left does, as a predicate ("is raised, ...")
    right: str
    free: str  # "left" | "right": the side of the picture of the free (hanging) hand, "" if none

    def other(self) -> str:
        return self.left if self.free == "right" else self.right if self.free == "left" else ""


HANGS = "hangs down by the hip"


def describe_arm(arm: Arm, nose: Point, hip_y: float, shoulder_width: float) -> str:
    """One arm as a predicate. Positions are relative to the body, so the picture's size doesn't matter."""
    s, e, w = arm.shoulder, arm.elbow, arm.wrist
    if w.visible < MIN_VISIBLE:
        # the hand is hidden or out of frame: only an elbow below the shoulder tells us it hangs
        return HANGS if e.visible >= MIN_VISIBLE and e.y > s.y else ""
    if w.y < s.y - 0.1 * shoulder_width:
        near_head = math.dist((w.x, w.y), (nose.x, nose.y)) < 0.8 * shoulder_width
        return "is raised, hand resting on top of the head" if near_head else "is raised above the shoulder"
    if w.y >= hip_y - 0.15 * shoulder_width:
        return HANGS
    return "is bent, hand in front of the body at chest height"


def arms_from(left: Arm, right: Arm, nose: Point, hip_y: float) -> Arms:
    """`left` and `right` are PICTURE sides (sorted by shoulder x by the caller)."""
    width = max(1.0, abs(right.shoulder.x - left.shoulder.x))
    a, b = (describe_arm(x, nose, hip_y, width) for x in (left, right))
    if a == HANGS and b == HANGS:
        free = "left" if left.wrist.y >= right.wrist.y else "right"
    else:
        free = "left" if a == HANGS else "right" if b == HANGS else ""
    return Arms(left=a, right=b, free=free)


def read_arms(path: str | Path) -> Arms | None:
    """Arms of the most prominent person in the picture; None when nobody is found."""
    os.environ.setdefault("GLOG_minloglevel", "2")
    import cv2
    import mediapipe as mp

    img = cv2.imread(str(path))
    if img is None:
        raise media.MediaError("image could not be read")
    height, width = img.shape[:2]
    # complexity 1 uses the model bundled in the wheel; 2 would download one at run time
    with mp.solutions.pose.Pose(static_image_mode=True, model_complexity=1) as pose:
        found = pose.process(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)).pose_landmarks
    if found is None:
        return None
    lm, P = found.landmark, mp.solutions.pose.PoseLandmark

    def pt(name: str) -> Point:
        q = lm[getattr(P, name)]
        return Point(q.x * width, q.y * height, q.visibility)

    body = [Arm(pt(f"{s}_SHOULDER"), pt(f"{s}_ELBOW"), pt(f"{s}_WRIST")) for s in ("LEFT", "RIGHT")]
    body.sort(key=lambda arm: arm.shoulder.x)  # body sides -> picture sides
    hip_y = (pt("LEFT_HIP").y + pt("RIGHT_HIP").y) / 2
    return arms_from(body[0], body[1], pt("NOSE"), hip_y)
