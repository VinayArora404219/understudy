"""Replacement experiment: put a character INTO the clip, keeping the clip's own pixels around them.

Question: Animate-2 (our default) animates a still, so the room has to be composed into that still
first, and every character photo with a busy background leaked its set into it (bench/RESULTS.md).
Wan2.2-Animate's replacement mode instead takes the source video as `background_video`, masks out
the performer (`character_mask`) and redraws only that region from the character image, with the
relight LoRA fitting them to the scene's light. The room is never generated, so nothing can leak.

Pipeline (all nodes already used by a known-good workflow on the GPU box; core + controlnet_aux +
segment-anything-2 + KJNodes):
    clip -> DWPose body/hands (pose_video) and face (face_video)
    clip -> SAM2 video segmentation, seeded at the performer's body keypoints (found here with
            MediaPipe Pose on the first frame, not clicked by hand) -> grow -> blockify -> mask
    clip with the mask painted black -> background_video
    character image -> reference_image + CLIP vision
    WanAnimateToVideo (77 frames) -> KSampler (lightx2v 6 steps, cfg 1) -> decode -> video + clip audio

People only: DWPose and MediaPipe track human bodies.

    python bench/experiments/replace.py --drive clip.mp4 --character c.png --text "..." --out bench/runs/replace
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from comfy_sdk import Comfy

from recast import graph, media, recipe, runner

UNET = "Wan2.2-Animate-14B-Q3_K_S.gguf"
LORAS = ["lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors", "WanAnimate_relight_lora_fp16.safetensors"]
SAM2 = "sam2_hiera_base_plus.safetensors"
FRAMES = 77


def seed_points(frame: Path, width: int, height: int) -> list[dict]:
    """Points inside the performer's body (head, chest, hips) for SAM2, in render pixels."""
    os.environ.setdefault("GLOG_minloglevel", "2")
    import cv2
    import mediapipe as mp

    img = cv2.cvtColor(cv2.imread(str(frame)), cv2.COLOR_BGR2RGB)
    with mp.solutions.pose.Pose(static_image_mode=True, model_complexity=1) as pose:
        lm = pose.process(img).pose_landmarks
    if lm is None:
        raise SystemExit("no person found in the first frame; replacement mode needs one")
    P, q = mp.solutions.pose.PoseLandmark, lm.landmark

    def mid(*names):
        pts = [q[getattr(P, n)] for n in names]
        return {"x": round(sum(p.x for p in pts) / len(pts) * width, 1),
                "y": round(sum(p.y for p in pts) / len(pts) * height, 1)}

    return [mid("NOSE"), mid("LEFT_SHOULDER", "RIGHT_SHOULDER"),
            mid("LEFT_SHOULDER", "RIGHT_SHOULDER", "LEFT_HIP", "RIGHT_HIP")]


def build(drive, character, points: list[dict], *, text: str, width: int, height: int, seed: int,
          prefix: str) -> dict:
    g: dict = {}

    def n(key, cls, **inputs):
        g[key] = {"class_type": cls, "inputs": inputs}
        return key

    n("unet", "UnetLoaderGGUF", unet_name=UNET)
    n("lora0", "LoraLoaderModelOnly", model=["unet", 0], lora_name=LORAS[0], strength_model=1.0)
    n("lora1", "LoraLoaderModelOnly", model=["lora0", 0], lora_name=LORAS[1], strength_model=1.0)
    n("shift", "ModelSamplingSD3", model=["lora1", 0], shift=8.0)
    n("clip", "CLIPLoader", clip_name=graph.TEXT_ENCODER, type="wan", device="default")
    n("pos", "CLIPTextEncode", clip=["clip", 0], text=text)
    n("neg", "CLIPTextEncode", clip=["clip", 0], text=graph.NEGATIVE)
    n("vae", "VAELoader", vae_name=graph.VAE)
    n("cv", "CLIPVisionLoader", clip_name=graph.CLIP_VISION)
    n("ref", "LoadImage", image=character)
    n("cv_ref", "CLIPVisionEncode", clip_vision=["cv", 0], image=["ref", 0], crop="none")
    n("vid", "VHS_LoadVideo", video=drive, force_rate=16, custom_width=0, custom_height=height,
      frame_load_cap=FRAMES, skip_first_frames=0, select_every_nth=1, format="Wan")
    n("frames", "ImageScale", image=["vid", 0], upscale_method="lanczos", width=width, height=height, crop="center")
    n("res", "PixelPerfectResolution", original_image=["frames", 0], image_gen_width=width,
      image_gen_height=height, resize_mode="Just Resize")
    n("pose", "DWPreprocessor", image=["frames", 0], detect_hand="enable", detect_body="enable",
      detect_face="disable", resolution=["res", 0], bbox_detector="yolox_l.onnx",
      pose_estimator="dw-ll_ucoco_384_bs5.torchscript.pt", scale_stick_for_xinsr_cn="disable")
    n("face", "DWPreprocessor", image=["frames", 0], detect_hand="disable", detect_body="disable",
      detect_face="enable", resolution=["res", 0], bbox_detector="yolox_l.onnx",
      pose_estimator="dw-ll_ucoco_384_bs5.torchscript.pt", scale_stick_for_xinsr_cn="disable")
    n("sam", "DownloadAndLoadSAM2Model", model=SAM2, segmentor="video", device="cuda", precision="fp16")
    n("seg", "Sam2Segmentation", sam2_model=["sam", 0], image=["frames", 0], keep_model_loaded=False,
      coordinates_positive=json.dumps(points), individual_objects=False)
    n("grow", "GrowMask", mask=["seg", 0], expand=10, tapered_corners=True)
    n("block", "BlockifyMask", masks=["grow", 0], block_size=32, device="cpu")
    n("bg", "DrawMaskOnImage", image=["frames", 0], mask=["block", 0], color="0, 0, 0", device="cpu")
    n("anim", "WanAnimateToVideo", positive=["pos", 0], negative=["neg", 0], vae=["vae", 0], width=width,
      height=height, length=FRAMES, batch_size=1, continue_motion_max_frames=5, video_frame_offset=0,
      clip_vision_output=["cv_ref", 0], reference_image=["ref", 0], face_video=["face", 0],
      pose_video=["pose", 0], background_video=["bg", 0], character_mask=["block", 0])
    n("ks", "KSampler", model=["shift", 0], seed=seed, steps=6, cfg=1.0, sampler_name="euler", scheduler="simple",
      positive=["anim", 0], negative=["anim", 1], latent_image=["anim", 2], denoise=1.0)
    n("trim", "TrimVideoLatent", samples=["ks", 0], trim_amount=["anim", 3])
    n("dec", "VAEDecode", samples=["trim", 0], vae=["vae", 0])
    n("out", "CreateVideo", images=["dec", 0], fps=16.0, audio=["vid", 2])
    n("save", "SaveVideo", video=["out", 0], filename_prefix=prefix, format="auto", codec="auto")
    n("save_bg", "SaveVideo", video=["bgv", 0], filename_prefix=f"{prefix}_masked", format="auto", codec="auto")
    n("bgv", "CreateVideo", images=["bg", 0], fps=16.0)
    return g


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--drive", required=True, type=Path)
    ap.add_argument("--character", required=True, type=Path)
    ap.add_argument("--text", required=True, help="who the character is (identity is carried by these words)")
    ap.add_argument("--layout", default=None)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)

    info = media.validate_upload(a.drive)
    box = media.content_box(a.drive)
    layout = a.layout or (media.layout_for(*box[:2]) if box else info.layout)
    w, h = graph.SIZES[layout]
    drive = media.normalize(a.drive, a.out / "drive.mp4", layout=layout, seconds=FRAMES / 16 + 0.1, fps=16, box=box)
    del drive
    drive = a.out / "drive.mp4"
    frame = media.first_frame(drive, a.out / "frame.png")
    points = seed_points(frame, w, h)
    character = media.clean_image(a.character, a.out / "character.png")
    text = (f"Character appearance description: {a.text.strip().rstrip('.')}.\n"
            "Background description: the same place, light and camera as the video.")
    g = build("drive.mp4", "character.png", points, text=text, width=w, height=h, seed=a.seed, prefix="recast/replace")
    (a.out / "graph.json").write_text(json.dumps(g, indent=1, ensure_ascii=False))
    print(f"{layout} {w}x{h}, SAM2 seeds {points}")

    t0 = time.time()
    with Comfy(timeout=120) as client:
        def make():
            return build(client.assets.from_file(drive), client.assets.from_file(character), points, text=text,
                         width=w, height=h, seed=a.seed, prefix="recast/replace")
        job = runner.follow(runner.submit_graph(client, make, a.out / f"submission_{recipe.graph_sha(g)[:10]}.json"),
                            lambda ev: ev["kind"] != "progress" and print(f"  {ev}", flush=True))
        files = runner.download(job, a.out / "render", node_id="save")
        runner.download(job, a.out / "render", node_id="save_bg")
    seconds = round(time.time() - t0, 1)
    if files:
        media.side_by_side(drive, files[0], a.out / "compare.mp4", vertical=layout.startswith("landscape"))
    print(f"done in {seconds}s -> {files}")


if __name__ == "__main__":
    main()
