"""SCAIL-2 replacement experiment: put one or two characters INTO the clip, in its own room.

Question: our duo clip has two animals performing (bench/RESULTS.md, "Two performers"). Wan2.2-Animate's
replacement mode keeps the clip's room but needs a human skeleton (DWPose), so it can't follow a dog or a
cat. SCAIL-2 (zai-org, MIT, Wan2.1 14B) is driven end to end without a skeleton, lists animal-driven
motion and multi-character replacement among its abilities, and runs on core ComfyUI nodes.

Graph: Comfy's own "Character Replacement (SCAIL-2 Base)" blueprint, node for node, with the GGUF model:
    clip            -> SAM3 video track of the performers (text prompt, e.g. "dog, cat")
    reference image -> SAM3 track of the characters ("person"); all identities on ONE picture, left to right
    both tracks     -> SCAIL2ColoredMask (left_to_right: the leftmost performer gets the leftmost character)
    WanSCAILToVideo (replacement mode: the clip is the pose video, so its room is the input) -> 6 steps

--animate is SCAIL-2's animation mode instead: the room comes from --reference (a finished start picture,
e.g. from their_place.py), and the clip lends only its motion.

    python bench/experiments/scail.py --drive drive.mp4 --character left.png --character right.png \\
        --text "..." --text "..." --track "dog, cat" --out bench/runs/scail
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

from comfy_sdk import Comfy

from recast import graph, media, recipe, runner

UNET = "SCAIL-2-Q4_K_M.gguf"
DPO = "wan2.1_SCAIL_2_DPO_lora_bf16.safetensors"
LIGHTX2V = "lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors"
SAM3 = "sam3.1_multiplex_fp16.safetensors"
FRAMES = 81
FPS = 16


def reference(characters: list[Path], dst: Path, *, size: int = 1024) -> Path:
    """All identities on one picture, left to right, each scaled to the same height, padded (never
    cropped) to a square on white: the model is trained with a stretch resize, so the shape is set here."""
    inputs, chain = [], []
    for i, c in enumerate(characters):
        inputs += ["-i", str(c)]
        chain.append(f"[{i}:v]scale=-2:{size}:flags=lanczos,setsar=1[c{i}]")
    joined = "".join(f"[c{i}]" for i in range(len(characters)))
    chain.append(f"{joined}hstack=inputs={len(characters)}[row]" if len(characters) > 1 else "[c0]copy[row]")
    chain.append(f"[row]scale='min(iw,{size * 2})':-2,pad='max(iw,ih)':'max(iw,ih)':(ow-iw)/2:(oh-ih)/2:white[out]")
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(chain), "-map", "[out]",
                    "-frames:v", "1", str(dst)], check=True, timeout=120)
    return dst


def build(drive, ref, *, prompt: str, track: str, people: int, width: int, height: int, seed: int,
          prefix: str, replace: bool = True, unet: str = UNET) -> dict:
    g: dict = {}

    def n(key, cls, **inputs):
        g[key] = {"class_type": cls, "inputs": inputs}
        return key

    n("video", "LoadVideo", file=drive)
    n("parts", "GetVideoComponents", video=["video", 0])
    n("frames", "ImageFromBatch", image=["parts", 0], batch_index=0, length=FRAMES)
    n("ref", "LoadImage", image=ref)
    n("sam", "CheckpointLoaderSimple", ckpt_name=SAM3)
    n("drive_words", "CLIPTextEncode", clip=["sam", 1], text=track)
    n("ref_words", "CLIPTextEncode", clip=["sam", 1], text="person")
    n("drive_track", "SAM3_VideoTrack", images=["frames", 0], model=["sam", 0], conditioning=["drive_words", 0],
      detection_threshold=0.5, max_objects=people, detect_interval=1)
    n("ref_track", "SAM3_VideoTrack", images=["ref", 0], model=["sam", 0], conditioning=["ref_words", 0],
      detection_threshold=0.5, max_objects=people, detect_interval=1)
    n("masks", "SCAIL2ColoredMask", driving_track_data=["drive_track", 0], ref_track_data=["ref_track", 0],
      object_indices="", sort_by="left_to_right", replacement_mode=replace)
    n("unet", "UnetLoaderGGUF", unet_name=unet)
    n("dpo", "LoraLoaderModelOnly", model=["unet", 0], lora_name=DPO, strength_model=1.0)
    n("fast", "LoraLoaderModelOnly", model=["dpo", 0], lora_name=LIGHTX2V, strength_model=0.8)
    n("shift", "ModelSamplingSD3", model=["fast", 0], shift=5.0)
    n("clip", "CLIPLoader", clip_name=graph.TEXT_ENCODER, type="wan", device="default")
    n("pos", "CLIPTextEncode", clip=["clip", 0], text=prompt)
    n("neg", "CLIPTextEncode", clip=["clip", 0], text="")
    n("vae", "VAELoader", vae_name=graph.VAE)
    n("cv", "CLIPVisionLoader", clip_name=graph.CLIP_VISION)
    n("cv_ref", "CLIPVisionEncode", clip_vision=["cv", 0], image=["ref", 0], crop="none")
    n("scail", "WanSCAILToVideo", positive=["pos", 0], negative=["neg", 0], vae=["vae", 0], width=width,
      height=height, length=FRAMES, batch_size=1, pose_strength=1.0, pose_start=0.0, pose_end=1.0,
      video_frame_offset=0, previous_frame_count=5, pose_video=["frames", 0], pose_video_mask=["masks", 0],
      replacement_mode=replace, reference_image=["ref", 0], reference_image_mask=["masks", 1],
      clip_vision_output=["cv_ref", 0])
    # as in the blueprint: the schedule comes from the model before the shift node
    n("sigmas", "BasicScheduler", model=["fast", 0], scheduler="simple", steps=6, denoise=1.0)
    n("sampler", "KSamplerSelect", sampler_name="euler")
    n("sample", "SamplerCustom", model=["shift", 0], add_noise=True, noise_seed=seed, cfg=1.0,
      positive=["scail", 0], negative=["scail", 1], sampler=["sampler", 0], sigmas=["sigmas", 0],
      latent_image=["scail", 2])
    n("dec", "VAEDecode", samples=["sample", 1], vae=["vae", 0])
    n("out", "CreateVideo", images=["dec", 0], fps=float(FPS), audio=["parts", 1])
    n("save", "SaveVideo", video=["out", 0], filename_prefix=prefix, format="auto", codec="auto")
    # the two coloured masks, to check who was matched to whom
    n("drive_mask_v", "CreateVideo", images=["masks", 0], fps=float(FPS))
    n("save_mask", "SaveVideo", video=["drive_mask_v", 0], filename_prefix=f"{prefix}_mask", format="auto",
      codec="auto")
    n("save_ref_mask", "SaveImage", images=["masks", 1], filename_prefix=f"{prefix}_refmask")
    return g


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--drive", required=True, type=Path, help="normalised clip: render size, 16 fps")
    ap.add_argument("--character", type=Path, action="append", default=[], help="left to right")
    ap.add_argument("--reference", type=Path, help="a finished reference picture instead of --character")
    ap.add_argument("--animate", action="store_true", help="animation mode: the room comes from the reference")
    ap.add_argument("--unet", default=UNET)
    ap.add_argument("--size", type=int, default=0, help="render side (multiple of 32); default: the clip's")
    ap.add_argument("--text", required=True, action="append", help="what each character looks like, left to right")
    ap.add_argument("--pose", action="append", default=[], help="what each performer does, left to right")
    ap.add_argument("--track", required=True, help="what SAM3 follows in the clip, e.g. 'dog, cat'")
    ap.add_argument("--scene", default="", help="the clip's place in a few words (kept as filmed)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    if bool(a.character) == bool(a.reference):
        ap.error("give --character (one or two) or --reference")
    if len(a.text) > 2 or (a.character and len(a.character) != len(a.text)):
        ap.error("one --text per character, at most two")
    a.out.mkdir(parents=True, exist_ok=True)

    info = media.probe(a.drive)
    w, h = info.width // 32 * 32, info.height // 32 * 32
    if a.size:  # keep the clip's shape at a new size
        w, h = (a.size, round(a.size * h / w) // 32 * 32) if w >= h else (round(a.size * w / h) // 32 * 32, a.size)
    ref = a.out / "reference.png"
    if a.reference:
        ref.write_bytes(a.reference.read_bytes())
    else:
        reference(a.character, ref)
    sides = ["On the left", "On the right"] if len(a.text) == 2 else ["In the frame"]
    poses = a.pose + [""] * len(a.text)
    lines = [f"{s}, {t.strip().rstrip('.')}" + (f", {p.strip().rstrip('.')}" if p else "") + "."
             for s, t, p in zip(sides, a.text, poses)]
    if a.scene:
        lines.append(f"They are {a.scene.strip().rstrip('.')}" + (", as in the picture." if a.animate else
                                                               ", exactly as in the video, same camera and light."))
    prompt = " ".join(lines)
    drive = a.out / "drive.mp4"
    if a.drive.resolve() != drive.resolve():
        drive.write_bytes(a.drive.read_bytes())
    people, replace = len(a.text), not a.animate
    g = build("drive.mp4", "reference.png", prompt=prompt, track=a.track, people=people, width=w,
              height=h, seed=a.seed, prefix="recast/scail", replace=replace, unet=a.unet)
    (a.out / "graph.json").write_text(json.dumps(g, indent=1, ensure_ascii=False))
    print(f"{'animate' if a.animate else 'replace'} {w}x{h}, {FRAMES} frames, {a.unet}\nprompt: {prompt}", flush=True)

    t0 = time.time()
    with Comfy(timeout=120) as client:
        def make():
            return build(client.assets.from_file(drive), client.assets.from_file(ref), prompt=prompt,
                         track=a.track, people=people, width=w, height=h, seed=a.seed,
                         prefix="recast/scail", replace=replace, unet=a.unet)
        job = runner.follow(runner.submit_graph(client, make, a.out / f"submission_{recipe.graph_sha(g)[:10]}.json"),
                            lambda ev: ev["kind"] != "progress" and print(f"  {ev}", flush=True))
        files = runner.download(job, a.out / "render", node_id="save")
        runner.download(job, a.out / "render", node_id="save_mask")
        runner.download(job, a.out / "render", node_id="save_ref_mask")
    seconds = round(time.time() - t0, 1)
    if files:
        media.side_by_side(drive, files[0], a.out / "compare.mp4", height=h, vertical=False)
    print(f"done in {seconds}s -> {files}")


if __name__ == "__main__":
    main()
