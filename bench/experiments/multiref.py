"""Multiple references in one Animate-2 reference still: which way of combining them holds up?

Animate-2 takes ONE reference still, so every reference has to be merged into it first.
Qwen-Image-Edit-2511 has three image slots (the clip's first frame plus two), so more than
two references need either a reference board (several images tiled into one) or two passes.

    python bench/experiments/multiref.py --frame first_frame.png --out bench/runs/multiref

Variants (all 4-step, seed 1, the same three references):
  V1 two_slots    frame + character + outfit                         (2 refs, no product: baseline)
  V2 board        frame + character + board(outfit | product)
  V3 two_pass     pass 1: frame + character + outfit; pass 2: result + product
  V4 board_all    frame + board(character | outfit | product)

The references are generated here with open-weight Qwen-Image, so there are no rights questions.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from comfy_sdk import Comfy

from recast import reference as ref
from recast import runner

ASSETS = {
    "character": ("Head-and-shoulders studio portrait photo of a young man with short curly black hair, "
                  "a neat short black beard, warm brown skin and a round face, plain light grey background, "
                  "looking at the camera, soft even light.", 1024, 1024),
    "outfit": ("Product photo of a bright red leather biker jacket with silver zips, shown flat and "
               "front-on, plain white background, nobody wearing it.", 1024, 1024),
    "product": ("Product photo of one glossy lime-green glass soda bottle with a plain white label, "
                "standing upright, plain white background.", 1024, 1024),
}
TAIL = " Same camera and framing as the first picture."
PROMPTS = {
    "V1_two_slots": ("Replace the woman in the first picture with the man from the second picture. He wears the "
                     "red leather jacket from the third picture. He takes exactly her body pose, size and "
                     "position." + TAIL),
    "V2_board": ("Replace the woman in the first picture with the man from the second picture. He wears the red "
                 "leather jacket shown on the LEFT side of the third picture and holds the green soda bottle "
                 "shown on the RIGHT side of the third picture in one hand. He takes exactly her body pose, "
                 "size and position." + TAIL),
    "V3_pass2": ("The man in the first picture now holds the green soda bottle from the second picture in one "
                 "hand. Nothing else changes." + TAIL),
    # V5: the prop goes in the hand the performer actually has low at their side (frame-relative
    # position, never "his right hand": possessive directions mirror).
    "V5_board_low_hand": ("Replace the woman in the first picture with the man from the second picture. He wears "
                          "the red leather jacket shown on the LEFT side of the third picture. His arm on the RIGHT "
                          "side of the frame hangs down by his hip exactly like hers, and that hand loosely holds "
                          "the green soda bottle shown on the RIGHT side of the third picture, the bottle hanging "
                          "down beside his thigh. He takes exactly her body pose, size and position." + TAIL),
    # V5b: V5 with the whole pose spelled out concretely (an abstract "take her pose" lost to the hand
    # instruction in V5). Frame-relative positions only.
    "V5b_low_hand_full_pose": ("Replace the woman in the first picture with the man from the second picture, in the "
                               "same pose: his arm on the LEFT side of the frame is raised with the hand resting on top "
                               "of his head, his head tilted back and his face turned up toward the TOP RIGHT of the "
                               "frame, his body leaning back. His arm on the RIGHT side of the frame hangs straight "
                               "down by his hip, and that hand loosely holds the green soda bottle shown on the RIGHT "
                               "side of the third picture, the bottle hanging beside his thigh. He wears the red "
                               "leather jacket shown on the LEFT side of the third picture." + TAIL),
    "V4_board_all": ("Replace the woman in the first picture with the man shown on the LEFT side of the second "
                     "picture. He wears the red leather jacket shown in the MIDDLE of the second picture and "
                     "holds the green soda bottle shown on the RIGHT side of the second picture in one hand. He "
                     "takes exactly her body pose, size and position." + TAIL),
}


def t2i(prompt: str, w: int, h: int, prefix: str) -> dict:
    return {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "qwen-image-Q4_K_M.gguf"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": ref.TEXT_ENCODER, "type": "qwen_image",
                                                      "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": ref.VAE}},
        "4": {"class_type": "LoraLoaderModelOnly", "inputs": {
            "model": ["1", 0], "lora_name": "Qwen-Image-Lightning-4steps-V1.0-bf16.safetensors", "strength_model": 1}},
        "5": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["4", 0], "shift": 3.1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": ""}},
        "8": {"class_type": "EmptySD3LatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "9": {"class_type": "KSampler", "inputs": {
            "model": ["5", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["8", 0], "seed": 1,
            "steps": 4, "cfg": 1, "sampler_name": "euler", "scheduler": "simple", "denoise": 1}},
        "10": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["3", 0]}},
        "11": {"class_type": "SaveImage", "inputs": {"images": ["10", 0], "filename_prefix": prefix}},
    }


def board(images: list[Path], dst: Path, height: int = 768) -> Path:
    """Tile images left to right at one height, white gaps between them."""
    args = ["ffmpeg", "-v", "error", "-y"]
    for p in images:
        args += ["-i", str(p)]
    chains = "".join(f"[{i}:v]scale=-2:{height},pad=iw+48:ih:24:0:white[v{i}];" for i in range(len(images)))
    args += ["-filter_complex", chains + "".join(f"[v{i}]" for i in range(len(images)))
             + f"hstack=inputs={len(images)}", "-frames:v", "1", str(dst)]
    subprocess.run(args, check=True, timeout=120)
    return dst


def run(client: Comfy, out: Path, name: str, image1: Path, image2: Path, image3: Path | None, prompt: str) -> Path:
    mp = ref.MatchParams(frame="f", character="c", character_text="x", location="l" if image3 else None,
                         subject="person", seed=1, prefix=f"recast/multiref_{name}")

    def make():
        mp.frame = client.assets.from_file(image1)
        mp.character = client.assets.from_file(image2)
        if image3:
            mp.location = client.assets.from_file(image3)
        g = ref.build(mp)
        g["pos"]["inputs"]["prompt"] = prompt
        return g

    job = runner.follow(runner.submit_graph(client, make, out / f"{name}.submission.json"), None)
    return runner.download(job, out / name, node_id=ref.FINAL_NODE)[0]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frame", required=True, type=Path, help="the clip's first frame")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--only", nargs="*", help="run only these variants (references are reused)")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    results: dict[str, str] = {}
    with Comfy(timeout=120) as client:
        assets = {}
        for key, (prompt, w, h) in ASSETS.items():
            existing = sorted((a.out / key).glob("*.png")) if (a.out / key).exists() else []
            if existing:
                assets[key] = existing[0]
                continue
            job = runner.follow(runner.submit_graph(
                client, lambda p=prompt, w=w, h=h, k=key: t2i(p, w, h, f"recast/multiref_{k}"),
                a.out / f"{key}.submission.json"), None)
            assets[key] = runner.download(job, a.out / key, node_id="11")[0]
        b2 = board([assets["outfit"], assets["product"]], a.out / "board_outfit_product.png")
        b3 = board([assets["character"], assets["outfit"], assets["product"]], a.out / "board_all.png")

        want = set(a.only or ["V1_two_slots", "V2_board", "V3_two_pass", "V4_board_all"])
        if "V1_two_slots" in want or "V3_two_pass" in want:
            results["V1_two_slots"] = str(run(client, a.out, "V1_two_slots", a.frame, assets["character"],
                                              assets["outfit"], PROMPTS["V1_two_slots"]))
        if "V2_board" in want:
            results["V2_board"] = str(run(client, a.out, "V2_board", a.frame, assets["character"], b2,
                                          PROMPTS["V2_board"]))
        if "V3_two_pass" in want:
            results["V3_two_pass"] = str(run(client, a.out, "V3_pass2", Path(results["V1_two_slots"]),
                                             assets["product"], None, PROMPTS["V3_pass2"]))
        if "V4_board_all" in want:
            results["V4_board_all"] = str(run(client, a.out, "V4_board_all", a.frame, b3, None,
                                              PROMPTS["V4_board_all"]))
        if "V5b_low_hand_full_pose" in want:
            results["V5b_low_hand_full_pose"] = str(run(client, a.out, "V5b_low_hand_full_pose", a.frame,
                                                        assets["character"], b2, PROMPTS["V5b_low_hand_full_pose"]))
        if "V5_board_low_hand" in want:
            results["V5_board_low_hand"] = str(run(client, a.out, "V5_board_low_hand", a.frame,
                                                   assets["character"], b2, PROMPTS["V5_board_low_hand"]))
    out = a.out / "results.json"
    previous = json.loads(out.read_text())["results"] if out.exists() else {}
    out.write_text(json.dumps({"results": {**previous, **results}, "prompts": PROMPTS,
                               "assets": {k: v[0] for k, v in ASSETS.items()}}, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
