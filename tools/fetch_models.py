"""Put every model and custom node pack the app needs into your own ComfyUI.

    python3 tools/fetch_models.py /path/to/ComfyUI            # models + the three node packs
    python3 tools/fetch_models.py /path/to/ComfyUI --check    # only report what is missing or wrong
    python3 tools/fetch_models.py /path/to/ComfyUI --with-cli # also the Wan Animate-2 model of the old CLI

Reads manifests/models.json: each file comes from its pinned Hugging Face commit and is checked against the
manifest's size and SHA-256 before it takes its real name. A file already there with the right size is kept.
About 63 GiB for the app (79 GiB with --with-cli). Standard library only. Node packs come from the Comfy
registry versions in the manifest; install their requirements into ComfyUI's own Python afterwards.
"""

import argparse
import hashlib
import io
import json
import os
import sys
import urllib.request
import zipfile
from pathlib import Path

MANIFEST = Path(__file__).resolve().parents[1] / "manifests" / "models.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 24), b""):
            h.update(block)
    return h.hexdigest()


def fetch(m: dict, dest: Path) -> None:
    hf = m["hf"]
    url = f"https://huggingface.co/{hf['repo']}/resolve/{hf['revision']}/{hf['path']}"
    part = dest.with_name(dest.name + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    h, done = hashlib.sha256(), 0
    with urllib.request.urlopen(url) as r, open(part, "wb") as f:
        while block := r.read(1 << 22):
            f.write(block)
            h.update(block)
            done += len(block)
            print(f"\r  {m['file']}: {done / 2**30:.1f} / {m['size_bytes'] / 2**30:.1f} GiB", end="", flush=True)
    print()
    if (done, h.hexdigest()) != (m["size_bytes"], m["sha256"]):
        part.unlink()
        raise RuntimeError(f"{m['file']}: got {done} bytes, sha256 {h.hexdigest()[:12]}; the manifest says "
                           f"{m['size_bytes']} / {m['sha256'][:12]}")
    os.replace(part, dest)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("comfyui", type=Path, help="the ComfyUI folder (the one with main.py)")
    ap.add_argument("--check", action="store_true", help="report only, download nothing")
    ap.add_argument("--with-cli", action="store_true", help="also the Wan Animate-2 model used only by the CLI")
    ap.add_argument("--no-nodes", action="store_true", help="leave custom_nodes alone")
    a = ap.parse_args()
    root = a.comfyui.resolve()
    if not (root / "main.py").exists():
        sys.exit(f"{root} has no main.py: pass the ComfyUI folder")
    man = json.loads(MANIFEST.read_text())

    bad = 0
    for m in man["models"]:
        if "hf" not in m or (not a.with_cli and m["used_by"].startswith("recast CLI")):
            continue
        d = m["dir"]
        dest = root / d / m["file"] if d.startswith("custom_nodes/") else root / "models" / d / m["file"]
        if dest.exists() and dest.stat().st_size == m["size_bytes"]:
            print(f"  have     {dest.relative_to(root)}")
            continue
        if a.check:
            print(f"  MISSING  {dest.relative_to(root)}  ({m['size_bytes'] / 2**30:.1f} GiB)")
            bad += 1
            continue
        try:
            fetch(m, dest)
        except Exception as e:
            print(f"  FAILED   {m['file']}: {e}")
            bad += 1

    if not a.no_nodes:
        for n in man["custom_nodes"]:
            d = root / "custom_nodes" / n["name"]
            if d.exists():
                print(f"  have     custom_nodes/{n['name']}")
            elif a.check:
                print(f"  MISSING  custom_nodes/{n['name']} ({n['registry_version']})")
                bad += 1
            else:
                with urllib.request.urlopen(n["download"]) as r:
                    zipfile.ZipFile(io.BytesIO(r.read())).extractall(d)
                print(f"  got      custom_nodes/{n['name']} {n['registry_version']}"
                      f"{'  (pip install -r its requirements.txt)' if (d / 'requirements.txt').exists() else ''}")

    print(f"\n{'all present' if not bad else f'{bad} missing or failed'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
