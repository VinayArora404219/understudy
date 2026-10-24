# Performance Recast

Film yourself doing something. Pick any character. Get the same performance back, played by that
character, with your original audio, plus a side-by-side comparison and a `recipe.json` that
reproduces it.

Open weights only, end to end: Wan Animate-2 (Apache-2.0) for the motion transfer and
Qwen-Image-Edit-2511 (Apache-2.0) for building the reference. Every job runs through the official
[Comfy SDK](https://docs.comfy.org/development/api-development/sdks) against a self-hosted ComfyUI
behind [`comfy-api-proxy`](https://github.com/Comfy-Org/comfy-api-proxy). There is no closed model
anywhere in the path.

> Status: early. Built for Comfy's *Open Source Higgsfield* challenge (Oct 2026).

## What it adds over the stock Animate-2 workflow

- **Automatic reference matching.** Animate-2 copies identity, framing *and background* from the
  reference image. It works best when that image matches the clip's first frame in pose,
  framing and subject count. `recast` builds that reference for you: the first frame is image 1
  of a Qwen edit (pose, camera and room come from it), and your character is image 2 (identity
  only). With `--scene keep` your own room survives. With `--scene new --background "..."` it
  doesn't.
- **Any length, one job.** Clips are cut into chained 81-frame segments. Each segment continues
  the previous one's motion, and the duplicate boundary frames are dropped. Each segment is
  checkpointed.
- **Reproducible.** `recipe.json` records the input hashes, every parameter, the graph hash and
  the model files used.
- **Safe to host.** Graphs are built server-side from bounded parameters. Uploads are decoded,
  capped and stripped of metadata, and no subprocess sees a shell.

## Quick start (CLI)

```bash
uv venv && uv pip install -e ".[dev]"
# on the GPU host, next to ComfyUI:  pip install comfy-api-proxy && comfy-api-proxy
export COMFY_BASE_URL=http://127.0.0.1:8189

recast run --drive me_dancing.mp4 \
  --character my_robot.png --character-text "a slim silver robot with a round blue head" \
  --appearance "Character appearance description: a slim silver robot ...\nBackground description: ..." \
  --motion "A robot dances, swaying its hips and waving both arms" \
  --out runs/robot
```

Outputs land in `runs/robot/`: `recast.mp4`, `compare.mp4`, `reference.png`, `recipe.json`.
`--dry-run` writes the graphs without touching a GPU.

## Requirements

A ComfyUI install with the models in [`manifests/models.json`](manifests/models.json), plus
ComfyUI-VideoHelperSuite and ComfyUI-GGUF. Measured on a 16 GB RTX 4070 Ti SUPER: about 5–9
minutes per 5-second segment at 480×832, with peak VRAM of 13.5–15.9 GB.

## Limits (honest list)

- One performer per clip. Two performers driving one character makes it follow one of them, and
  you can't choose which.
- Locked or slow camera. The background comes from a single reference still.
- 480p-class output at 16 fps (Animate-2's native rate). Anything larger is an upscale, and the
  output says so.

## Licence

MIT for this repository's code. Models and custom nodes keep their own licences; see
`manifests/models.json`.

## Contributing / publishing rules

Nothing machine-specific, private or unlicensed enters git: no media, no weights, no IPs, paths or
usernames, no third-party clips. `tools/install_hooks.sh` installs a pre-commit check
(`tools/check_public.py`) that enforces this. Machine details live in `.env` (see `.env.example`).
Measured findings go in `bench/RESULTS.md`; every problem met so far and how it was fixed is in
`docs/PROBLEMS_AND_FIXES.md`.
