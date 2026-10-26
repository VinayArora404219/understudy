"""The judge build's GPUs: two Modal endpoints, each ComfyUI + comfy-api-proxy in one container.

    modal run    deploy/modal/app.py::download      # once: every model in manifests/models.json -> Volume
    modal deploy deploy/modal/app.py                # publishes both HTTPS endpoints
    modal run    deploy/modal/app.py::check         # boots each lane, reports GPU / nodes / models
    modal run    deploy/modal/app.py::costs         # seconds and dollars per task, per lane

Then point the app at them, and change nothing else:

    COMFY_BASE_URL=https://<workspace>--performance-recast-comfy-api.<region>.modal.run          # heavy
    COMFY_QUICK_BASE_URL=https://<workspace>--performance-recast-comfyquick-api.<region>.modal.run
    COMFY_API_KEY=<the value in the `recast-api` Modal secret>   # both lanes check the same key

Two lanes because the server runs two GPU queues (server/app.py `_lane_of`): a judge who starts a render
and then opens another mode must not wait minutes for a picker that takes seconds. heavy = renders and the
Recast-in-the-clip's-place preview (a real 5 s render); quick = finding people, reading pictures and clips,
image-edit previews and cut-outs. Same image, same models Volume; each lane its own GPU and state.

The server talks to ComfyUI only through comfy-sdk -> comfy-api-proxy, never the legacy /prompt
endpoint, and it already does that against a proxy at whatever URL a lane names. So each container runs
exactly what the reference machine runs (ComfyUI on loopback, the proxy in front of it) and exposes the
proxy, nothing else, on Modal's HTTPS edge. front.py is the proxy with its own bearer-token gate
(comfy-sdk sends the key as `Authorization: Bearer`) and one fix for TLS termination.

A judge page wakes a lane with `GET <lane url>/api/v2/health`: no key needed, and any request starts a
container.

## One container per lane, always

`max_containers=1` on each lane. The proxy keeps jobs, idempotency keys and the asset index in its own SQLite, and
ComfyUI keeps the queue and the outputs; a second container would be a second, empty proxy, and the
SDK's poll for a job could land on the one that never heard of it. Jobs run one at a time on the GPU
anyway. A side effect worth knowing: `modal deploy` while a render runs starts the new container next to
the old one and that render is lost. Deploy between renders.

## What survives a restart (the `recast-state` Volume, one directory per lane)

The server stores the SDK job id and reattaches after its own restart, so the proxy's state must outlive
the container:

* proxy SQLite: kept on local disk (SQLite on a network volume is asking for trouble) and snapshotted to
  the Volume every SNAPSHOT_S seconds and at shutdown with SQLite's online backup, restored at boot;
* ComfyUI's input dir: lives ON the Volume. It has to: the proxy dedups uploads by hash and never checks
  that the file is still there, so a restored asset index pointing at an input dir that was wiped with
  the old container makes the next upload of the same clip a no-op and the job fail on a missing file.

After a restart, a job the proxy remembers but the fresh ComfyUI does not is reported `expired`, and
recast/runner.py already resubmits on `expired`: the cost of a restart mid-render is a re-render, never a
wrong or stuck job. What is NOT covered: a job submitted in the last SNAPSHOT_S seconds before a hard kill
is unknown to the restored proxy, so the SDK gets 404 on reattach (see README, "server").

## Warm while judges are active

Modal keeps a container while requests arrive. The server polls a running job, so a render keeps it
alive; after the last request heavy stays SCALEDOWN_S and quick QUICK_SCALEDOWN_S, then each scales to
zero. No always-on container.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

import modal

HERE = Path(__file__).resolve().parent
MANIFEST_LOCAL = HERE.parent.parent / "manifests" / "models.json"
MANIFEST = "/app/models.json"  # where the image carries it

# -- the stack, pinned to the reference machine (manifests/models.json has the same pins) -----------
COMFY_COMMIT = "8713616fcc321624e306bbd36be5906203dcb0dc"  # v0.41.3
TORCH = ("torch==2.13.0", "torchvision==0.28.0", "torchaudio==2.11.0")
TORCH_INDEX = "https://download.pytorch.org/whl/cu130"   # the reference runs +cu130; Modal hosts run r610
PROXY = "comfy-api-proxy==0.1.6"
NODES = {  # ComfyUI Registry versions, as installed on the reference (not git checkouts)
    "comfyui-videohelpersuite": "https://cdn.comfy.org/kosinkadink/comfyui-videohelpersuite/1.7.9/node.zip",
    "ComfyUI-GGUF": "https://cdn.comfy.org/city96/ComfyUI-GGUF/1.1.10/node.zip",
    "comfyui_controlnet_aux": "https://cdn.comfy.org/fannovel16/comfyui_controlnet_aux/1.1.5/node.zip",
}
# Python 3.13, not the reference's 3.14: Modal's image builder stops at 3.13. Same torch/CUDA build.
PYTHON = "3.13"

# -- GPUs, one per lane, chosen by measurement (bench/RESULTS.md, "Modal"); override at deploy -------
# heavy: renders and the Recast-in-the-clip's-place preview (a real 5 s render). quick: finding people,
# reading pictures and clips, image-edit previews and cut-outs, seconds each (server/app.py `_lane_of`).
GPU = os.environ.get("RECAST_GPU", "L40S")
QUICK_GPU = os.environ.get("RECAST_QUICK_GPU", "L4")
USD_PER_S = {  # Modal list prices, per GPU-second
    "L4": 0.000222, "A10G": 0.000306, "A10": 0.000306, "A100-40GB": 0.000583, "L40S": 0.000542,
    "RTX-PRO-6000": 0.000842, "A100-80GB": 0.000694, "H100": 0.001097, "H200": 0.001261,
}
# What the container itself costs on top of the GPU, at its requested size (usage above it bills higher)
CPU_CORES, MEM_GIB = 2.0, 16
BASE_USD_PER_S = CPU_CORES * 0.0000131 + MEM_GIB * 0.00000222
# How long a lane stays warm after its last request. 2 min while testing (idle time is most of the bill);
# raise at release, e.g. RECAST_SCALEDOWN_S=720 RECAST_QUICK_SCALEDOWN_S=300 modal deploy deploy/modal/app.py
SCALEDOWN_S = int(os.environ.get("RECAST_SCALEDOWN_S", 120))
QUICK_SCALEDOWN_S = int(os.environ.get("RECAST_QUICK_SCALEDOWN_S", 120))
SNAPSHOT_S = 20
RENDER_TIMEOUT_S = 60 * 60   # a request; a 20 s render is 4 chunks of up to ~15 min each on the reference
QUICK_TIMEOUT_S = 20 * 60

COMFY = "/root/ComfyUI"
MODELS = "/models"
STATE = "/state"
PROXY_STATE_LOCAL = "/tmp/proxy-state"
LANES = ("heavy", "quick")   # each has its own dir on the state Volume: proxy/, input/, costs.jsonl, sessions/
COMFY_PORT, PROXY_PORT = 8188, 8000

# Every directory the graphs load from. Two names for diffusion models because the manifest keeps the
# reference machine's split (SCAIL/VACE GGUFs in unet/, the rest in diffusion_models/).
EXTRA_PATHS = f"""recast:
    base_path: {MODELS}
    checkpoints: checkpoints
    clip_vision: clip_vision
    diffusion_models: |
        unet
        diffusion_models
    loras: loras
    text_encoders: text_encoders
    vae: vae
    background_removal: background_removal
"""
AUX_CKPTS = f"{MODELS}/aux_ckpts"  # controlnet_aux reads its checkpoints from here (config.yaml below)
AUX_CONFIG = f"""annotator_ckpts_path: "{AUX_CKPTS}"
custom_temp_path: "/tmp"
USE_SYMLINKS: False
EP_list: ["CUDAExecutionProvider", "CPUExecutionProvider"]
"""


def volume_path(entry: dict) -> str:
    """Where a manifest entry lives on the models Volume."""
    d = entry["dir"]
    aux = "custom_nodes/comfyui_controlnet_aux/ckpts/"
    return f"{AUX_CKPTS}/{d[len(aux):]}/{entry['file']}" if d.startswith(aux) else f"{MODELS}/{d}/{entry['file']}"


def manifest() -> list[dict]:
    path = MANIFEST if os.path.exists(MANIFEST) else MANIFEST_LOCAL
    return [m for m in json.loads(Path(path).read_text())["models"] if "hf" in m]


def _node_install() -> list[str]:
    cmds = []
    for name, url in NODES.items():
        d = f"{COMFY}/custom_nodes/{name}"
        cmds += [f"mkdir -p {d}", f"wget -qO /tmp/{name}.zip {url}", f"unzip -q /tmp/{name}.zip -d {d}",
                 f"rm /tmp/{name}.zip"]
    return cmds


image = (
    modal.Image.debian_slim(python_version=PYTHON)
    .apt_install("git", "wget", "unzip", "ffmpeg", "libgl1", "libglib2.0-0", "sqlite3")
    # torch first from the CUDA index; ComfyUI lists torch unpinned, so it stays put afterwards
    .pip_install(*TORCH, index_url=TORCH_INDEX)
    .add_local_file(HERE / "reference-constraints.txt", "/app/reference-constraints.txt", copy=True)
    .run_commands(
        f"git clone https://github.com/comfyanonymous/ComfyUI {COMFY}",
        f"git -C {COMFY} checkout --detach {COMFY_COMMIT}",
        *_node_install(),
        f"pip install -c /app/reference-constraints.txt -r {COMFY}/requirements.txt "
        f"-r {COMFY}/custom_nodes/comfyui-videohelpersuite/requirements.txt "
        f"-r {COMFY}/custom_nodes/ComfyUI-GGUF/requirements.txt "
        f"-r {COMFY}/custom_nodes/comfyui_controlnet_aux/requirements.txt "
        f"{PROXY} huggingface_hub hf_xet",
        # the torch wheels must still be the cu130 build after every requirements file has resolved
        "python -c \"import torch; assert torch.__version__ == '2.13.0+cu130', torch.__version__\"",
    )
    # written through python: every printf/echo spelling of a multi-line yaml loses newlines or indentation
    .run_commands(
        f"python -c \"open('{COMFY}/extra_model_paths.yaml','w').write({EXTRA_PATHS!r})\"",
        f"python -c \"open('{COMFY}/custom_nodes/comfyui_controlnet_aux/config.yaml','w').write({AUX_CONFIG!r})\"",
    )
    .env({"RECAST_GPU": GPU, "RECAST_QUICK_GPU": QUICK_GPU, "HF_XET_HIGH_PERFORMANCE": "1", "PYTHONUNBUFFERED": "1"})
    .add_local_file(MANIFEST_LOCAL, MANIFEST)
    .add_local_file(HERE / "front.py", "/app/front.py")
)

app = modal.App("performance-recast", image=image)
models_vol = modal.Volume.from_name("recast-models", create_if_missing=True)
state_vol = modal.Volume.from_name("recast-state", create_if_missing=True)
api_secret = modal.Secret.from_name("recast-api", required_keys=["COMFY_API_KEY"])


# ----------------------------------------------------------------------------- models

def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(16 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _fetch(entry: dict, verify: bool) -> tuple[str, str]:
    from huggingface_hub import hf_hub_download

    dest = volume_path(entry)
    if os.path.exists(dest) and os.path.getsize(dest) == entry["size_bytes"]:
        if not verify or _sha256(dest) == entry["sha256"]:
            return "have", dest
    hf = entry["hf"]
    t0 = time.time()
    staging = f"{MODELS}/.staging/{entry['file']}"
    got = hf_hub_download(hf["repo"], hf["path"], revision=hf["revision"], local_dir=staging)
    size, sha = os.path.getsize(got), _sha256(got)
    if (size, sha) != (entry["size_bytes"], entry["sha256"]):
        raise RuntimeError(f"{entry['file']}: got {size} bytes sha256 {sha[:12]}, the manifest says "
                           f"{entry['size_bytes']} / {entry['sha256'][:12]}. Not the reference checkpoint.")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    os.replace(got, dest)  # same filesystem: atomic, never a half-written model under its real name
    return f"got {size / 2**30:.1f} GiB in {time.time() - t0:.0f}s", dest


@app.function(volumes={MODELS: models_vol}, timeout=3 * 3600, cpu=8.0, memory=16384)
def download(verify: bool = False, only: str = ""):
    """Fill the models Volume from Hugging Face. Idempotent: a file of the right size is kept (and with
    --verify re-hashed). Every fetched file is checked against the manifest's size and sha256."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    entries = [m for m in manifest() if not only or only in m["file"]]
    done, failed = 0, []
    with ThreadPoolExecutor(4) as pool:
        futs = {pool.submit(_fetch, m, verify): m for m in entries}
        for fut in as_completed(futs):
            m = futs[fut]
            try:
                status, dest = fut.result()
                done += 1
                print(f"  {status:<24} {dest}", flush=True)
            except Exception as e:
                failed.append(m["file"])
                print(f"  FAILED {m['file']}: {e}", flush=True)
            models_vol.commit()  # keep what landed even if a later file fails
    shutil.rmtree(f"{MODELS}/.staging", ignore_errors=True)
    models_vol.commit()
    total = sum(m["size_bytes"] for m in entries) / 2**30
    print(f"\n  {done}/{len(entries)} present ({total:.1f} GiB), {len(failed)} failed {failed or ''}")
    if failed:
        raise SystemExit(1)


# ----------------------------------------------------------------------------- the server

def _wait(url: str, deadline_s: int, proc: subprocess.Popen | None = None) -> dict:
    t0 = time.time()
    while time.time() - t0 < deadline_s:
        if proc is not None and proc.poll() is not None:
            # died during boot (an import error, a bad flag): say so now, not after the deadline
            time.sleep(1)  # let the log pump drain the traceback
            tail = Path("/tmp/comfyui.log").read_text(errors="replace")[-3000:]
            raise RuntimeError(f"ComfyUI exited with {proc.returncode} while booting:\n{tail}")
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                return json.load(r)
        except Exception:
            time.sleep(1)
    raise RuntimeError(f"{url} did not answer within {deadline_s}s")


def _kind(graph: dict) -> str:
    """Which task a ComfyUI prompt was, from the models it loads (first match wins)."""
    text = json.dumps(graph)
    for needle, kind in (("SCAIL-2", "recast"), ("VACE", "restyle"), ("qwen-image-edit", "reference"),
                         ("wan_animate_2", "animate2"), ("qwen3vl", "describe"), ("sam3", "people"),
                         ("birefnet", "cutout")):
        if needle in text:
            return kind
    return "other"


def _partial_loads() -> int:
    # a partial load means the GPU is too small for the graph: weights stream every step.
    # \b because ComfyUI also logs "Unloaded partially", which is healthy.
    return len(re.findall(r"\bloaded partially", Path("/tmp/comfyui.log").read_text(errors="replace")))


class Lane:
    """One ComfyUI + proxy in this container, and everything it keeps on the state Volume.

    Two lanes never share a directory: a proxy's asset index is only true of its own input dir (see the
    module docstring), so each lane has its own proxy snapshot and input dir, and its own cost log and
    session files, so two containers never commit the same file.
    """

    def __init__(self, name: str, gpu: str):
        self.name, self.gpu = name, gpu
        self.dir = Path(STATE) / name
        self.rate = USD_PER_S.get(gpu, 0) + BASE_USD_PER_S
        self.task = os.environ.get("MODAL_TASK_ID", f"local-{os.getpid()}")

    # -- state
    def restore(self) -> None:
        os.makedirs(PROXY_STATE_LOCAL, exist_ok=True)
        saved = self.dir / "proxy" / "state.sqlite3"
        if saved.exists():
            shutil.copy2(saved, Path(PROXY_STATE_LOCAL) / "state.sqlite3")
            print(f"  [{self.name}] proxy state restored ({saved.stat().st_size} bytes)", flush=True)

    def snapshot(self) -> None:
        """Copy the proxy's live SQLite to the Volume, then commit it with the input dir and the logs."""
        src = Path(PROXY_STATE_LOCAL) / "state.sqlite3"
        if src.exists():
            dst = self.dir / "proxy" / "state.sqlite3"
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_suffix(".tmp")
            with sqlite3.connect(src) as a, sqlite3.connect(tmp) as b:
                a.backup(b)  # consistent copy of a database another process is writing
            os.replace(tmp, dst)
        state_vol.commit()

    # -- cost
    def log(self, row: dict) -> None:
        with open(self.dir / "costs.jsonl", "a") as f:
            f.write(json.dumps({"t": round(time.time(), 1), "lane": self.name, "gpu": self.gpu, **row}) + "\n")

    def session(self) -> None:
        """This container's life so far: what Modal bills (boot, tasks and the idle scaledown tail).
        Rewritten every snapshot, so it survives a hard stop that never runs the exit hook."""
        d = self.dir / "sessions"
        d.mkdir(parents=True, exist_ok=True)
        life = round(time.time() - self.t0, 1)
        (d / f"{self.task}.json").write_text(json.dumps(
            {"lane": self.name, "gpu": self.gpu, "start": round(self.t0, 1), "lifetime_s": life,
             "usd": round(life * self.rate, 4), "boot_s": self.boot_s}))

    def log_finished(self) -> None:
        """One line per prompt ComfyUI finished since the last look: kind, GPU seconds, dollars."""
        with urllib.request.urlopen(f"http://127.0.0.1:{COMFY_PORT}/history", timeout=30) as r:
            hist = json.load(r)
        partial = _partial_loads()
        for pid, rec in hist.items():
            st = rec.get("status") or {}
            if pid in self.seen or not st.get("completed") and st.get("status_str") != "error":
                continue
            self.seen.add(pid)
            ts = {ev: data.get("timestamp") for ev, data in st.get("messages", []) if isinstance(data, dict)}
            start = ts.get("execution_start")
            end = ts.get("execution_success") or ts.get("execution_error") or ts.get("execution_interrupted")
            gpu_s = round((end - start) / 1000, 1) if start and end else None
            self.log({"event": "prompt", "prompt_id": pid, "kind": _kind(rec["prompt"][2]),
                      "status": st.get("status_str"), "gpu_s": gpu_s,
                      "usd": round(gpu_s * self.rate, 4) if gpu_s else None, "loaded_partially_total": partial})

    # -- lifecycle
    def boot(self) -> None:
        self.t0 = time.time()
        self.boot_s = None
        self.dir.mkdir(parents=True, exist_ok=True)
        self.restore()
        (self.dir / "input").mkdir(exist_ok=True)
        self.comfy_log = open("/tmp/comfyui.log", "w")
        # --disable-comfy-compiler: the reference runs with it, and compiled kernels are a numerics change.
        # The reference's --disable-pinned-memory / --cache-ram 8 are workarounds for a 16 GB card with
        # 32 GB RAM; they change speed, not results, and are not set here.
        self.comfy = subprocess.Popen(
            ["python", "main.py", "--listen", "127.0.0.1", "--port", str(COMFY_PORT),
             "--extra-model-paths-config", f"{COMFY}/extra_model_paths.yaml",
             "--input-directory", str(self.dir / "input"), "--output-directory", "/tmp/comfy-output",
             "--disable-comfy-compiler"],
            cwd=COMFY, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        threading.Thread(target=self._pump, daemon=True).start()
        st = _wait(f"http://127.0.0.1:{COMFY_PORT}/system_stats", 900, self.comfy)
        dev = (st.get("devices") or [{}])[0]
        self.boot_s = round(time.time() - self.t0, 1)
        print(f"  [{self.name}] comfy {st['system']['comfyui_version']} on {dev.get('name')} "
              f"({dev.get('vram_total', 0) / 2**30:.0f} GB) in {self.boot_s}s", flush=True)
        self.log({"event": "boot", "boot_s": self.boot_s, "device": dev.get("name")})
        self.session()
        self.seen: set[str] = set()
        self.stop = threading.Event()
        threading.Thread(target=self._loop, daemon=True).start()

    def _pump(self):
        # ComfyUI's log both to Modal (watch a render live) and to disk (the offload check greps it)
        for line in self.comfy.stdout:
            print(line, end="", flush=True)
            self.comfy_log.write(line)
            self.comfy_log.flush()

    def _loop(self):
        while not self.stop.wait(SNAPSHOT_S):
            self.tick()

    def tick(self) -> None:
        try:
            self.log_finished()
            self.session()
            self.snapshot()
        except Exception as e:  # never take the server down over a backup or a cost line
            print(f"  [{self.name}] snapshot failed: {e!r}", flush=True)

    def serve(self) -> None:
        env = {**os.environ, "PROXY_STATE_DIR": PROXY_STATE_LOCAL, "PROXY_PORT": str(PROXY_PORT),
               "COMFY_URL": f"http://127.0.0.1:{COMFY_PORT}"}
        subprocess.Popen(["python", "/app/front.py"], env=env)

    def ping(self) -> dict:
        """What this container sees: for `check`, and to read boot time and partial loads."""
        with urllib.request.urlopen(f"http://127.0.0.1:{COMFY_PORT}/system_stats", timeout=10) as r:
            st = json.load(r)
        with urllib.request.urlopen(f"http://127.0.0.1:{COMFY_PORT}/object_info", timeout=120) as r:
            nodes = set(json.load(r))
        need = ["UnetLoaderGGUF", "VHS_LoadVideo", "DepthAnythingV2Preprocessor", "SAM3_VideoTrack",
                "SCAIL2ColoredMask", "TextGenerate", "LoadBackgroundRemovalModel", "TextEncodeQwenImageEditPlus",
                "WanAnimate2Cache", "SaveVideo"]
        missing = [m["file"] for m in manifest()
                   if not (os.path.exists(volume_path(m)) and os.path.getsize(volume_path(m)) == m["size_bytes"])]
        dev = (st.get("devices") or [{}])[0]
        return {"lane": self.name, "comfyui": st["system"]["comfyui_version"],
                "python": st["system"].get("python_version"), "torch": st["system"].get("pytorch_version"),
                "gpu": dev.get("name"), "vram_gb": round(dev.get("vram_total", 0) / 2**30, 1),
                "boot_s": self.boot_s, "missing_nodes": [n for n in need if n not in nodes],
                "missing_models": missing, "loaded_partially": _partial_loads(),
                "usd_per_s": USD_PER_S.get(self.gpu)}

    def shutdown(self) -> None:
        self.stop.set()
        self.tick()


# Two classes rather than one parametrised class because a Modal class carries ONE gpu= and ONE
# scaledown_window for all its parameters. The methods are thin on purpose: everything is in Lane.
_SERVED = dict(volumes={MODELS: models_vol, STATE: state_vol}, secrets=[api_secret],
               cpu=CPU_CORES, memory=(MEM_GIB * 1024, 131072), min_containers=0, max_containers=1)


@app.cls(gpu=GPU, timeout=RENDER_TIMEOUT_S, scaledown_window=SCALEDOWN_S, **_SERVED)
@modal.concurrent(max_inputs=64)  # the SDK's polls, event streams and downloads share one container
class Comfy:
    """The heavy lane (COMFY_BASE_URL): renders and the Recast-in-the-clip's-place preview."""

    @modal.enter()
    def boot(self):
        self.lane = Lane("heavy", GPU)
        self.lane.boot()

    @modal.web_server(PROXY_PORT, startup_timeout=120)
    def api(self):
        self.lane.serve()

    @modal.method()
    def ping(self) -> dict:
        return self.lane.ping()

    @modal.exit()
    def shutdown(self):
        self.lane.shutdown()


@app.cls(gpu=QUICK_GPU, timeout=QUICK_TIMEOUT_S, scaledown_window=QUICK_SCALEDOWN_S, **_SERVED)
@modal.concurrent(max_inputs=64)
class ComfyQuick:
    """The quick lane (COMFY_QUICK_BASE_URL): people, words, image-edit previews and cut-outs."""

    @modal.enter()
    def boot(self):
        self.lane = Lane("quick", QUICK_GPU)
        self.lane.boot()

    @modal.web_server(PROXY_PORT, startup_timeout=120)
    def api(self):
        self.lane.serve()

    @modal.method()
    def ping(self) -> dict:
        return self.lane.ping()

    @modal.exit()
    def shutdown(self):
        self.lane.shutdown()


# ----------------------------------------------------------------------------- reports

@app.function(volumes={STATE: state_vol}, timeout=120)
def read_costs() -> dict:
    """Every lane's cost lines and session files. Lines written before the lanes existed (at the Volume's
    root, from the single-endpoint build) count as the heavy lane."""
    state_vol.reload()
    rows, sessions = [], []
    old = Path(STATE) / "costs.jsonl"
    if old.exists():
        rows += [{"lane": "heavy", **json.loads(l)} for l in old.read_text().splitlines() if l.strip()]
    for lane in LANES:
        f = Path(STATE) / lane / "costs.jsonl"
        if f.exists():
            rows += [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
        sessions += [json.loads(p.read_text()) for p in sorted((Path(STATE) / lane / "sessions").glob("*.json"))]
    return {"rows": rows, "sessions": sessions}


@app.local_entrypoint()
def check(lane: str = "both"):
    """`modal run deploy/modal/app.py::check [--lane heavy|quick]`: boot each lane, report what it sees."""
    for name, cls in (("heavy", Comfy), ("quick", ComfyQuick)):
        if lane in ("both", name):
            print(json.dumps(cls().ping.remote(), indent=1))


@app.local_entrypoint()
def costs():
    """`modal run deploy/modal/app.py::costs`: seconds and dollars per task kind, per lane and GPU, and
    what each lane's containers cost in total (boot + tasks + idle tail)."""
    from collections import defaultdict

    data = read_costs.remote()
    by = defaultdict(list)
    for r in data["rows"]:
        if r["event"] == "prompt" and r.get("gpu_s") and r.get("status") == "success":
            by[(r["lane"], r["gpu"], r["kind"])].append(r)
    print(f"{'lane':<7}{'gpu':<9}{'kind':<11}{'n':>3}{'mean s':>9}{'min s':>8}{'max s':>8}{'mean $':>9}{'partial':>9}")
    for (lane, gpu, kind), rs in sorted(by.items()):
        s = [r["gpu_s"] for r in rs]
        print(f"{lane:<7}{gpu:<9}{kind:<11}{len(rs):>3}{sum(s) / len(s):>9.1f}{min(s):>8.1f}{max(s):>8.1f}"
              f"{sum(r['usd'] for r in rs) / len(rs):>9.3f}{max(r.get('loaded_partially_total') or 0 for r in rs):>9}")
    print()
    for lane in LANES:
        boots = [r["boot_s"] for r in data["rows"] if r["event"] == "boot" and r["lane"] == lane]
        ss = [s for s in data["sessions"] if s["lane"] == lane]
        if boots:
            print(f"{lane}: {len(boots)} boots, ComfyUI boot {min(boots)}-{max(boots)} s")
        if ss:
            print(f"{lane}: {len(ss)} sessions, ${sum(s['usd'] for s in ss):.2f} over "
                  f"{sum(s['lifetime_s'] for s in ss) / 3600:.2f} h (GPU + requested CPU/RAM; a floor)")
