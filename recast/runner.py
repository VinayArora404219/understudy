"""Run a recast through the official Comfy SDK (comfy-sdk) against the
self-hosted comfy-api-proxy. `COMFY_BASE_URL` names the proxy; nothing here
talks to ComfyUI's legacy /prompt endpoint.

A submission records its own idempotency key and job id *before* waiting,
so a caller that crashes or loses the connection reattaches to the job
instead of rendering it twice.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from comfy_sdk import Comfy, IdempotencyKeyReuse, JobFailed, Progress, StatusChange

from . import graph

ProgressFn = Callable[[dict], None]
DEAD = frozenset({"failed", "canceled", "expired"})  # comfy-sdk terminal states other than "succeeded"


@dataclass
class Submission:
    idempotency_key: str
    job_id: str | None = None
    submitted_at: float = field(default_factory=time.time)

    def save(self, path: Path) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self)))
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> "Submission | None":
        return cls(**json.loads(path.read_text())) if path.exists() else None


def _asset(client: Comfy, value):
    """Local paths become SDK asset handles (uploaded lazily, deduped by hash)."""
    if isinstance(value, Path):
        return client.assets.from_file(value)
    return value


def submit(client: Comfy, params: graph.RecastParams, state: Path, *, metadata: dict | None = None):
    """Submit a recast once (see `submit_graph`)."""
    def make():
        params.reference = _asset(client, params.reference)
        params.drive = _asset(client, params.drive)
        return graph.build(params)
    return submit_graph(client, make, state, metadata=metadata)


def submit_graph(client: Comfy, make: Callable[[], dict], state: Path, *, metadata: dict | None = None):
    """Submit the graph `make()` returns, once. If `state` already names a
    job, reattach to it instead of building or uploading anything."""
    sub = Submission.load(state)
    if sub and sub.job_id:
        job = client.jobs.get(sub.job_id)
        if job.status not in DEAD:
            return job  # still queued/running, or already succeeded: reattach, never render twice
        sub = None  # failed, canceled or expired: a re-run means a fresh submission
    sub = sub or Submission(idempotency_key=f"recast-{uuid.uuid4().hex}")
    sub.save(state)  # the key is on disk before any bytes leave

    wf = client.workflows.from_json(make())
    try:
        job = client.submit(wf, idempotency_key=sub.idempotency_key, metadata=metadata)
    except IdempotencyKeyReuse:
        # an earlier attempt reached the server but its job id never reached disk;
        # find it rather than render twice
        job = _find_by_key(client, sub.idempotency_key, metadata)
    sub.job_id = job.id
    sub.save(state)
    return job


def _find_by_key(client: Comfy, key: str, metadata: dict | None):
    """Jobs carry their submission's metadata; a unique label finds the one
    an earlier, lost attempt created."""
    if metadata:
        for summary in client.list_jobs(metadata=metadata, limit=5):
            return client.jobs.get(summary.id)
    raise RuntimeError(f"job for idempotency key {key} exists but cannot be located; check the proxy")


def follow(job, on_progress: ProgressFn | None = None):
    """Stream progress for display; the final state comes from polling."""
    if on_progress is not None:
        try:
            for ev in job.events():
                if isinstance(ev, Progress):
                    on_progress({"kind": "progress", "value": ev.value, "node": ev.current_node,
                                 "step": ev.step, "steps": ev.steps,
                                 "nodes_done": ev.nodes_done, "nodes_total": ev.nodes_total})
                elif isinstance(ev, StatusChange):
                    on_progress({"kind": "status", "status": ev.status, "queue_position": ev.queue_position})
        except Exception as e:  # the stream is advisory; never fail a render over it
            on_progress({"kind": "stream_lost", "error": type(e).__name__})
    try:
        return job.result()
    except JobFailed as e:
        raise RenderFailed(job.id, getattr(e, "error", None)) from e


class RenderFailed(RuntimeError):
    """A job ended failed. Carries the server's reason in one readable line."""

    def __init__(self, job_id: str, error) -> None:
        self.job_id = job_id
        self.code = getattr(error, "code", None) or "failed"
        message = str(getattr(error, "message", None) or error or "no reason given")
        self.reason = message.strip().splitlines()[0][:300]
        super().__init__(f"job {job_id} failed ({self.code}): {self.reason}")


def download(job, out_dir: Path, node_id: str = graph.FINAL_NODE) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for o in job.get_outputs(node_id):
        name = Path(o.name).name  # server-chosen; never let it climb out of out_dir
        paths.append(o.to_file(out_dir / name))
    return paths
