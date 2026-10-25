"""Wan Animate-2 recast graph, built in ComfyUI API format.

One graph holds N chained 81-frame segments. Each later segment continues
the previous one's motion, starts at its frame offset and drops its first
frame, which overlaps the previous segment. The joined frames are trimmed
back to the source length and the source audio is attached.

The builder is the parameter contract: every value a user can influence
enters through `RecastParams`, which validates it, and nowhere else.
Ported from the author's own pre-competition `animate2_poc/gen_long.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SEGMENT_FRAMES = 81  # Wan's native clip length (4n+1)
SEGMENT_STRIDE = 80  # each continuation overlaps the previous segment by one frame
MAX_SEGMENTS = 4
FPS_CHOICES = (16,)
# Render sizes: multiples of 16 at about 0.4 MP, what Animate-2 fits on a 16 GB card. 480x832 is the
# nearest 16-aligned size to 9:16, not exactly 9:16: ASPECT is the shape a file is delivered in, and
# media.deliver crops to it (an inexact portrait was delivered stretched by 2.6% in an earlier project).
SIZES = {"portrait": (480, 832), "landscape": (832, 480), "square": (640, 640),
         "portrait_3x4": (576, 768), "landscape_4x3": (768, 576)}
ASPECT = {"portrait": (9, 16), "landscape": (16, 9), "square": (1, 1),
          "portrait_3x4": (3, 4), "landscape_4x3": (4, 3)}
MAX_PROMPT_CHARS = 600

UNET = "wan_animate_2_distill_int8_convrot.safetensors"
TEXT_ENCODER = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"
VAE = "wan_2.1_vae.safetensors"
CLIP_VISION = "clip_vision_h.safetensors"

# Wan's official negative prompt (kept in the original Chinese, as the model was trained on it).
NEGATIVE = (
    "色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，"
    "低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，画得不好的脸部，畸形的，"
    "毁容的，形态畸形的肢体，手指融合，静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走"
)

DEFAULT_SEED = 387378783691198
MAX_SEED = 2**53 - 1  # survives a JSON round trip through any client


class ParamError(ValueError):
    """A recast parameter is out of its allowed range."""


def frames_for(segments: int) -> int:
    return SEGMENT_FRAMES + SEGMENT_STRIDE * (segments - 1)


def chunk_lengths(frames: int, *, chunk: int, overlap: int) -> list[int]:
    """Frames in each chunk of a `frames`-frame video: whole chunks, then a shorter last one, so a clip of any
    length renders only what it needs. Each later chunk starts `overlap` frames back (it anchors on them).
    Every length is 1 + 4n, which Wan's latent needs, so up to 3 frames at the end are dropped; a last chunk
    that would add nothing past its overlap is left out."""
    out: list[int] = []
    start = 0
    while True:
        length = min(chunk, (frames - start - 1) // 4 * 4 + 1)
        if out and length <= overlap:
            break
        out.append(length)
        if length < chunk or start + length >= frames:
            break
        start += chunk - overlap
    return out


def covered(lengths: list[int], *, chunk: int, overlap: int) -> int:
    """Frames a render of these chunk lengths delivers."""
    return (chunk - overlap) * (len(lengths) - 1) + lengths[-1]


def segments_for(frames: int) -> int:
    """Fewest segments that cover `frames` source frames."""
    if frames <= SEGMENT_FRAMES:
        return 1
    return 1 + -(-(frames - SEGMENT_FRAMES) // SEGMENT_STRIDE)


@dataclass
class RecastParams:
    """Everything a recast job may vary. `reference` and `drive` are an input
    filename or an SDK asset handle; the rest are plain values."""

    reference: Any
    drive: Any
    appearance: str
    motion: str
    layout: str = "portrait"
    segments: int = 1
    fps: int = 16
    seed: int = DEFAULT_SEED
    steps: int = 10
    prefix: str = "recast/out"
    save_segments: bool = True
    extra: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.layout not in SIZES:
            raise ParamError(f"layout must be one of {sorted(SIZES)}")
        if not 1 <= self.segments <= MAX_SEGMENTS:
            raise ParamError(f"segments must be 1..{MAX_SEGMENTS}")
        if self.fps not in FPS_CHOICES:
            raise ParamError(f"fps must be one of {FPS_CHOICES}")
        if not 0 <= self.seed <= MAX_SEED - MAX_SEGMENTS:
            raise ParamError("seed out of range")
        if not 4 <= self.steps <= 20:
            raise ParamError("steps must be 4..20")
        for name in ("appearance", "motion"):
            text = getattr(self, name)
            if not isinstance(text, str) or not text.strip():
                raise ParamError(f"{name} prompt is required")
            if len(text) > MAX_PROMPT_CHARS:
                raise ParamError(f"{name} prompt is over {MAX_PROMPT_CHARS} characters")
        if not self.prefix.replace("/", "").replace("_", "").replace("-", "").isalnum():
            raise ParamError("prefix may hold only letters, digits, '/', '_' and '-'")
        if ".." in self.prefix or self.prefix.startswith("/"):
            raise ParamError("prefix must be a relative path")
        if self.extra:
            raise ParamError(f"unknown parameters: {sorted(self.extra)}")

    @property
    def size(self) -> tuple[int, int]:
        return SIZES[self.layout]


def build(p: RecastParams) -> dict[str, dict[str, Any]]:
    """Return the API-format graph for `p` (validated first)."""
    p.validate()
    w, h = p.size
    g: dict[str, dict[str, Any]] = {}

    def n(key: str, class_type: str, **inputs: Any) -> str:
        g[key] = {"class_type": class_type, "inputs": inputs}
        return key

    n("unet", "UNETLoader", unet_name=UNET, weight_dtype="default")
    n("cache", "WanAnimate2Cache", model=["unet", 0], device="cpu", dtype="int8")
    n("shift", "ModelSamplingSD3", model=["cache", 0], shift=5.0)
    n("sched", "BasicScheduler", model=["cache", 0], scheduler="simple", steps=p.steps, denoise=1.0)
    n("smp", "KSamplerSelect", sampler_name="lcm")
    n("clip", "CLIPLoader", clip_name=TEXT_ENCODER, type="wan", device="default")
    n("pos", "CLIPTextEncode", clip=["clip", 0], text=p.appearance)
    n("neg", "CLIPTextEncode", clip=["clip", 0], text=NEGATIVE)
    n("pose", "CLIPTextEncode", clip=["clip", 0], text=p.motion)
    n("vae", "VAELoader", vae_name=VAE)
    n("cv", "CLIPVisionLoader", clip_name=CLIP_VISION)
    n("ref", "LoadImage", image=p.reference)
    # VHS decodes at the target height while reading (bounded RAM), capped to what N segments use.
    n("vid", "VHS_LoadVideo", video=p.drive, force_rate=p.fps, custom_width=0, custom_height=h,
      frame_load_cap=frames_for(p.segments), skip_first_frames=0, select_every_nth=1, format="Wan")
    size = {"resize_type": "scale dimensions", "resize_type.width": w, "resize_type.height": h,
            "resize_type.crop": "center", "scale_method": "area"}
    n("drive", "ResizeImageMaskNode", input=["vid", 0], **size)
    n("ref_rs", "ResizeImageMaskNode", input=["ref", 0], **size)
    n("cv_ref", "CLIPVisionEncode", clip_vision=["cv", 0], image=["ref_rs", 0], crop="none")
    n("first", "ImageFromBatch", image=["drive", 0], batch_index=0, length=1)
    n("cv_pose", "CLIPVisionEncode", clip_vision=["cv", 0], image=["first", 0], crop="none")

    parts: dict[str, list[Any]] = {}
    prev: str | None = None
    for i in range(p.segments):
        a = n(f"a{i}", "WanAnimate2ToVideo", positive=["pos", 0], negative=["neg", 0], vae=["vae", 0],
              width=w, height=h, length=SEGMENT_FRAMES, batch_size=1,
              reference_image=["ref_rs", 0], pose_video=["drive", 0], clip_vision_output=["cv_ref", 0],
              positive_pose=["pose", 0], clip_vision_output_pose=["cv_pose", 0],
              video_frame_offset=0 if prev is None else [f"a{i - 1}", 5],
              pose_strength=1.0, pose_start_percent=0.0, pose_end_percent=1.0, reference_image_strength=1.0)
        if prev is not None:
            g[a]["inputs"]["continue_motion"] = [prev, 0]
        n(f"s{i}", "SamplerCustom", model=["shift", 0], add_noise=True, noise_seed=p.seed + i, cfg=1.0,
          positive=[a, 0], negative=[a, 1], sampler=["smp", 0], sigmas=["sched", 0], latent_image=[a, 2])
        n(f"t{i}", "TrimVideoLatent", samples=[f"s{i}", 0], trim_amount=[a, 3])
        prev = n(f"d{i}", "VAEDecode", samples=[f"t{i}", 0], vae=["vae", 0])
        if i == 0:
            part = [prev, 0]
        else:  # first frame repeats the previous segment's last
            part = [n(f"x{i}", "ImageFromBatch", image=[prev, 0], batch_index=1, length=4096), 0]
        parts[f"images.image{i}"] = part
        if p.save_segments and p.segments > 1:
            # checkpoint per segment so a late failure does not lose everything
            n(f"cv{i}", "CreateVideo", images=part, fps=float(p.fps))
            n(f"sv{i}", "SaveVideo", video=[f"cv{i}", 0], filename_prefix=f"{p.prefix}_seg{i + 1:02d}",
              format="auto", codec="auto")

    if p.segments == 1:
        joined = parts["images.image0"]
    else:
        joined = [n("all", "BatchImagesNode", **parts), 0]
    # trim to the source frame count: the last segment pads with held frames
    n("cut", "ImageFromBatch", image=joined, batch_index=0, length=["vid", 1])
    n("out", "CreateVideo", images=["cut", 0], fps=float(p.fps), audio=["vid", 2])
    n("save", "SaveVideo", video=["out", 0], filename_prefix=p.prefix, format="auto", codec="auto")
    return g


FINAL_NODE = "save"
