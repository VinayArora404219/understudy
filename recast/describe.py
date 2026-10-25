"""Put the clip's first frame into words: who is in it, and what each body is doing.

Measured (bench/RESULTS.md, fix A and duo): Qwen-Image-Edit keeps the clip's
pose only when the pose is spelled out in concrete words. "Take the first
picture's pose" loses to the character picture's pose. Users shouldn't have
to write those words, so the frame is described by Qwen3-VL-8B through
ComfyUI's core TextGenerate node. No custom node. (Qwen-Edit's own
Qwen2.5-VL file is encoder-only and cannot generate text.)

The same description checks the user's answer to "who's in your clip?"
before any edit runs.

Directions: performers are placed by the side of the PICTURE they stand on.
Body parts are never given a left or right (that mirrors, measured); a
clause that does it anyway is dropped rather than trusted. Which arm does
what, by picture side, comes from keypoints instead (recast/pose.py): asked
for it, the model answered body-relative.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


MAX_WORDS = 40

PROMPT = """Look at the picture and list every person or animal in it that is moving or performing.
Reply with JSON only, no other text, in exactly this shape:
{"performers": [{"side": "left", "kind": "animal", "what": "dog", "find": "brown dog", "shot": "whole body", "pose": "...", "body": "..."}]}

Rules:
- "side": where the performer stands in the picture: "left", "right" or "center". With two
  performers, one is "left" and one is "right".
- "kind": "person" or "animal". "what": one or two words, such as "woman", "man", "cat", "dog".
- "find": two to six words that pick this performer out from everyone else in the picture: "what" with
  the colour of their main garment, or their fur colour, such as "man in a grey suit", "woman in a red
  dress", "black and white cat". It is the only field that names clothes or colours.
- "shot": how much of the performer the picture shows: "whole body", "knees up", "waist up" or
  "head and shoulders".
- "pose": one sentence, at most 30 words, starting with a verb, describing only the body: standing,
  sitting, leaning or crouching; where the head faces; where the hands are and what they touch.
  Call front paws "hands". Say "both hands" when both do the same thing.
- "body": the same pose with no objects named, only the body: how it leans, where the head faces, where
  the hands are ("low in front", "raised above the head"). It is used to pose someone in another room.
- Never say left or right about a body part ("left arm", "her right hand"). Place hands by what
  they touch or where they are: "one hand on top of the head", "both hands on the keyboard".
- Outside "find", do not describe clothes, colours, faces, the room, or the camera.
Example pose: "stands upright, leans back slightly, one hand on top of the head, face tilted up"."""

def prompt_for(count: int) -> str:
    """The reader when the visitor has chosen who is recast: exactly those, never a passer-by.

    Measured: asked for "every person moving or performing", it described a small walker in the background
    and skipped the man standing still in front, who was the one chosen."""
    who = "one performer: the largest person or animal" if count == 1 else \
        f"{count} performers: the {count} largest people or animals"
    first, rest = PROMPT.split("\n", 1)
    return (f"Look at the picture. It shows exactly {who} in front. Anyone greyed out, small or in the "
            f"background is not a performer: leave them out.\n{rest}")


# Any left/right that belongs to a body, not to the picture: "left arm", "her right", "turned slightly left".
BODY_SIDE = re.compile(r"\b(left|right)\s+(arm|hand|leg|foot|paw|shoulder|elbow|knee|hip|side|ear|eye)s?\b"
                       r"|\b(her|his|its|their)\s+(left|right)\b"
                       r"|\b(turn|tilt|face|look|lean|point)\w*\s+(\w+\s+)?(to\s+the\s+)?(left|right)\b", re.I)


def _clean_pose(text: str) -> str:
    """Drop each clause that gives a body a side; keep the rest. Too long a sentence is dropped whole."""
    clauses = [c.strip() for c in " ".join(text.split()).rstrip(".").split(",")]
    kept = [c for c in clauses if c and not BODY_SIDE.search(c)]
    pose = ", ".join(kept)
    return pose if len(pose.split()) <= MAX_WORDS else ""


def _clean_find(text: str) -> str:
    """A tracker phrase: short, lower case, no sides (a side names the picture, not the performer)."""
    words = re.sub(r"[^\w\s-]", " ", text.lower()).split()
    return "" if not 2 <= len(words) <= 6 or {"left", "right"} & set(words) else " ".join(words)


SHOTS = ("whole body", "knees up", "waist up", "head and shoulders")


@dataclass(frozen=True)
class Performer:
    side: str  # left | right | center
    kind: str  # person | animal
    what: str
    pose: str  # clauses that gave a body a side are removed
    shot: str = ""  # one of SHOTS, "" when the reply gave something else
    body: str = ""  # the pose without the objects it touches, for posing someone in another place
    find: str = ""  # "man in a grey suit": what the tracker follows, so a crowd's other men are left alone


VLM = "qwen3vl_8b_int8_convrot.safetensors"


# One description per uploaded image, by the role it plays. Identity is carried by these words (measured:
# two characters both described as "tall man, short curly hair, red jacket" came out as two such men).
ROLE_PROMPTS = {
    "character": ("Describe the main person or character in this picture so an artist could redraw them, in one "
                  "line of at most 30 words: apparent age and gender, build, face shape, skin tone, hair colour "
                  "and style, facial hair, glasses, and every clothing item they wear with its colour, including hats. "
                  "Only what is on their body: never an object beside them or on a table, even one that matches "
                  "their clothes. Only what they have, never what they lack. No background, no pose, no names, "
                  "no brand names, no left or right. Reply with the line only."),
    "outfit": ("Name the garment or outfit in this picture in at most 12 words: what it is, colour, material and "
               "notable details. No brand names. Reply with the words only, starting with \"a\"."),
    "product": ("Name the object in this picture in at most 12 words: what it is, colour, material and shape. "
                "No brand names. Reply with the words only, starting with \"a\"."),
    # Restyle: who and where, for the video-to-video prompt (recast/vace.py), read from a 2x2 sheet of four
    # moments of the clip (media.moments_sheet). A depth map can't see small things against the body, so
    # what a performer puts on or picks up later must be named (measured: sunglasses vanished). Background
    # events must NOT be: a line that named a passing cyclist got one drawn big in the foreground, too early.
    "scene": ("This picture shows four moments of one video, in order, in a 2x2 grid. In one line of at most 60 "
              "words, so an artist could redraw the video: each person or animal with apparent age, hair and every "
              "clothing item with its colour; then the place; then anything a person or animal puts on, takes "
              "off or picks up during the video, such as \"later puts on dark sunglasses\". Do not mention passers-by, "
              "traffic or anything else that moves in the background. Describe one video, not four pictures. No "
              "names, no brand names, no left or right. Reply with the line only."),
    # Swap: what the performer wears below the waist, read over four moments of the clip, because the first
    # frame often doesn't show it (a selfie start). Without these words the render invented trousers.
    "lower": ("This picture shows four moments of one video, in a 2x2 grid. In at most 10 words, name what the "
              "main person wears below the waist and on their feet, with colours, such as \"blue jeans and white "
              "trainers\". Only what you can see. No brand names, no left or right. Reply with the words only. If "
              "nothing below the waist is in view, reply: none"),
}
ROLE_WORDS = {"character": 30, "outfit": 12, "product": 12, "scene": 65, "lower": 12}
MAX_SCENE = 500  # characters a visitor may write when they correct the scene line


def build(frame: Any, *, prefix: str = "recast/describe", prompt: str = PROMPT,
          max_length: int = 400) -> dict[str, dict[str, Any]]:
    """The first-frame reader; with `prompt` (see ROLE_PROMPTS) the same graph describes one image."""
    return {
        # A loader type that no image model claims selects ComfyUI's plain Qwen3-VL, which can generate.
        "clip": {"class_type": "CLIPLoader", "inputs": {"clip_name": VLM, "type": "stable_diffusion",
                                                         "device": "default"}},
        "frame": {"class_type": "LoadImage", "inputs": {"image": frame}},
        "frame_rs": {"class_type": "FluxKontextImageScale", "inputs": {"image": ["frame", 0]}},
        "gen": {"class_type": "TextGenerate",
                "inputs": {"clip": ["clip", 0], "prompt": prompt, "image": ["frame_rs", 0],
                           "max_length": max_length, "sampling_mode": "off"}},  # greedy: same picture, same words
        "save": {"class_type": "SaveText", "inputs": {"text": ["gen", 0], "filename_prefix": prefix,
                                                      "format": "txt"}},
    }


FINAL_NODE = "save"


def parse(text: str) -> list[Performer]:
    """Read the model's reply. Tolerates prose or code fences around the JSON."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("the description has no JSON in it")
    data = json.loads(m.group(0))
    out = []
    for p in data.get("performers") or []:
        side = str(p.get("side", "center")).lower()
        kind = str(p.get("kind", "")).lower()
        pose = _clean_pose(str(p.get("pose", "")))  # a mirrored or rambling pose is worse than none
        out.append(Performer(side=side if side in ("left", "right", "center") else "center",
                             kind=kind if kind in ("person", "animal") else "person",
                             what=str(p.get("what", "")).strip().lower()[:30], pose=pose,
                             shot=shot if (shot := str(p.get("shot", "")).strip().lower()) in SHOTS else "",
                             body=_clean_pose(str(p.get("body", ""))), find=_clean_find(str(p.get("find", "")))))
    if len(out) == 2:  # order by side so [0] is always the one on the picture's left
        out.sort(key=lambda q: {"left": 0, "center": 1, "right": 2}[q.side])
    return out


def build_role(image: Any, role: str, *, prefix: str = "recast/describe_image") -> dict[str, dict[str, Any]]:
    return build(image, prefix=prefix, prompt=ROLE_PROMPTS[role], max_length=120)


# "no glasses", "without a hat", "not wearing a tie": a prompt can't say what isn't there, it only adds the
# word. Measured: a character worded "no glasses ... with matching helmet" put on a helmet where the clip's
# performer put on sunglasses.
_NEGATION = re.compile(r"(?i)^(no|without|not wearing|not)\b")
_INLINE_NEGATION = re.compile(r"(?i)\s+(?:and|with)\s+no\s+[^,]*|\s+without\s+[^,]*")


def drop_negations(text: str) -> str:
    """The text without anything said to be absent: whole clauses ("no glasses") and tails ("with no hat")."""
    parts = [_INLINE_NEGATION.sub("", c).strip() for c in text.split(",")]
    return ", ".join(c for c in parts if c and not _NEGATION.match(c))


# A reply about the picture instead of clothes: what is below the waist isn't in view.
NOT_SEEN = re.compile(r"(?i)^none$|\b(image|picture|photo|frame|visible|in view|upper body|cannot|can't|unable)\b")


def parse_role(text: str, role: str) -> str:
    """One clean line: no quotes or labels, no sides, nothing said to be absent, no more words than the role
    allows."""
    line = next((ln for ln in text.strip().splitlines() if ln.strip()), "")
    line = re.sub(r"^\s*(description|answer|outfit|product|character|scene)\s*:\s*", "", line, flags=re.I)
    line = line.strip().strip('"\'`*').rstrip(".")
    if role == "lower" and NOT_SEEN.search(line):  # measured: "The image shows only the upper body of the person.
        return ""  # Nothing below" went into the render prompt as clothes
    line = ", ".join(c.strip() for c in line.split(",") if c.strip() and not re.search(r"(?i)\b(left|right)\b", c))
    return " ".join(drop_negations(line).split()[:ROLE_WORDS[role]])


def mismatch(found: list[Performer], *, performers: int, subject: str) -> str | None:
    """A sentence for the visitor when the clip doesn't hold what the job needs, else None. Only jobs without
    chosen performers get here (Swap's outfit and product need one person), so it names the need, not a
    question on the page."""
    if not found:
        return None  # nothing recognised: let the preview show what happens rather than block
    names = " and ".join(f"a {p.what or p.kind}" for p in found)
    if len(found) > 2:
        return f"We see {len(found)} performers in this clip. Up to two performers for now: trim or crop the clip."
    want = ("one " if performers == 1 else "two ") + {("person", 1): "person", ("person", 2): "people",
                                                      ("animal", 1): "animal", ("animal", 2): "animals"}[subject, performers]
    if len(found) != performers:
        n = "one performer" if len(found) == 1 else "two performers"
        return f"We see {n} in this clip ({names}), but this needs {want}. Try a clip with {want} in view."
    if any(p.kind != subject for p in found):
        return f"We see {names} in this clip, but this needs {want}. Try a clip with {want} in view."
    return None
