"""Restyle's scene line: read automatically, editable only once it exists, locked once a render starts."""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("RECAST_DATA", str(tmp_path))
    import server.app as mod
    mod = importlib.reload(mod)
    return mod


def _job(mod, **fields):
    j = {"id": "job_test", "state": "awaiting_approval", "params": {"mode": "restyle"},
         "_work": {"scene": "a man on a street"}, **fields}
    mod.JOBS[j["id"]] = j
    (mod._job_dir(j["id"])).mkdir(parents=True, exist_ok=True)
    return j


def test_edit_is_refused_while_reading(app):
    _job(app, scene={"state": "reading", "text": ""})
    r = TestClient(app.app).post("/api/jobs/job_test/scene", json={"text": "a man in sunglasses"})
    assert r.status_code == 409 and "still reading" in r.json()["message"]


def test_edit_once_ready_is_saved_for_the_render(app):
    j = _job(app, scene={"state": "ready", "text": "a man on a street", "edited": False})
    r = TestClient(app.app).post("/api/jobs/job_test/scene", json={"text": "  a man   who puts on sunglasses "})
    assert r.status_code == 200
    assert j["scene"] == {"state": "ready", "text": "a man who puts on sunglasses", "edited": True}
    assert j["_work"]["scene"] == "a man who puts on sunglasses"


@pytest.mark.parametrize("state", ["queued", "rendering", "finishing", "done"])
def test_edit_is_locked_once_a_render_starts(app, state):
    _job(app, state=state, scene={"state": "ready", "text": "a man", "edited": False})
    r = TestClient(app.app).post("/api/jobs/job_test/scene", json={"text": "a woman"})
    assert r.status_code == 409


def test_edit_must_be_a_real_line(app):
    _job(app, scene={"state": "ready", "text": "a man", "edited": False})
    assert TestClient(app.app).post("/api/jobs/job_test/scene", json={"text": " x "}).status_code == 400


def test_cancel_reaches_the_gpu_without_a_live_handle(app, monkeypatch):
    """Just after a restart nothing follows the job yet; the stored submission id still cancels it."""
    j = _job(app, state="rendering")
    (app._job_dir(j["id"]) / "render_submission_abc.json").write_text('{"job_id": "gpu-123"}')
    cancelled = []

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        class jobs:
            @staticmethod
            def get(job_id):
                return type("J", (), {"cancel": lambda self: cancelled.append(job_id)})()

    monkeypatch.setattr(app, "_comfy", lambda lane=None: Client())
    r = TestClient(app.app).post("/api/jobs/job_test/cancel")
    assert r.status_code == 200 and j["state"] == "cancelled" and cancelled == ["gpu-123"]
