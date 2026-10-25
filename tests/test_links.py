"""Judge links: each link sees only its own work and has its own render cap."""
import importlib
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("RECAST_DATA", str(tmp_path))
    monkeypatch.setenv("RECAST_LINKS", "1")
    import server.app as mod
    mod = importlib.reload(mod)
    yield mod
    monkeypatch.delenv("RECAST_LINKS")
    importlib.reload(mod)


def _client(app, name, cap=3):
    token, link = app.LINKS.create(name, cap=cap, days=10)
    c = TestClient(app.app)
    assert c.post("/api/links/claim", json={"token": token}).status_code == 200
    return c, link


def _job(app, owner, jid, state="done", cost=1):
    (app.DATA / "jobs" / jid).mkdir(parents=True)
    (app.DATA / "jobs" / jid / "recast.mp4").write_bytes(b"x")
    app.JOBS[jid] = {"id": jid, "created_at": "2026-10-24T00:00:00", "state": state, "title": "t",
                     "params": {"mode": "recast"}, "cost_renders": cost, "_owner": owner}


def test_without_a_link_only_the_landing_page_answers(app):
    c = TestClient(app.app)
    assert c.get("/api/session").json()["kind"] == "guest"
    assert c.get("/api/gallery").status_code == 200
    assert c.get("/api/jobs").status_code == 401
    assert c.post("/api/links/claim", json={"token": "made-up"}).status_code == 404


def test_each_link_sees_only_its_own_work(app):
    a, la = _client(app, "Judge A")
    b, lb = _client(app, "Judge B")
    _job(app, la["id"], "job_a")
    assert [j["id"] for j in a.get("/api/jobs").json()] == ["job_a"]
    assert b.get("/api/jobs").json() == []
    assert b.get("/api/jobs/job_a").status_code == 404
    assert a.get("/api/files/jobs/job_a/recast.mp4").status_code == 200
    assert b.get("/api/files/jobs/job_a/recast.mp4").status_code == 404  # files too, not just the lists
    assert TestClient(app.app).get("/api/files/gallery/../jobs/job_a/recast.mp4").status_code in (401, 404)
    assert "_owner" not in a.get("/api/jobs/job_a").json()


def test_each_link_has_its_own_cap_and_a_refund_goes_back(app):
    a, la = _client(app, "Judge A", cap=3)
    b, _ = _client(app, "Judge B", cap=3)
    _job(app, la["id"], "job_1", cost=2)
    _job(app, la["id"], "job_2", state="failed", cost=1)  # refunded: costs nothing
    assert a.get("/api/session").json() == {"kind": "judge", "name": "Judge A", "renders_left": 1, "renders_total": 3}
    assert b.get("/api/session").json()["renders_left"] == 3


def test_an_expired_link_stops_working(app):
    token, link = app.LINKS.create("Judge C", cap=1, days=1)
    data = json.loads(app.LINKS.path.read_text())
    data["links"][0]["expires"] = "2020-01-01T00:00:00+00:00"
    app.LINKS.path.write_text(json.dumps(data))
    assert TestClient(app.app).post("/api/links/claim", json={"token": token}).status_code == 404
    assert app.LINKS.find(token) is None
    assert token not in app.LINKS.path.read_text()  # only its hash is kept: the file can't sign anyone in


def test_a_job_cant_use_someone_elses_upload(app):
    a, la = _client(app, "Judge A")
    b, _ = _client(app, "Judge B")
    d = app.DATA / "uploads" / "up_a"
    d.mkdir(parents=True)
    (d / "original.mp4").write_bytes(b"x")
    app.UPLOADS["up_a"] = {"id": "up_a", "kind": "video", "_file": "uploads/up_a/original.mp4", "_owner": la["id"],
                           "info": {"seconds": 10}}
    assert a.get("/api/uploads/up_a").status_code == 200
    assert b.get("/api/uploads/up_a").status_code == 404
    r = b.post("/api/jobs", json={"mode": "restyle", "style": "anime", "motion": {"upload_id": "up_a", "start": 0,
               "length": 5}, "performers": 1, "subject": "person", "place": {"mode": "keep"}, "finish": "480p",
               "audio": "original"})
    assert r.status_code == 400 and "missing" in r.json()["message"]
