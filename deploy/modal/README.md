# Modal backend

The GPUs behind the judge build. Two Modal endpoints ("lanes"), each one container running ComfyUI with
comfy-api-proxy 0.1.6 in front of it, exposed over HTTPS and guarded by a key. The app reaches them the
same way it reaches any other ComfyUI: comfy-sdk 0.5.0 → comfy-api-proxy. Switching backends is a change
in `.env`. Nothing in `server/`, `recast/` or `web/` knows which backend it is talking to.

| Lane | Modal class | GPU | Runs | Idle → zero |
|---|---|---|---|---|
| heavy | `Comfy` | L40S 48 GB | renders, and the Recast-in-the-clip's-place preview (a real 5 s render) | 2 min (testing) |
| quick | `ComfyQuick` | L4 24 GB | finding people, reading photos and clips, image-edit previews, cut-outs | 2 min (testing) |

The server decides which lane a task goes to (`server/app.py`, `_lane_of`). Two lanes so that a judge who
starts a render and then opens another mode gets the picker in seconds instead of after the render. Both
lanes share the image and the models Volume; each has its own GPU, its own state and its own cost log. The
GPUs were picked by measurement (`bench/RESULTS.md`, "Running on Modal"): the L4 is the cheapest card that
holds every quick-lane model without a partial load.

## Run it

```bash
pip install modal && modal setup                      # once per machine

# the key the SDK will send; keep the file out of git
python3 -c "import secrets; print('COMFY_API_KEY=' + secrets.token_urlsafe(32))" > private/modal.env
modal secret create recast-api --from-dotenv private/modal.env    # needs python-dotenv

modal run    deploy/modal/app.py::download            # once: ~79 GiB from Hugging Face into a Volume
modal deploy deploy/modal/app.py                      # publishes both lanes' endpoints
modal run    deploy/modal/app.py::check               # boots each lane and reports GPU, nodes, models
```

Then, in `.env`:

```bash
COMFY_BASE_URL=https://<workspace>--performance-recast-comfy-api.<region>.modal.run         # heavy
COMFY_QUICK_BASE_URL=https://<workspace>--performance-recast-comfyquick-api.<region>.modal.run
COMFY_API_KEY=<same value as in private/modal.env>                                       # both lanes
```

and run the app as usual (`tools/serve_local.sh`). Leaving `COMFY_QUICK_BASE_URL` unset sends both lanes'
work to the heavy endpoint. `modal deploy` prints the URLs, wrapped; to read them whole:
`python3 -c "import modal; print(modal.Cls.from_name('performance-recast', 'ComfyQuick')().api.get_web_url())"`.

`RECAST_GPU=H100` or `RECAST_QUICK_GPU=A10 modal deploy deploy/modal/app.py` redeploys a lane on another
GPU at the same URL.

**Waking the lanes.** Any request starts a lane's container, so a judge page can wake both with
`GET <lane URL>/api/v2/health`, which needs no key. Cold start to a ready endpoint measured 15 s (heavy)
and 30 s (quick); the first task then loads its models.

## What runs in the container

| Piece | Version | Why this one |
|---|---|---|
| ComfyUI | v0.41.3 (`8713616f`) | the reference machine's version; SAM3, SCAIL-2, Wan, TextGenerate and background removal are core nodes in it |
| torch | 2.13.0+cu130 | same build as the reference; Modal's hosts run driver r610 (CUDA 13.3), so cu130 runs |
| Python | 3.13 | the reference runs 3.14, but Modal's image builder stops at 3.13. Kernels and weights are unaffected |
| Custom nodes | ComfyUI-GGUF 1.1.10, VideoHelperSuite 1.7.9, controlnet_aux 1.1.5 | Registry versions as installed on the reference (Registry zips, not git `main`) |
| Everything else | `reference-constraints.txt` | the reference's installed packages, used as constraints. Read from its `*.dist-info` directories, because its `pip freeze` was stale after an interrupted upgrade and reported older comfy-kitchen/comfy-aimdo than the ones that import (comfy-kitchen holds the quantised-matmul kernels, so this matters) |
| Models | `manifests/models.json` | each file is pinned to a Hugging Face commit and checked against its LFS size and sha256 after download |

ComfyUI starts with `--disable-comfy-compiler`, as on the reference. The reference's
`--disable-pinned-memory` and `--cache-ram 8` work around a 16 GB card with 32 GB of RAM. They change
speed, not results, so they are not set here.

## Auth

comfy-sdk sends `COMFY_API_KEY` as `Authorization: Bearer <key>`, and only to the origin named by
`COMFY_BASE_URL`. The proxy has a matching static-token gate (`--token`). `front.py` builds the proxy
app with that gate and refuses to start without a key. `GET /api/v2/health` stays open, as the proxy
intends.

The one thing `front.py` adds is a scheme fix. The proxy builds every absolute link it returns (job
URLs, output and asset URLs) from the incoming request's scheme and Host, and ignores
`X-Forwarded-*`. Modal terminates TLS and forwards plain HTTP, so without the fix the SDK receives
`http://` links. It treats those as a foreign origin, withholds the key, and the first output
download fails with 401. The only way into the container is Modal's HTTPS edge, so `front.py` marks
every request as `https` before the proxy sees it.

## State, restarts, and what can still go wrong

- **One container per lane, ever** (`max_containers=1` on each). The proxy's job table and ComfyUI's queue live in that
  container. A second container would be a second, empty proxy.
- **Each lane has its own directory** on the `recast-state` Volume (`heavy/`, `quick/`): proxy snapshot,
  input dir, cost log and session files. Two proxies sharing an asset index or an input dir would break
  the dedup rule below. A job id is only ever polled on the lane that created it.
- **Proxy state survives restarts.** The SQLite database lives on local disk, is snapshotted to the
  lane's directory every 20 s and at shutdown (SQLite online backup), and is restored at boot.
- **ComfyUI's input dir lives on the same Volume.** The proxy dedups uploads by hash and never checks
  that the file still exists. A restored asset index pointing at a wiped input dir would make the next
  upload of the same clip a no-op, and the job would fail on a missing file.
- **A restart mid-render costs a re-render.** After a restart the proxy reports a job it remembers,
  but the fresh ComfyUI never ran, as `expired`. `recast/runner.py` already resubmits on `expired`.
- **Deploying mid-render loses the render.** `modal deploy` starts the new container while the old one
  drains. Deploy between renders.
- **Scale-down.** The container stays up while requests arrive (the server polls running jobs). After
  the last request it stays warm for the idle window (2 minutes while testing; `RECAST_SCALEDOWN_S` and `RECAST_QUICK_SCALEDOWN_S` set it at deploy), then scales to zero. If the local server is stopped
  mid-render for longer than that, the container goes away and the job comes back as `expired`.

### Server change requested (not made here)

A job submitted in the last ≤20 s before a hard container kill is not in the restored snapshot. When
the server reattaches with `client.jobs.get(job_id)`, the SDK raises `comfy_sdk.exceptions.NotFound`
(HTTP 404). `recast/runner.submit_graph` only handles a job that is found in a dead state, so this
becomes a failed job instead of a fresh submission. The same thing happens on the reference machine
whenever its proxy state dir is lost. The fix, in `recast/runner.py`:

```python
from comfy_sdk.exceptions import NotFound
...
    if sub and sub.job_id:
        try:
            job = client.jobs.get(sub.job_id)
        except NotFound:          # the proxy lost the job (state reset); render it again
            job = None
        if job is not None and job.status not in DEAD:
            return job
        sub = None
```

## Cost

Each lane appends one line per finished ComfyUI prompt to its `costs.jsonl`: task kind (from the models
the graph loads), GPU seconds from ComfyUI's own execution timestamps, dollars, and whether any model
loaded partially. Each container also rewrites a session file every 20 s with its lifetime so far, which
is what Modal bills (boot, tasks and the idle tail); it survives a hard stop that skips the exit hook.

```bash
modal run deploy/modal/app.py::costs     # seconds and $ per task kind, per lane and GPU; total per lane
```

Dollars are Modal list prices for the GPU plus the container's requested CPU and RAM (2 cores,
16 GiB). Memory used above the request is billed too but not counted here, so treat these figures as
a floor. Measured numbers are in `bench/RESULTS.md`.
