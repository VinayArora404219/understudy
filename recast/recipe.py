"""recipe.json: everything needed to reproduce a result — inputs by hash,
every parameter, the exact graph by hash, and the models it loaded."""

from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import asdict
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any

from . import graph

MODELS = [
    {"role": "video model", "file": graph.UNET, "upstream": "Wan-AI/Wan2.2-Animate-2-14B (Comfy int8 repack)",
     "license": "Apache-2.0"},
    {"role": "text encoder", "file": graph.TEXT_ENCODER, "upstream": "google/umt5-xxl (Comfy fp8 repack)",
     "license": "Apache-2.0"},
    {"role": "vae", "file": graph.VAE, "upstream": "Wan-AI/Wan2.1", "license": "Apache-2.0"},
    {"role": "image encoder", "file": graph.CLIP_VISION, "upstream": "open-clip ViT-H/14 (Comfy repack)",
     "license": "MIT"},
]


def sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def graph_sha(g: dict) -> str:
    return hashlib.sha256(json.dumps(g, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def write(path: Path, *, params: Any, g: dict, inputs: dict[str, Path],
          outputs: dict[str, Path], job_id: str | None, seconds: float | None,
          models: list[dict] | None = None, finishing: dict | None = None) -> dict:
    """`params` is the engine's dataclass (graph.RecastParams, scail.ScailParams); `models` its weights.
    The recipe carries the exact API graph that ran (it opens in ComfyUI) and `finishing`: what was done to
    its output outside ComfyUI, so a re-run knows every step between the graph and the delivered file."""
    p = asdict(params)
    p.pop("extra", None)
    p["reference"] = inputs["reference"].name
    p["drive"] = inputs["drive"].name
    recipe = {
        "recipe_version": 2,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "params": p,
        "inputs": {k: {"file": v.name, "sha256": sha256(v)} for k, v in inputs.items()},
        "outputs": {k: {"file": v.name, "sha256": sha256(v)} for k, v in outputs.items()},
        "graph_sha256": graph_sha(g),
        "graph": g,
        "finishing": finishing or {},
        "models": models or MODELS,
        "runtime": {"comfy_sdk": version("comfy-sdk"), "python": platform.python_version()},
        "job_id": job_id,
        "render_seconds": seconds,
    }
    path.write_text(json.dumps(recipe, indent=2, ensure_ascii=False))
    return recipe
