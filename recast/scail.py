"""SCAIL-2: recast the clip's performers by motion alone, in the clip's place or in another.

SCAIL-2 (zai-org, MIT, Wan2.1 14B) is driven end to end, without a skeleton, so a dog or a cat can drive a
person (measured: bench/RESULTS.md, "SCAIL-2"). It has two modes, which are the two places a recast can be in:

    replace=True   the clip's place. The clip is the pose video and its room is the input; SAM3 tracks the
                   performers and only they are redrawn, from the reference.
    replace=False  another place. The reference picture is the room (the character's own photo, or a start
                   picture with the cast in it); the clip lends only its motion.

All identities go on ONE reference picture, left to right; SCAIL2ColoredMask colours the clip's performers
and the reference's characters left to right, so the leftmost performer becomes the leftmost character.

The graph is Comfy's "Character Replacement (SCAIL-2 Base/Extend)" blueprints, unrolled: 81-frame chunks,
each one after the first anchored on the previous chunk's last 5 frames, its overlap dropped and its
colour matched to the previous chunk. Core nodes only, plus the GGUF loader.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import describe, graph, keep

UNET = "SCAIL-2-Q4_K_M.gguf"
DPO = "wan2.1_SCAIL_2_DPO_lora_bf16.safetensors"
LIGHTX2V = "lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors"
SAM3 = "sam3.1_multiplex_fp16.safetensors"

CHUNK = 81  # frames per chunk, as trained
OVERLAP = 5  # previous frames each later chunk is anchored on
STRIDE = CHUNK - OVERLAP
STEPS = 6  # with the lightx2v distill LoRA, cfg 1 (the blueprint's fast setting)
MAX_CHUNKS = 4
MAX_TEXT = 1200
# People recast in one clip. SCAIL-2 tells identities apart by mask colour and was trained on a palette of six
# (comfy_extras/nodes_scail.py); we offer four, so each still has some of the 480p frame for a face.
MAX_PEOPLE = 4


MODELS = [  # for recipe.json: every weight file in the graph, with its source and terms
    {"role": "video model", "file": UNET, "upstream": "zai-org/SCAIL-2 (realrebelai GGUF Q4_K_M)", "license": "MIT"},
    {"role": "lora", "file": DPO, "upstream": "zai-org/SCAIL-2 DPO (Comfy-Org repack)", "license": "MIT"},
    {"role": "lora", "file": LIGHTX2V, "upstream": "lightx2v/Wan2.1-I2V-14B-480P-StepDistill-CfgDistill",
     "license": "Apache-2.0"},
    {"role": "segmentation", "file": SAM3, "upstream": "facebook/sam3.1 (Comfy-Org repack)",
     "license": "SAM License (Meta)"},
    {"role": "text encoder", "file": graph.TEXT_ENCODER, "upstream": "google/umt5-xxl (Comfy fp8 repack)",
     "license": "Apache-2.0"},
    {"role": "vae", "file": graph.VAE, "upstream": "Wan-AI/Wan2.1", "license": "Apache-2.0"},
    {"role": "image encoder", "file": graph.CLIP_VISION, "upstream": "open-clip ViT-H/14 (Comfy repack)",
     "license": "MIT"},
]


class ScailError(ValueError):
    pass


def frames_for(chunks: int) -> int:
    return CHUNK + STRIDE * (chunks - 1)


def lengths_for(frames: int) -> list[int]:
    return graph.chunk_lengths(frames, chunk=CHUNK, overlap=OVERLAP)


@dataclass
class ScailParams:
    drive: Any  # normalised clip: render size, 16 fps, at least frames_for(chunks) frames
    reference: Any  # all identities on one picture, left to right (replace) or the start picture (animate)
    prompt: str
    track: str  # what SAM3 follows in the clip, e.g. "dog, cat" or "person"
    people: int
    replace: bool
    layout: str
    chunks: int = 1
    frames: int = 0  # the video's length; 0: whole chunks. Otherwise the last chunk is as short as it can be
    seed: int = 1
    prefix: str = "recast/scail"
    unet: str = UNET
    picks: list[Any] | None = None  # one first-frame mask per chosen performer, left to right (recast/people.py)
    # with picks in the clip's place: points inside each pick, where SAM finds the new character in the render
    # for keeping the clip as filmed around them (recast/keep.py; the composite itself is recast/composite.py)
    keep_points: list[list[list[int]]] | None = None
    others: list[Any] | None = None  # start masks of everyone not recast: always kept as filmed

    def lengths(self) -> list[int]:
        return lengths_for(self.frames or frames_for(self.chunks))

    def validate(self) -> None:
        if self.layout not in graph.SIZES:
            raise ScailError(f"layout must be one of {sorted(graph.SIZES)}")
        if not 1 <= self.chunks <= MAX_CHUNKS:
            raise ScailError(f"chunks must be 1..{MAX_CHUNKS}")
        if self.frames and len(lengths_for(self.frames)) != self.chunks:
            raise ScailError(f"{self.frames} frames don't make {self.chunks} chunks")
        if not 1 <= self.people <= MAX_PEOPLE:
            raise ScailError(f"1 to {MAX_PEOPLE} people")
        if not self.prompt.strip() or len(self.prompt) > MAX_TEXT:
            raise ScailError(f"the prompt must be 1..{MAX_TEXT} characters")
        if self.picks is not None and len(self.picks) != self.people:
            raise ScailError("one chosen performer per character")
        if self.keep_points is not None and (self.picks is None or not self.replace
                                             or not 1 <= len(self.keep_points) <= self.people):
            raise ScailError("keeping the clip needs the chosen performers, in the clip's place")
        if self.picks is None and (not self.track.strip() or len(self.track) > 60):
            raise ScailError("say what to track in the clip, in a few words")
        if not 0 <= self.seed <= graph.MAX_SEED - MAX_CHUNKS:  # each chunk samples with seed + its index
            raise ScailError("seed out of range")


def size(layout: str) -> tuple[int, int]:
    """SCAIL-2 wants both sides divisible by 32."""
    w, h = graph.SIZES[layout]
    return w // 32 * 32, h // 32 * 32


def build(p: ScailParams) -> dict[str, dict[str, Any]]:
    p.validate()
    w, h = size(p.layout)
    lengths = p.lengths()
    g: dict[str, dict[str, Any]] = {}

    def n(key: str, cls: str, **inputs: Any) -> str:
        g[key] = {"class_type": cls, "inputs": inputs}
        return key

    n("video", "LoadVideo", file=p.drive)
    n("parts", "GetVideoComponents", video=["video", 0])
    n("ref", "LoadImage", image=p.reference)
    n("sam", "CheckpointLoaderSimple", ckpt_name=SAM3)
    n("ref_words", "CLIPTextEncode", clip=["sam", 1], text="person")
    n("ref_track", "SAM3_VideoTrack", images=["ref", 0], model=["sam", 0], conditioning=["ref_words", 0],
      detection_threshold=0.5, max_objects=p.people, detect_interval=1)
    n("unet", "UnetLoaderGGUF", unet_name=p.unet)
    n("dpo", "LoraLoaderModelOnly", model=["unet", 0], lora_name=DPO, strength_model=1.0)
    n("fast", "LoraLoaderModelOnly", model=["dpo", 0], lora_name=LIGHTX2V, strength_model=0.8)
    n("shift", "ModelSamplingSD3", model=["fast", 0], shift=5.0)
    n("clip", "CLIPLoader", clip_name=graph.TEXT_ENCODER, type="wan", device="default")
    n("pos", "CLIPTextEncode", clip=["clip", 0], text=p.prompt)
    n("neg", "CLIPTextEncode", clip=["clip", 0], text="")
    n("vae", "VAELoader", vae_name=graph.VAE)
    n("cv", "CLIPVisionLoader", clip_name=graph.CLIP_VISION)
    n("cv_ref", "CLIPVisionEncode", clip_vision=["cv", 0], image=["ref", 0], crop="none")
    # as in the blueprint: the schedule comes from the model before the shift node
    n("sigmas", "BasicScheduler", model=["fast", 0], scheduler="simple", steps=STEPS, denoise=1.0)
    n("sampler", "KSamplerSelect", sampler_name="euler")

    if p.picks is not None:
        # The chosen performers, tracked once over the whole clip from their first-frame masks and no words:
        # SAM3 follows those individuals by look and motion, and one track can't swap people between chunks.
        for k, pick in enumerate(p.picks):
            n(f"pick{k}", "LoadImage", image=pick)
        start = "pick0"
        for k in range(1, len(p.picks)):
            start = n(f"picks{k}", "ImageBatch", image1=[start, 0], image2=[f"pick{k}", 0])
        n("start_masks", "ImageToMask", image=[start, 0], channel="red")
        n("clip_frames", "ImageFromBatch", image=["parts", 0], batch_index=0,
          length=graph.covered(lengths, chunk=CHUNK, overlap=OVERLAP))
        n("track", "SAM3_VideoTrack", images=["clip_frames", 0], model=["sam", 0], initial_mask=["start_masks", 0],
          detection_threshold=0.5, max_objects=p.people, detect_interval=1)
        n("masks", "SCAIL2ColoredMask", driving_track_data=["track", 0], ref_track_data=["ref_track", 0],
          object_indices="", sort_by="left_to_right", replacement_mode=p.replace)
    else:
        n("drive_words", "CLIPTextEncode", clip=["sam", 1], text=p.track)

    joined = prev = ""  # everything so far; the previous chunk alone (what the next one anchors on)
    for i, length in enumerate(lengths):
        c = f"c{i}"
        n(f"{c}_frames", "ImageFromBatch", image=["parts", 0], batch_index=STRIDE * i, length=length)
        if p.picks is not None:  # this chunk's slice of the one coloured track
            n(f"{c}_masks", "ImageFromBatch", image=["masks", 0], batch_index=STRIDE * i, length=length)
            ref_mask = ["masks", 1]
        else:
            n(f"{c}_track", "SAM3_VideoTrack", images=[f"{c}_frames", 0], model=["sam", 0],
              conditioning=["drive_words", 0], detection_threshold=0.5, max_objects=p.people, detect_interval=1)
            n(f"{c}_masks", "SCAIL2ColoredMask", driving_track_data=[f"{c}_track", 0],
              ref_track_data=["ref_track", 0], object_indices="", sort_by="left_to_right",
              replacement_mode=p.replace)
            ref_mask = [f"{c}_masks", 1]
        # Each chunk gets its own slice of the clip, so the offset stays 0, as in the blueprint: the node also
        # slices pose_video by video_frame_offset, and doing both left chunk 2 with 5 frames of motion
        # (measured: the second 5 s of a 10 s render ignored the performer).
        later = {} if i == 0 else {"previous_frames": [prev, 0]}
        n(f"{c}_scail", "WanSCAILToVideo", positive=["pos", 0], negative=["neg", 0], vae=["vae", 0], width=w,
          height=h, length=length, batch_size=1, pose_strength=1.0, pose_start=0.0, pose_end=1.0,
          video_frame_offset=0, previous_frame_count=OVERLAP, pose_video=[f"{c}_frames", 0],
          pose_video_mask=[f"{c}_masks", 0], replacement_mode=p.replace, reference_image=["ref", 0],
          reference_image_mask=ref_mask, clip_vision_output=["cv_ref", 0], **later)
        n(f"{c}_sample", "SamplerCustom", model=["shift", 0], add_noise=True, noise_seed=p.seed + i, cfg=1.0,
          positive=[f"{c}_scail", 0], negative=[f"{c}_scail", 1], sampler=["sampler", 0], sigmas=["sigmas", 0],
          latent_image=[f"{c}_scail", 2])
        n(f"{c}_dec", "VAEDecode", samples=[f"{c}_sample", 1], vae=["vae", 0])
        if i == 0:
            out = f"{c}_dec"
        else:  # drop the anchored overlap, then match colour to where the previous chunk ended
            n(f"{c}_new", "ImageFromBatch", image=[f"{c}_dec", 0], batch_index=OVERLAP, length=4096)
            n(f"{c}_last", "ImageFromBatch", image=[prev, 0], batch_index=-1, length=1)
            out = n(f"{c}_out", "ColorTransfer", image_target=[f"{c}_new", 0], image_ref=[f"{c}_last", 0],
                    method="reinhard_lab", source_stats="per_frame", strength=1.0)
        joined = out if i == 0 else n(f"{c}_join", "ImageBatch", image1=[joined, 0], image2=[out, 0])
        prev = out
    n("out", "CreateVideo", images=[joined, 0], fps=16.0, audio=["parts", 1])
    n("save", "SaveVideo", video=["out", 0], filename_prefix=p.prefix, format="auto", codec="auto")
    if p.keep_points is not None:
        union, new, kept = keep.add(n, render=[joined, 0], old_track=["track", 0], sam=["sam", 0],
                                    points=[[tuple(pt) for pt in pts] for pts in p.keep_points],
                                    clip=["clip_frames", 0], others=p.others or None)
        for key, images in ((KEEP_MASK_NODE, union), (KEEP_NEW_NODE, new), (KEEP_OTHERS_NODE, kept)):
            n(f"{key}_video", "CreateVideo", images=[images, 0], fps=16.0)
            n(key, "SaveVideo", video=[f"{key}_video", 0], filename_prefix=f"{p.prefix}_{key}", format="auto",
              codec="auto")
    return g


FINAL_NODE = "save"
KEEP_MASK_NODE = "save_keep_mask"  # old and new performers: left out of the colour fit
KEEP_NEW_NODE = "save_keep_new"  # the new characters alone: always as rendered
KEEP_OTHERS_NODE = "save_keep_others"  # the people not recast: put back as filmed


def reference_sheet(characters: list[Path], dst: Path, *, height: int = 1024) -> Path:
    """All identities on one picture, left to right, each scaled to the same height, padded (never cropped)
    to a square on white: SCAIL-2 matches characters to performers left to right."""
    inputs, chain = [], []
    for i, c in enumerate(characters):
        inputs += ["-i", str(c)]
        chain.append(f"[{i}:v]scale=-2:{height}:flags=lanczos,setsar=1[c{i}]")
    joined = "".join(f"[c{i}]" for i in range(len(characters)))
    chain.append(f"{joined}hstack=inputs={len(characters)}[row]" if len(characters) > 1 else "[c0]copy[row]")
    chain.append(f"[row]scale='min(iw,{height * 2})':-2,pad='max(iw,ih)':'max(iw,ih)':(ow-iw)/2:(oh-ih)/2:white[out]")
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(chain), "-map", "[out]",
                    "-frames:v", "1", "-map_metadata", "-1", str(dst)], check=True, timeout=120)
    return Path(dst)


def placed_sheet(characters: list[Path], boxes: list[tuple[float, float, float, float]], size: tuple[int, int],
                 dst: Path, colour: int, *, scale: int = 2) -> Path:
    """All identities on one picture the clip's shape, each where its performer stands in the start frame:
    fitted to that performer's box (x, y, width, height as fractions), top-aligned, on the room's colour.

    The coloured masks alone don't decide who becomes whom. With two performers chosen in the middle of seven
    people and the characters side by side on a square sheet, SCAIL-2 drew them on the people at the frame's
    edges, whatever the prompt said; placed like this, the same seed put each on their own performer
    (bench/RESULTS.md, "Who becomes whom follows the reference's layout")."""
    from PIL import Image

    W, H = size[0] * scale, size[1] * scale
    sheet = Image.new("RGB", (W, H), ((colour >> 16) & 255, (colour >> 8) & 255, colour & 255))
    for c, (x, y, w, h) in zip(characters, sorted(boxes, key=lambda b: b[0] + b[2] / 2)):  # left to right
        img = Image.open(c).convert("RGB")
        k = min(PLACED_WIDE * w * W / img.width, h * H / img.height)
        img = img.resize((max(1, round(img.width * k)), max(1, round(img.height * k))), Image.LANCZOS)
        sheet.paste(img, (round((x + w / 2) * W - img.width / 2), round(y * H)))
    sheet.save(dst)
    return Path(dst)


PLACED_WIDE = 1.15  # a cut-out may be this much wider than its performer's box (arms held out in the photo)


def track_words(whats: list[str], subject: str) -> str:
    """What SAM3 should follow: the performers as the clip reader named them ("dog, cat"), once each.

    In a crowd, "man" with one object tracks whichever man SAM3 finds first (measured on a crowded clip: a
    man walking behind the group, then the one in front); "man in a grey suit" stayed on the performer
    through both chunks, and "man in a suit" did not. So the server passes describe's `find` phrase."""
    words = list(dict.fromkeys(w.strip().lower() for w in whats if w and w.strip()))
    return ", ".join(words) if words else ("person" if subject == "person" else "animal")


ORDINALS = ["First", "Second", "Third", "Fourth"]


def prompt(texts: list[str], poses: list[str], *, replace: bool, place: str = "") -> str:
    """SCAIL-2 is trained on long, detailed prompts: who is where, what each body does, and the place."""
    sides = (["On the left", "On the right"] if len(texts) == 2 else ["In the frame"] if len(texts) == 1
             else [f"{ORDINALS[i]} from the left" for i in range(len(texts))])
    lines = []
    for side, text, pose in zip(sides, texts, poses + [""] * len(texts)):
        line = f"{side}, {describe.drop_negations(text.strip().rstrip('.'))}"
        if pose.strip():
            line += f", who {pose.strip().rstrip('.')}"
        lines.append(line + ".")
    if replace:
        lines.append("They are in the same place as the video, with the same camera, light and objects.")
    elif place.strip():
        lines.append(f"They are in {place.strip().rstrip('.')}, as in the picture.")
    else:
        lines.append("They are in the place shown in the picture, in its light.")
    return " ".join(lines)
