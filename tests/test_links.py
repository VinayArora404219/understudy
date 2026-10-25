"""Judge links: each link sees only its own work and has its own credits (seconds of video)."""
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


def _client(app, name, credits=30):
    token, link = app.LINKS.create(name, credits=credits, days=10)
    c = TestClient(app.app)
    assert c.post("/api/links/claim", json={"token": token}).status_code == 200
    return c, link


def _job(app, owner, jid, state="done", cost=1):
    (app.DATA / "jobs" / jid).mkdir(parents=True)
    (app.DATA / "jobs" / jid / "recast.mp4").write_bytes(b"x")
    app.JOBS[jid] = {"id": jid, "created_at": "2026-10-24T00:00:00", "state": state, "title": "t",
                     "params": {"mode": "recast"}, "cost_seconds": cost, "_owner": owner}


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


def test_each_link_has_its_own_credits_and_a_refund_goes_back(app):
    a, la = _client(app, "Judge A", credits=30)
    b, _ = _client(app, "Judge B", credits=30)
    _job(app, la["id"], "job_1", cost=7)
    _job(app, la["id"], "job_2", state="failed", cost=5)  # refunded: costs nothing
    assert a.get("/api/session").json() == {"kind": "judge", "name": "Judge A", "credits_left": 23, "credits_total": 30}
    assert b.get("/api/session").json()["credits_left"] == 30


def test_links_and_jobs_from_before_credits_count_in_renders_of_five_seconds(app):
    a, la = _client(app, "Judge A")
    data = json.loads(app.LINKS.path.read_text())
    data["links"][0] = {k: v for k, v in data["links"][0].items() if k != "credits"} | {"cap": 4}
    app.LINKS.path.write_text(json.dumps(data))
    app.LINKS._seen = None
    app.JOBS["job_old"] = {"id": "job_old", "state": "done", "params": {"mode": "recast"}, "cost_renders": 1,
                           "_owner": la["id"]}
    assert a.get("/api/session").json()["credits_left"] == 15 and app._cost(app.JOBS["job_old"]) == 5


def test_an_expired_link_stops_working(app):
    token, link = app.LINKS.create("Judge C", credits=5, days=1)
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


def test_the_admin_page_makes_lists_and_revokes_links(app, monkeypatch):
    admin = TestClient(app.app)
    assert admin.get("/api/admin/links").status_code == 404  # no password set: there is no admin page
    monkeypatch.setattr(app, "ADMIN_PASSWORD", "open sesame")
    assert admin.get("/api/admin/session").json() == {"signed_in": False}
    assert admin.get("/api/admin/links").status_code == 401
    assert admin.post("/api/admin/login", json={"password": "guess"}).status_code == 401
    assert admin.post("/api/admin/login", json={"password": "open sesame"}).status_code == 200
    assert admin.post("/api/admin/links", json={"name": "Judge D", "credits": 0, "days": 5}).status_code == 400

    made = admin.post("/api/admin/links", json={"name": "Judge D", "credits": 60, "days": 5}).json()
    token = made["path"].removeprefix("/j/")
    judge = TestClient(app.app)
    assert judge.post("/api/links/claim", json={"token": token}).status_code == 200
    _job(app, made["link"]["id"], "job_d", cost=7)
    row = admin.get("/api/admin/links").json()[0]
    assert (row["name"], row["used"], row["left"], row["videos"], row["live"]) == ("Judge D", 7, 53, 1, True)
    assert token not in json.dumps(admin.get("/api/admin/links").json())  # the address is shown once, at making
    assert judge.get("/api/admin/links").status_code == 401  # a judge's cookie is not the admin's

    assert admin.post(f"/api/admin/links/{row['id']}/revoke").json()["live"] is False
    assert judge.get("/api/session").json()["kind"] == "guest"  # at once, in the browser that opened it
    assert judge.post("/api/links/claim", json={"token": token}).status_code == 404
    admin.post("/api/admin/logout")
    assert admin.get("/api/admin/links").status_code == 401


def test_a_ready_made_motion_becomes_the_visitors_own_upload(app, monkeypatch):
    d = app.PRESETS / "studio_duo"
    d.mkdir(parents=True)
    (d / "clip.mp4").write_bytes(b"x")
    (d / "thumb.jpg").write_bytes(b"x")
    (d / "preset.json").write_text(json.dumps({"title": "Studio duo", "subtitle": "Two dancers", "seconds": 5.8}))
    monkeypatch.setattr(app, "_describe_video", lambda raw, d: {"thumb_url": "", "url": "", "checks": [],
                                                                 "info": {"seconds": 5.8}})
    guest = TestClient(app.app)
    listed = guest.get("/api/presets").json()  # the landing page may show them
    assert [p["id"] for p in listed] == ["studio_duo"] and guest.get(listed[0]["thumb_url"]).status_code == 200
    assert guest.post("/api/presets/studio_duo/use").status_code == 401  # using one needs a link
    a, la = _client(app, "Judge A")
    b, _ = _client(app, "Judge B")
    mine = a.post("/api/presets/studio_duo/use").json()
    assert a.post("/api/presets/studio_duo/use").json()["id"] == mine["id"]  # one copy each, people found once
    assert b.post("/api/presets/studio_duo/use").json()["id"] != mine["id"]
    assert b.get(f"/api/uploads/{mine['id']}").status_code == 404
    assert a.post("/api/presets/..%2Fjobs/use").status_code == 404
