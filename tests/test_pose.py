"""Arm sides come from geometry, by picture side. Synthetic keypoints, pixels, y grows downward."""
from recast import pose

P = pose.Point


def _arm(sx, sy, ex, ey, wx, wy, wv=1.0):
    return pose.Arm(P(sx, sy, 1), P(ex, ey, 1), P(wx, wy, wv))


NOSE = P(470, 240, 1)
HIP_Y = 780


def test_hand_on_head_and_hanging_arm_measured_frame():
    """The dancer frame: the arm on the picture's left is up at the head, the other hangs out of view."""
    left = _arm(230, 390, 110, 240, 430, 200)
    right = _arm(600, 470, 600, 680, 580, 830, wv=0.07)  # wrist out of frame, elbow below the shoulder
    a = pose.arms_from(left, right, NOSE, HIP_Y)
    assert a.left == "is raised, hand resting on top of the head"
    assert a.right == pose.HANGS
    assert a.free == "right" and a.other() == a.left


def test_both_hanging_picks_the_lower_hand():
    left = _arm(300, 400, 290, 600, 285, 790)
    right = _arm(600, 400, 610, 600, 615, 830)
    assert pose.arms_from(left, right, NOSE, HIP_Y).free == "right"


def test_no_free_hand_means_no_side():
    left = _arm(300, 400, 200, 300, 100, 150)  # raised, well away from the head
    right = _arm(600, 400, 560, 520, 480, 500)  # bent at the chest
    a = pose.arms_from(left, right, NOSE, HIP_Y)
    assert (a.left, a.right, a.free) == ("is raised above the shoulder", "is bent, hand in front of the body at chest height", "")
    assert a.other() == ""


def test_phrases_never_carry_a_side():
    import re
    for text in ("is raised, hand resting on top of the head", "is raised above the shoulder", pose.HANGS,
                 "is bent, hand in front of the body at chest height"):
        assert not re.search(r"(?i)\b(left|right)\b", text)
