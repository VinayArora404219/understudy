"""Restyle by video-to-video (Wan2.1 VACE 14B), not by animating one still.

Question: Restyle animates one restyled first frame (Animate-2), so anything that appears later in the clip
is lost or frozen (measured: sunglasses put on at ~3 s never appeared; a car that drives off stayed parked).
VACE follows a control video made from EVERY frame of the clip (edges or depth), with the restyled first
frame as its reference picture, so later objects and background motion are in what it follows.

Graph: Comfy's "video_wan_vace_14B_v2v" template (Canny control, CausVid LoRA, 4 steps, cfg 1, uni_pc,
shift 8), with the GGUF model, and --control depth as the alternative. The template's negative prompt
names "style, artwork, painting", which works against a restyle, so it is not used.

    python bench/experiments/vace_restyle.py --drive drive.mp4 --reference styled_frame.png --style anime \\
        --content "a young man in a white shirt on a city street" --control canny --out bench/runs/vace_canny
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from comfy_sdk import Comfy

from recast import graph, media, recipe, runner, styles

UNET = "Wan2.1_14B_VACE-Q4_K_S.gguf"
CAUSVID = "Wan21_CausVid_14B_T2V_lora_rank32_v2.safetensors"
FRAMES = 81
NEGATIVE = ("blurry, low quality, jpeg artifacts, deformed hands, extra fingers, deformed face, extra limbs, "
            "static frame, text, watermark")


def build(drive, ref, *, prompt: str, control: str, width: int, height: int, seed: int, prefix: str,
          lora: float = 0.3, steps: int = 4) -> dict:
    g: dict = {}

    def n(key, cls, **inputs):
        g[key] = {"class_type": cls, "inputs": inputs}
        return key

    n("unet", "UnetLoaderGGUF", unet_name=UNET)
    n("fast", "LoraLoaderModelOnly", model=["unet", 0], lora_name=CAUSVID, strength_model=lora)
    n("shift", "ModelSamplingSD3", model=["fast", 0], shift=8.0)
    n("clip", "CLIPLoader", clip_name=graph.TEXT_ENCODER, type="wan", device="default")
    n("pos", "CLIPTextEncode", clip=["clip", 0], text=prompt)
    n("neg", "CLIPTextEncode", clip=["clip", 0], text=NEGATIVE)
    n("vae", "VAELoader", vae_name=graph.VAE)
    n("video", "LoadVideo", file=drive)
    n("parts", "GetVideoComponents", video=["video", 0])
    n("frames", "ImageFromBatch", image=["parts", 0], batch_index=0, length=FRAMES)
    if control == "canny":
        n("control", "Canny", image=["frames", 0], low_threshold=0.4, high_threshold=0.8)
    else:
        n("control", "DepthAnythingV2Preprocessor", image=["frames", 0], ckpt_name="depth_anything_v2_vits.pth",
          resolution=512)
        # the depth map comes back at its own size; VACE and the encoder need the render size
        g["control_raw"] = g.pop("control")
        n("control", "ImageScale", image=["control_raw", 0], upscale_method="lanczos", width=width, height=height,
          crop="disabled")
    n("ref", "LoadImage", image=ref)
    n("vace", "WanVaceToVideo", positive=["pos", 0], negative=["neg", 0], vae=["vae", 0], width=width,
      height=height, length=FRAMES, batch_size=1, strength=1.0, control_video=["control", 0],
      reference_image=["ref", 0])
    n("ks", "KSampler", model=["shift", 0], seed=seed, steps=steps, cfg=1.0, sampler_name="uni_pc", scheduler="simple",
      positive=["vace", 0], negative=["vace", 1], latent_image=["vace", 2], denoise=1.0)
    n("trim", "TrimVideoLatent", samples=["ks", 0], trim_amount=["vace", 3])
    n("dec", "VAEDecode", samples=["trim", 0], vae=["vae", 0])
    n("out", "CreateVideo", images=["dec", 0], fps=16.0, audio=["parts", 1])
    n("save", "SaveVideo", video=["out", 0], filename_prefix=prefix, format="auto", codec="auto")
    n("control_v", "CreateVideo", images=["control", 0], fps=16.0)
    n("save_control", "SaveVideo", video=["control_v", 0], filename_prefix=f"{prefix}_control", format="auto",
      codec="auto")
    return g


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--drive", required=True, type=Path, help="normalised clip: render size, 16 fps")
    ap.add_argument("--reference", required=True, type=Path, help="the restyled first frame")
    ap.add_argument("--style", required=True, choices=sorted(styles.STYLES))
    ap.add_argument("--content", required=True, help="what is in the clip: who, what they wear, where")
    ap.add_argument("--control", choices=["canny", "depth"], default="canny",
                    help="depth uses Depth Anything V2 Small (Apache-2.0; the Large model is non-commercial)")
    ap.add_argument("--lora", type=float, default=0.3, help="CausVid strength (template: 0.3)")
    ap.add_argument("--steps", type=int, default=4, help="template: 4")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    info = media.probe(a.drive)
    w, h = info.width // 16 * 16, info.height // 16 * 16
    drive, ref = a.out / "drive.mp4", a.out / "reference.png"
    drive.write_bytes(a.drive.read_bytes())
    ref.write_bytes(a.reference.read_bytes())
    look = styles.get(a.style).look
    prompt = f"{a.content.strip().rstrip('.')}, everything drawn as {look}."
    g = build("drive.mp4", "reference.png", prompt=prompt, control=a.control, width=w, height=h, seed=a.seed,
              prefix=f"recast/vace_{a.control}", lora=a.lora, steps=a.steps)
    (a.out / "graph.json").write_text(json.dumps(g, indent=1, ensure_ascii=False))
    print(f"{a.control} {w}x{h} {FRAMES} frames, lora {a.lora}, {a.steps} steps\nprompt: {prompt}", flush=True)
    t0 = time.time()
    with Comfy(timeout=120) as client:
        def make():
            return build(client.assets.from_file(drive), client.assets.from_file(ref), prompt=prompt,
                         control=a.control, width=w, height=h, seed=a.seed, prefix=f"recast/vace_{a.control}",
                         lora=a.lora, steps=a.steps)
        job = runner.follow(runner.submit_graph(client, make, a.out / f"submission_{recipe.graph_sha(g)[:10]}.json"),
                            lambda ev: ev["kind"] != "progress" and print(f"  {ev}", flush=True))
        files = runner.download(job, a.out / "render", node_id="save")
        runner.download(job, a.out / "render", node_id="save_control")
    print(f"done in {time.time() - t0:.1f}s -> {files}")


if __name__ == "__main__":
    main()
