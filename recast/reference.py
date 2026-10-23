"""Automatic reference matching.

Animate-2 animates whoever is in the reference image and takes identity,
framing and background from it. A reference whose pose and framing differ
from the clip's first frame costs quality (tighter crop, colour drift, a
blank background at the start). Users don't know that rule, and shouldn't
have to.

So the reference is built, not uploaded, by Qwen-Image-Edit-2511. Its image1
is the latent: the result's room, light and camera come from it, and nothing
else reliably does. So image1 is the one picture whose place the result is in
(`base`), and every other image is content only:

    base="frame"      the clip's first frame: pose, framing and room as filmed
    base="character"  the character's own photo: the result is in their place
    base="location"   a place image: the result is in that place

    character  -> who stands where the performer stands
    location   -> the place the scene moves to (base="frame" only)
    style      -> a preset look the whole picture is redrawn in (no image)

With base="character" or "location" the clip frame is not an input at all
(its room would leak in): the performers' positions, framing and poses are
given as words, read from the frame by recast/describe.py. That is the
measured recipe that put two cats dancing in one cat's kitchen.

Any non-empty combination works: a character alone, a style alone
("restyle my video"), a character in a new place, a character in a style.
Without a location, scene="keep" leaves the performer's own room and
scene="new" replaces it with the `background` text.

Prompt rules from measured runs: say what changes, not what to keep (a
preservation list freezes the edit); never use body-relative directions
("her left") — they mirror.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from . import styles

UNET = "qwen-image-edit-2511-Q4_K_M.gguf"
TEXT_ENCODER = "qwen_2.5_vl_7b_fp8_scaled.safetensors"
VAE = "qwen_image_vae.safetensors"
LIGHTNING = "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors"
BG_REMOVAL = "birefnet.safetensors"
CUTOUT_GREY = 0x808080  # fallback backdrop when the scene's own colour is unknown

MAX_TEXT = 400
SUBJECTS = ("person", "dancer", "performer", "cat", "dog", "animal")

BASES = ("frame", "character", "location")
SHOT_WORDS = {"whole body": "the whole body in view from head to feet", "knees up": "seen from the knees up",
              "waist up": "seen from the waist up", "head and shoulders": "seen head and shoulders"}
WHERE = {"left": "On the left of the frame", "right": "On the right of the frame",
         "center": "In the middle of the frame"}

NEGATIVE = ("two characters, extra person, duplicate, mirrored, flipped, cropped body, cut-off feet, "
            "text, watermark, logo, blurry, deformed hands, extra limbs")


class ReferenceError(ValueError):
    pass


@dataclass
class MatchParams:
    frame: Any  # clip's first frame: filename or SDK asset handle
    character: Any = None  # user's character image (with two performers: the one on the picture's left)
    character_text: str = ""  # short identity description: shape, build, colours, clothing
    character2: Any = None  # second character, for the performer on the picture's right
    character2_text: str = ""
    pose: str = ""  # optional, concrete, frame-relative words for what the (left) performer's body does
    pose2: str = ""  # the same for the performer on the right
    outfit: Any = None  # swap: a garment the performer now wears
    outfit_text: str = ""
    product: Any = None  # swap: an object the performer now holds
    product_text: str = ""
    product_hand: str = ""  # "left" | "right": the side of the picture of the hand that stays in view
    other_hand: str = ""  # what the arm on the other side of the picture does, e.g. "is raised, hand on the head"
    location: Any = None  # image of the place to move the scene to
    base: str = "frame"  # which picture is image1, so whose place the result is in: see BASES
    side: str = ""  # with base != "frame": where the (left) performer stands, "left" | "right" | "center"
    shot: str = ""  # ... and how much of them the clip shows, a key of describe.SHOTS
    shot2: str = ""
    props: str = ""  # with base != "frame": what the performers handle in the clip, brought into the new place
    # The result's background comes from one source only: image1, a place image or the words.
    # Every other image is cut out onto plain grey first; a prompt can't stop a busy photo's set leaking in.
    cutout: bool = True
    # The backdrop under each cut-out. Measured: a grey backdrop leaked in as the room's colour, so callers
    # pass the first frame's own background colour (media.edge_colour) and a leak blends into the room.
    cutout_colour: int = CUTOUT_GREY
    style: str = ""  # a key of styles.STYLES
    subject: str = "person"
    scene: str = "keep"
    background: str = ""
    quality: str = "fast"  # fast = 4-step Lightning (~20 s), high = 20 steps cfg 3 (~2 min)
    seed: int = 1
    prefix: str = "recast/reference"

    def validate(self) -> None:
        if self.subject not in SUBJECTS:
            raise ReferenceError(f"subject must be one of {SUBJECTS}")
        if self.scene not in ("keep", "new"):
            raise ReferenceError("scene must be 'keep' or 'new'")
        if self.quality not in ("fast", "high"):
            raise ReferenceError("quality must be 'fast' or 'high'")
        if self.style and self.style not in styles.STYLES:
            raise ReferenceError(f"style must be one of {sorted(styles.STYLES)}")
        if self.character is not None and not self.character_text.strip():
            raise ReferenceError("describe the character")
        if self.character is None and self.character_text.strip():
            raise ReferenceError("a character description needs a character image")
        if self.character2 is not None and self.character is None:
            raise ReferenceError("a second character needs a first one")
        if self.character2 is not None and not self.character2_text.strip():
            raise ReferenceError("describe the second character")
        if self.character2 is None and (self.character2_text.strip() or self.pose2.strip()):
            raise ReferenceError("a second description or pose needs a second character image")
        if self.base not in BASES:
            raise ReferenceError(f"base must be one of {BASES}")
        if self.base == "frame" and self.frame is None:
            raise ReferenceError("base='frame' needs the clip's first frame")
        if self.base != "frame":
            if self.character is None:
                raise ReferenceError("moving to another place recasts the performer: give a character")
            if getattr(self, self.base) is None:
                raise ReferenceError(f"base='{self.base}' needs the {self.base} image")
            if self.base == "character" and self.location is not None:
                raise ReferenceError("the result is in one place: the character's or the location image's")
            if self.scene == "new":
                raise ReferenceError("the place comes from the base image: scene must be 'keep'")
        if self.side not in ("", "left", "right", "center"):
            raise ReferenceError("side must be left, right or center")
        for shot in (self.shot, self.shot2):
            if shot and shot not in SHOT_WORDS:
                raise ReferenceError(f"shot must be one of {sorted(SHOT_WORDS)}")
        if (self.outfit is not None or self.product is not None) and self.character is not None:
            raise ReferenceError("an outfit or product swap keeps the performer: it can't be combined with a character")
        if self.outfit is not None and self.product is not None:
            raise ReferenceError("swap one thing at a time: an outfit or a product")
        for img, text, name in ((self.outfit, self.outfit_text, "outfit"), (self.product, self.product_text, "product")):
            if img is not None and not text.strip():
                raise ReferenceError(f"describe the {name}")
        if self.other_hand and not self.product_hand:
            raise ReferenceError("other_hand needs product_hand")
        if self.product_hand not in ("", "left", "right"):
            raise ReferenceError("product_hand must be 'left' or 'right'")
        if len(slots(self)) > 2:
            raise ReferenceError("two characters and a place image don't fit in one edit: drop the place image")
        if self.scene == "new" and self.location is None and not self.background.strip():
            raise ReferenceError("describe the new background or give a location image")
        if (self.character is None and self.location is None and self.outfit is None and self.product is None
                and not self.style and self.scene == "keep"):
            raise ReferenceError("nothing to change: give a character, a location, a style or a new background")
        if self.props.strip() and self.base == "frame":
            raise ReferenceError("props are for another place: the clip's own frame already has them")
        for name in ("character_text", "character2_text", "pose", "pose2", "props", "outfit_text", "product_text", "other_hand",
                     "background"):
            if len(getattr(self, name)) > MAX_TEXT:
                raise ReferenceError(f"{name} is over {MAX_TEXT} characters")
        if not 0 <= self.cutout_colour <= 0xFFFFFF:
            raise ReferenceError("cutout_colour must be 0xRRGGBB")
        if not 0 <= self.seed < 2**48:
            raise ReferenceError("seed out of range")


ORDINAL = {2: "second", 3: "third"}


def base_image(p: MatchParams) -> Any:
    return p.frame if p.base == "frame" else getattr(p, p.base)


def slots(p: MatchParams) -> dict[str, int]:
    """Which image slot each content-only input occupies (image1 is the base)."""
    out, n = {}, 2
    for name in ("character", "character2", "outfit", "product", "location"):
        if getattr(p, name) is not None and name != p.base:
            out[name] = n
            n += 1
    return out


def _clause(text: str) -> str:
    return text.strip().rstrip(".")


def _noun(text: str) -> str:
    """"a red jacket" -> "red jacket", for "the ... shown in the second picture"."""
    return re.sub(r"(?i)^(a|an|the)\s+", "", _clause(text))


def _prompt_elsewhere(p: MatchParams) -> str:
    """base != "frame": the clip isn't in the edit, so who stands where and how is said in words.
    Measured (cat dance): place each by the side of the frame, name the picture each comes from,
    spell out the pose and how much of the body shows, and give the exact count."""
    sl = slots(p)

    def nth(name: str) -> str:
        return "first" if name == p.base else ORDINAL[sl[name]]

    two = p.character2 is not None
    people = "people" if p.subject == "person" else p.subject + "s"
    # Measured: without a one-scene opening, two characters from two pictures came back as a split-screen
    # diptych, one panel each. The cat-dance prompt that worked opened like this.
    parts = ["One single photograph of one continuous scene in the place of the first picture"
             + (f": two {people} side by side in the same room." if two else ".")]
    cast = [("character", p.character_text, "left" if two else (p.side or "center"), p.shot, p.pose)]
    if two:
        cast.append(("character2", p.character2_text, "right", p.shot2, p.pose2))
    for name, text, side, shot, pose in cast:
        parts.append(f"{WHERE[side]}, the {p.subject} from the {nth(name)} picture: {_clause(text)}.")
        body = ", ".join(x for x in (_clause(pose), SHOT_WORDS.get(shot, "")) if x)
        if body:
            parts.append(f"This {p.subject} {body}.")
    if p.props.strip():  # without them the performers mime at nothing in the new place
        parts.append(f"In front of them, as in the video: {_clause(p.props)}.")
    if two:
        parts.append(f"Exactly two {people}, one on the left and one on the right, not a split screen.")
    others = [nth(name) for name, *_ in cast if name != p.base]
    if others:
        parts.append(f"Use the {' and '.join(others)} picture{'s' if len(others) > 1 else ''} only for faces "
                     f"and clothing, not pose or place.")
    parts.append("The scene stays in the place of the first picture, in its light." if p.base == "character" else
                 "The scene is the place shown in the first picture, in its light.")
    if p.style:
        parts.append(f"Redraw the whole picture as {styles.get(p.style).edit}.")
    return " ".join(parts)


def prompt_for(p: MatchParams) -> str:
    if p.base != "frame":
        return _prompt_elsewhere(p)
    sl = slots(p)
    parts = []
    if "character2" in sl:
        # Measured (duo): each character named by its side OF THE PICTURE, each pose spelled out,
        # both character pictures used only for faces and clothing.
        n1, n2 = ORDINAL[sl["character"]], ORDINAL[sl["character2"]]
        parts.append(f"Replace the {p.subject} on the left of the first picture with the character from the {n1} "
                     f"picture: {_clause(p.character_text)}. Replace the {p.subject} on the right of the first "
                     f"picture with the character from the {n2} picture: {_clause(p.character2_text)}.")
        if p.pose.strip():
            parts.append(f"The character on the left {_clause(p.pose)}.")
        if p.pose2.strip():
            parts.append(f"The character on the right {_clause(p.pose2)}.")
        parts.append(f"Each character takes the size and position of the {p.subject} it replaces; use the {n1} and "
                     f"{n2} pictures only for faces and clothing, not pose. Two characters, side by side.")
    elif "character" in sl:
        # Measured (t3): "same pose" alone was read as the character picture's pose. Say which picture
        # owns the pose and size, and that the character picture gives only the look.
        nth = ORDINAL[sl["character"]]
        parts.append(f"Replace the {p.subject} in the first picture with the character from the {nth} picture: "
                     f"{_clause(p.character_text)}. The character takes exactly the body pose, "
                     f"size and position of the {p.subject} in the first picture; use the {nth} picture "
                     f"only for its look, not its pose.")
        if p.pose.strip():  # fix A: concrete pose words beat the abstract instruction above
            parts.append(f"The character {_clause(p.pose)}.")
    if "outfit" in sl:
        parts.append(f"The {p.subject} in the first picture now wears the {_noun(p.outfit_text)} shown in the "
                     f"{ORDINAL[sl['outfit']]} picture, fitted to their body.")
    if "product" in sl:
        # Measured (V5b): the product goes in the hand the performer keeps in view, placed by the
        # side of the picture; elsewhere it vanishes once its hand leaves the frame.
        # Both arms are named by picture side (V5b): naming only the holding arm let the edit swap them.
        noun, nth = _noun(p.product_text), ORDINAL[sl["product"]]
        if p.product_hand:
            other = "left" if p.product_hand == "right" else "right"
            if p.other_hand.strip():
                parts.append(f"The {p.subject}'s arm on the {other} side of the picture {_clause(p.other_hand)}, "
                             f"exactly as in the first picture.")
            parts.append(f"The {p.subject}'s arm on the {p.product_hand} side of the picture hangs down by the hip "
                         f"as in the first picture, and that hand now holds the {noun} shown in the {nth} picture, "
                         f"the {noun} hanging down at the side.")  # "beside the thigh" bared a thigh (measured)
        else:
            parts.append(f"The {p.subject} in the first picture now holds the {noun} shown in the {nth} picture "
                         f"in one hand.")
    if ("outfit" in sl or "product" in sl) and p.pose.strip():
        parts.append(f"The {p.subject} {_clause(p.pose)}.")  # the item instruction pushes out an abstract pose
    if "location" in sl:
        parts.append(f"Move the scene to the place shown in the {ORDINAL[sl['location']]} picture.")
    elif p.scene == "new":
        parts.append(f"Change the background to {p.background.strip().rstrip('.')}.")
    if p.style:
        parts.append(f"Redraw the whole picture as {styles.get(p.style).edit}.")
    # Not "whole body in frame": a waist-up clip then gets a full-body reference (measured, h3b).
    parts.append("Same pose, same camera and framing as the first picture.")
    return " ".join(parts)


def build(p: MatchParams) -> dict[str, dict[str, Any]]:
    p.validate()
    fast = p.quality == "fast"
    g: dict[str, dict[str, Any]] = {
        "unet": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": UNET}},
        "clip": {"class_type": "CLIPLoader", "inputs": {"clip_name": TEXT_ENCODER, "type": "qwen_image",
                                                         "device": "default"}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "base": {"class_type": "LoadImage", "inputs": {"image": base_image(p)}},  # image1: whose place
        "base_rs": {"class_type": "FluxKontextImageScale", "inputs": {"image": ["base", 0]}},
        "shift": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["unet", 0], "shift": 3.1}},
        "norm": {"class_type": "CFGNorm", "inputs": {"model": ["shift", 0], "strength": 1, "pre_cfg": False}},
        "pos": {"class_type": "TextEncodeQwenImageEditPlus",
                "inputs": {"clip": ["clip", 0], "vae": ["vae", 0], "image1": ["base_rs", 0],
                           "prompt": prompt_for(p)}},
        "neg": {"class_type": "TextEncodeQwenImageEditPlus",
                "inputs": {"clip": ["clip", 0], "vae": ["vae", 0], "image1": ["base_rs", 0],
                           "prompt": NEGATIVE if not fast else ""}},
        "pos_m": {"class_type": "FluxKontextMultiReferenceLatentMethod",
                  "inputs": {"conditioning": ["pos", 0], "reference_latents_method": "index_timestep_zero"}},
        "neg_m": {"class_type": "FluxKontextMultiReferenceLatentMethod",
                  "inputs": {"conditioning": ["neg", 0], "reference_latents_method": "index_timestep_zero"}},
        "latent": {"class_type": "VAEEncode", "inputs": {"pixels": ["base_rs", 0], "vae": ["vae", 0]}},
        "sample": {"class_type": "KSampler",
                   "inputs": {"model": ["norm", 0], "positive": ["pos_m", 0], "negative": ["neg_m", 0],
                              "latent_image": ["latent", 0], "seed": p.seed,
                              "steps": 20, "cfg": 3.0, "sampler_name": "euler", "scheduler": "simple",
                              "denoise": 1.0}},
        "decode": {"class_type": "VAEDecode", "inputs": {"samples": ["sample", 0], "vae": ["vae", 0]}},
        "save": {"class_type": "SaveImage", "inputs": {"images": ["decode", 0], "filename_prefix": p.prefix}},
    }
    for name, n in slots(p).items():  # content-only images: identity, place
        g[name] = {"class_type": "LoadImage", "inputs": {"image": getattr(p, name)}}
        src = [name, 0]
        if p.cutout and name != "location":  # all core nodes: matte, then paste onto plain grey
            g.setdefault("bg_model", {"class_type": "LoadBackgroundRemovalModel", "inputs": {"bg_removal_name": BG_REMOVAL}})
            g[f"{name}_matte"] = {"class_type": "RemoveBackground",
                                  "inputs": {"bg_removal_model": ["bg_model", 0], "image": [name, 0]}}
            g[f"{name}_size"] = {"class_type": "GetImageSize", "inputs": {"image": [name, 0]}}
            g[f"{name}_grey"] = {"class_type": "EmptyImage",
                                 "inputs": {"width": [f"{name}_size", 0], "height": [f"{name}_size", 1],
                                            "batch_size": 1, "color": p.cutout_colour}}
            g[f"{name}_cut"] = {"class_type": "ImageCompositeMasked",
                                "inputs": {"destination": [f"{name}_grey", 0], "source": [name, 0], "x": 0, "y": 0,
                                           "resize_source": False, "mask": [f"{name}_matte", 0]}}
            src = [f"{name}_cut", 0]
        g[f"{name}_rs"] = {"class_type": "FluxKontextImageScale", "inputs": {"image": src}}
        for enc in ("pos", "neg"):
            g[enc]["inputs"][f"image{n}"] = [f"{name}_rs", 0]
    if fast:  # 4-step distilled: cfg 1 makes the negative inert, hence the empty one above
        g["lora"] = {"class_type": "LoraLoaderModelOnly",
                     "inputs": {"model": ["norm", 0], "lora_name": LIGHTNING, "strength_model": 1}}
        g["sample"]["inputs"].update(model=["lora", 0], steps=4, cfg=1.0)
    return g


FINAL_NODE = "save"
