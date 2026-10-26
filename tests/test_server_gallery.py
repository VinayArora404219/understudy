"""Examples to start from, and recreating a render: the visitor gets their own copies, with every choice kept."""
import importlib
import json

import pytest
from fastapi.testclient import TestClient

PEOPLE = {"0.00_portrait": {"state": "ready", "frame_url": "/api/files/uploads/up_clip/people_0.00_portrait/frame.png",
                            "people": [{"id": 1, "box": [0, 0, 0.4, 1], "area": 0.3, "cx": 0.2},
                                       {"id": 2, "box": [0.5, 0, 0.4, 1], "area": 0.3, "cx": 0.7}]}}
PARAMS = {"mode": "recast", "motion": {"upload_id": "up_clip", "start": 0, "length": 5, "picks": [1, 2]},
          "performers": 2, "subject": "person", "place": {"mode": "keep"}, "finish": "720p", "audio": "original",
          "auto": True, "characters": [{"upload_id": "up_face", "text": "a chef", "keep_outfit": False},
                                       {"upload_id": "up_face", "text": "an astronaut", "keep_outfit": False}]}


def _upload(root, uid, kind, **extra):
    d = root / uid
    d.mkdir(parents=True)
    (d / ("original.mp4" if kind == "video" else "image.png")).write_bytes(b"x")
    u = {"id": uid, "kind": kind, "_file": f"uploads/{uid}/original.mp4", "_box": [480, 832, 0, 0],
         "info": {"seconds": 10}, "thumb_url": f"/api/files/uploads/{uid}/thumb.jpg",
         "url": f"/api/files/uploads/{uid}/original.mp4", **extra}
    (d / "upload.json").write_text(json.dumps(u))
    return u


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("RECAST_DATA", str(tmp_path))
    import server.app as mod
    mod = importlib.reload(mod)
    monkeypatch.setattr(mod.media, "layout_for", lambda w, h: "portrait")
    item = tmp_path / "gallery" / "items" / "duo"
    _upload(item / "uploads", "up_clip", "video", people=PEOPLE, _owner="ln_maker")
    _upload(item / "uploads", "up_face", "image", descriptions={"character": "a chef"}, _owner="ln_maker")
    (item / "item.json").write_text(json.dumps({"title": "Two dancers, recast", "params": PARAMS, "order": 0,
                                                "choices": [{"label": "Motion", "thumb": "uploads/up_clip/thumb.jpg"}]}))
    return mod


def test_an_example_becomes_the_visitors_own_uploads_once(app):
    c = TestClient(app.app)
    r = c.post("/api/gallery/duo/recreate").json()
    clip, face = r["params"]["motion"]["upload_id"], r["params"]["characters"][0]["upload_id"]
    assert clip not in ("up_clip", "up_face") and face not in ("up_clip", "up_face") and clip != face
    assert r["params"]["characters"][1]["upload_id"] == face  # one photo used twice is copied once
    assert app.UPLOADS[clip]["_owner"] == app.LOCAL and app.UPLOADS[clip]["url"] == f"/api/files/uploads/{clip}/original.mp4"
    assert r["people"]["key"] == "0.00_portrait" and r["people"]["frame_url"].startswith(f"/api/files/uploads/{clip}/")
    assert r["params"]["motion"]["picks"] == [1, 2] and "auto" not in r["params"] and r["title"] == "Two dancers, recast"
    assert r["uploads"][face]["descriptions"] == {"character": "a chef"}
    again = c.post("/api/gallery/duo/recreate").json()
    assert again["params"]["motion"]["upload_id"] == clip  # not copied a second time


def test_the_gallery_lists_its_examples(app):
    [x] = TestClient(app.app).get("/api/gallery").json()
    assert x["id"] == "duo" and x["mode"] == "Recast" and x["after_url"] == "/api/files/gallery/items/duo/after.mp4"
    assert x["choices"] == [{"label": "Motion", "text": None, "thumb_url": "/api/files/gallery/items/duo/uploads/up_clip/thumb.jpg"}]


def test_unknown_examples_are_refused(app):
    c = TestClient(app.app)
    assert c.post("/api/gallery/nope/recreate").status_code == 404
    assert c.post("/api/gallery/..%2Fitems/recreate").status_code == 404


def test_a_render_is_recreated_from_its_own_uploads_and_only_by_its_owner(app, tmp_path):
    c = TestClient(app.app)
    r = c.post("/api/gallery/duo/recreate").json()
    p = {**PARAMS, "motion": r["params"]["motion"], "characters": r["params"]["characters"]}
    app.JOBS["job_a"] = {"id": "job_a", "title": "Recast · 5 s", "params": p, "_owner": app.LOCAL, "state": "done"}
    mine = c.post("/api/jobs/job_a/recreate").json()
    assert mine["params"]["motion"] == p["motion"] and mine["title"] == "Recast · 5 s"
    assert mine["people"]["list"][1]["id"] == 2
    app.JOBS["job_b"] = {"id": "job_b", "params": p, "_owner": "ln_other", "state": "done"}
    assert c.post("/api/jobs/job_b/recreate").status_code == 404
