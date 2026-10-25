"""Restyle by video-to-video: Wan2.1 VACE 14B follows the depth of EVERY frame of the clip.

Animating one restyled still (Animate-2) keeps only what is in the first frame and what the body does:
sunglasses put on at 3 s never appeared, and a car that drives off stayed parked (bench/RESULTS.md,
"Restyle by video-to-video"). VACE is conditioned on a control video made from the whole clip, so later
objects and background motion are in what it follows; the restyled first frame is its reference picture,
which carries the look.

Graph: Comfy's "video_wan_vace_14B_v2v" template with depth control instead of Canny (measured cleaner,
less traced), the GGUF model, and lightx2v's step/cfg distill LoRA at full strength with 6 steps. The
template's CausVid LoRA is CC-BY-NC-4.0 (non-commercial), so it is not used. Depth is Depth Anything V2
Small, which is Apache-2.0; Base and Large are non-commercial.

A depth map can't see small things against the body (sunglasses put on mid-clip vanished when the prompt
didn't name them), so the prompt is written from four moments of the whole clip, not the first frame:
see describe.ROLE_PROMPTS["scene"].

Longer clips run as 81-frame chunks. Every chunk after the first starts from the last OVERLAP frames the
previous chunk made, given as fixed pixels (control mask 0); the rest of the chunk follows the clip's
depth (mask 1). The anchored frames are then dropped and the colour matched at the join.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import graph, styles

UNET = "Wan2.1_14B_VACE-Q4_K_S.gguf"
DISTILL = "Wan21_T2V_14B_lightx2v_cfg_step_distill_lora_rank64.safetensors"
DEPTH = "depth_anything_v2_vits.pth"

CHUNK = 81
OVERLAP = 9  # 1 + 4n frames, so the anchor fills whole latent frames
STRIDE = CHUNK - OVERLAP
STEPS = 6
MAX_CHUNKS = 4
MAX_TEXT = 1200
NEGATIVE = ("blurry, low quality, jpeg artifacts, deformed hands, extra fingers, deformed face, extra limbs, "
            "static frame, text, watermark")  # no "style, painting" words: they fight a restyle

MODELS = [
    {"role": "video model", "file": UNET, "upstream": "Wan-AI/Wan2.1-VACE-14B (GGUF Q4_K_S)", "license": "Apache-2.0"},
    {"role": "lora", "file": DISTILL, "upstream": "lightx2v/Wan2.1-T2V-14B-StepDistill-CfgDistill",
     "license": "Apache-2.0"},
    {"role": "depth", "file": DEPTH, "upstream": "depth-anything/Depth-Anything-V2-Small", "license": "Apache-2.0"},
    {"role": "text encoder", "file": graph.TEXT_ENCODER, "upstream": "google/umt5-xxl (Comfy fp8 repack)",
     "license": "Apache-2.0"},
    {"role": "vae", "file": graph.VAE, "upstream": "Wan-AI/Wan2.1", "license": "Apache-2.0"},
]


class VaceError(ValueError):
    pass


def frames_for(chunks: int) -> int:
    return CHUNK + STRIDE * (chunks - 1)


def lengths_for(frames: int) -> list[int]:
    return graph.chunk_lengths(frames, chunk=CHUNK, overlap=OVERLAP)


def size(layout: str) -> tuple[int, int]:
    w, h = graph.SIZES[layout]
    return w // 16 * 16, h // 16 * 16


@dataclass
class VaceParams:
    drive: Any  # normalised clip: render size, 16 fps, at least frames_for(chunks) frames
    reference: Any  # the restyled first frame: it carries the look
    prompt: str
    layout: str
    chunks: int = 1
    frames: int = 0  # the video's length; 0: whole chunks. Otherwise the last chunk is as short as it can be
    seed: int = 1
    prefix: str = "recast/restyle"

    def lengths(self) -> list[int]:
        return lengths_for(self.frames or frames_for(self.chunks))

    def validate(self) -> None:
        if self.layout not in graph.SIZES:
            raise VaceError(f"layout must be one of {sorted(graph.SIZES)}")
        if not 1 <= self.chunks <= MAX_CHUNKS:
            raise VaceError(f"chunks must be 1..{MAX_CHUNKS}")
        if self.frames and len(lengths_for(self.frames)) != self.chunks:
            raise VaceError(f"{self.frames} frames don't make {self.chunks} chunks")
        if not self.prompt.strip() or len(self.prompt) > MAX_TEXT:
            raise VaceError(f"the prompt must be 1..{MAX_TEXT} characters")
        if not 0 <= self.seed <= graph.MAX_SEED - MAX_CHUNKS:
            raise VaceError("seed out of range")


def prompt(scene: str, style: str) -> str:
    """Who and where, from the clip reader, then the look. The motion comes from the depth video."""
    return f"{scene.strip().rstrip('.')}, everything drawn as {styles.get(style).look}."


def build(p: VaceParams) -> dict[str, dict[str, Any]]:
    p.validate()
    w, h = size(p.layout)
    g: dict[str, dict[str, Any]] = {}

    def n(key: str, cls: str, **inputs: Any) -> str:
        g[key] = {"class_type": cls, "inputs": inputs}
        return key

    n("unet", "UnetLoaderGGUF", unet_name=UNET)
    n("fast", "LoraLoaderModelOnly", model=["unet", 0], lora_name=DISTILL, strength_model=1.0)
    n("shift", "ModelSamplingSD3", model=["fast", 0], shift=8.0)
    n("clip", "CLIPLoader", clip_name=graph.TEXT_ENCODER, type="wan", device="default")
    n("pos", "CLIPTextEncode", clip=["clip", 0], text=p.prompt)
    n("neg", "CLIPTextEncode", clip=["clip", 0], text=NEGATIVE)
    n("vae", "VAELoader", vae_name=graph.VAE)
    n("video", "LoadVideo", file=p.drive)
    n("parts", "GetVideoComponents", video=["video", 0])
    lengths = p.lengths()
    n("clip_frames", "ImageFromBatch", image=["parts", 0], batch_index=0,
      length=graph.covered(lengths, chunk=CHUNK, overlap=OVERLAP))
    n("depth_raw", "DepthAnythingV2Preprocessor", image=["clip_frames", 0], ckpt_name=DEPTH, resolution=512)
    n("depth", "ImageScale", image=["depth_raw", 0], upscale_method="bilinear", width=w, height=h, crop="disabled")
    n("ref", "LoadImage", image=p.reference)
    if p.chunks > 1:  # the extension mask: OVERLAP frames kept as given, the rest generated from depth
        n("keep", "EmptyImage", width=w, height=h, batch_size=OVERLAP, color=0)
        for length in sorted(set(lengths[1:])):  # whole chunks share one; a shorter last chunk has its own
            k = "" if length == CHUNK else f"_{length}"
            n(f"make{k}", "EmptyImage", width=w, height=h, batch_size=length - OVERLAP, color=0xFFFFFF)
            n(f"mask_img{k}", "ImageBatch", image1=["keep", 0], image2=[f"make{k}", 0])
            n(f"mask{k}", "ImageToMask", image=[f"mask_img{k}", 0], channel="red")

    joined = prev = ""  # everything so far; the previous chunk alone (what the next one starts from)
    for i, length in enumerate(lengths):
        c = f"c{i}"
        if i == 0:
            n(f"{c}_control", "ImageFromBatch", image=["depth", 0], batch_index=0, length=length)
            extra: dict[str, Any] = {}
        else:
            n(f"{c}_anchor", "ImageFromBatch", image=[prev, 0], batch_index=-OVERLAP, length=OVERLAP)
            n(f"{c}_depth", "ImageFromBatch", image=["depth", 0], batch_index=STRIDE * i + OVERLAP,
              length=length - OVERLAP)
            n(f"{c}_control", "ImageBatch", image1=[f"{c}_anchor", 0], image2=[f"{c}_depth", 0])
            extra = {"control_masks": ["mask" if length == CHUNK else f"mask_{length}", 0]}
        n(f"{c}_vace", "WanVaceToVideo", positive=["pos", 0], negative=["neg", 0], vae=["vae", 0], width=w,
          height=h, length=length, batch_size=1, strength=1.0, control_video=[f"{c}_control", 0],
          reference_image=["ref", 0], **extra)
        n(f"{c}_ks", "KSampler", model=["shift", 0], seed=p.seed + i, steps=STEPS, cfg=1.0, sampler_name="uni_pc",
          scheduler="simple", positive=[f"{c}_vace", 0], negative=[f"{c}_vace", 1], latent_image=[f"{c}_vace", 2],
          denoise=1.0)
        n(f"{c}_trim", "TrimVideoLatent", samples=[f"{c}_ks", 0], trim_amount=[f"{c}_vace", 3])
        n(f"{c}_dec", "VAEDecode", samples=[f"{c}_trim", 0], vae=["vae", 0])
        if i == 0:
            out = f"{c}_dec"
        else:  # drop the anchored frames, then match colour to where the previous chunk ended
            n(f"{c}_new", "ImageFromBatch", image=[f"{c}_dec", 0], batch_index=OVERLAP, length=4096)
            n(f"{c}_last", "ImageFromBatch", image=[prev, 0], batch_index=-1, length=1)
            out = n(f"{c}_out", "ColorTransfer", image_target=[f"{c}_new", 0], image_ref=[f"{c}_last", 0],
                    method="reinhard_lab", source_stats="per_frame", strength=1.0)
        joined = out if i == 0 else n(f"{c}_join", "ImageBatch", image1=[joined, 0], image2=[out, 0])
        prev = out
    n("out", "CreateVideo", images=[joined, 0], fps=16.0, audio=["parts", 1])
    n("save", "SaveVideo", video=["out", 0], filename_prefix=p.prefix, format="auto", codec="auto")
    return g


FINAL_NODE = "save"
