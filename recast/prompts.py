"""Animate-2 prompts written for the user.

Animate-2 wants two prompts: an appearance prompt ("Character appearance
description: ... / Background description: ...") and a motion prompt. A user
shouldn't have to know that. Both are composed from what the user already
chose (character text, style, scene); a user-written prompt still wins.
"""

from __future__ import annotations

from . import styles


def appearance(*, subject: str, character_text: str = "", style: str = "", scene: str = "keep",
               background: str = "", has_location: bool = False, character2_text: str = "",
               two: bool = False, wearing: str = "", holding: str = "") -> str:
    """`two`: the clip has two performers. With two characters, each is named by its side of the
    picture (measured, duo); without characters, both performers keep their own look."""
    look = styles.get(style).look if style else ""
    if character2_text.strip():
        who = f"on the left, {character_text.strip().rstrip('.')}; on the right, {character2_text.strip().rstrip('.')}"
    elif two:
        who = f"the two {subject}s shown in the reference image"
    else:
        who = character_text.strip().rstrip(".") or f"the {subject} shown in the reference image"
    if wearing.strip():
        who += f", wearing {wearing.strip().rstrip('.')}"
    if holding.strip():
        who += f", holding {holding.strip().rstrip('.')} in one hand"
    if look:
        who += f", drawn as {look}"
    if has_location:
        where = "the place shown in the reference image"
    elif scene == "new" and background.strip():
        where = background.strip().rstrip(".")
    else:
        where = "the same place, light and camera as the reference image"
    if look:
        where += f", drawn as {look}"
    return f"Character appearance description: {who}.\nBackground description: {where}."


def motion(*, subject: str, two: bool = False) -> str:
    if two:
        return ("The two characters perform with the same body movements, gestures and timing as the two "
                "performers in the driving video, each keeping their own place, natural weight and balance.")
    return (f"The {subject} performs with the same body movement, steps, gestures and timing as the "
            f"driving video, natural weight and balance.")
