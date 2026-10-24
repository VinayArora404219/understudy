"""Who is recast is chosen in the start frame; a job can only name people that were found there."""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("RECAST_DATA", str(tmp_path))
    import server.app as mod
    mod = importlib.reload(mod)
    for uid, kind in (("up_clip", "video"), ("up_face", "image")):
        d = tmp_path / "uploads" / uid
        d.mkdir(parents=True)
        (d / ("original.mp4" if kind == "video" else "image.png")).write_bytes(b"x")
        mod.UPLOADS[uid] = {"id": uid, "kind": kind, "_file": f"uploads/{uid}/original.mp4", "_box": [480, 832, 0, 0],
                            "info": {"seconds": 10}, "thumb_url": "", "url": ""}
    monkeypatch.setattr(mod.media, "layout_for", lambda w, h: "portrait")
    return mod


def _params(picks, **kw):
    return {"mode": "recast", "motion": {"upload_id": "up_clip", "start": 0, "length": 5, "picks": picks},
            "performers": 1, "subject": "person", "characters": [{"upload_id": "up_face", "text": "a man in glasses"}],
            "place": {"mode": "keep"}, "finish": "480p", "audio": "original", **kw}


def test_finding_people_is_queued_once_per_start_point(app):
    c = TestClient(app.app)
    r = c.post("/api/uploads/up_clip/people", json={"start": 0})
    assert r.status_code == 200 and r.json()["key"] == "0.00_portrait"
    assert r.json()["people"]["0.00_portrait"] == {"state": "finding"}
    c.post("/api/uploads/up_clip/people", json={"start": 0})
    assert app.TASKS.qsize() == 1


def test_a_job_can_only_choose_people_found_at_its_start(app):
    c = TestClient(app.app)
    assert c.post("/api/jobs", json=_params([2])).status_code == 400  # nobody looked yet
    app.UPLOADS["up_clip"]["people"] = {"0.00_portrait": {"state": "ready", "people": [{"id": 1}, {"id": 2}]}}
    assert c.post("/api/jobs", json=_params([2])).status_code == 200
    assert c.post("/api/jobs", json=_params([3])).status_code == 400
    assert c.post("/api/jobs", json=_params([1, 2])).status_code == 400  # one performer, two people


def test_other_modes_ignore_a_choice(app):
    r = TestClient(app.app).post("/api/jobs", json=_params([9], mode="restyle", characters=[], style="anime"))
    assert r.status_code == 200 and "picks" not in r.json()["params"]["motion"]


def test_chosen_performers_need_no_person_or_animal_answer(app):
    app.UPLOADS["up_clip"]["people"] = {"0.00_portrait": {"state": "ready", "people": [{"id": 1}]}}
    p = _params([1])
    del p["subject"]
    r = TestClient(app.app).post("/api/jobs", json=p)
    assert r.status_code == 200 and r.json()["params"]["subject"] == "person"  # the reader corrects it later
    del p["motion"]["picks"]
    assert TestClient(app.app).post("/api/jobs", json=p).status_code == 400  # without a choice it is still asked


def test_the_preview_frame_outlines_the_chosen_and_dims_the_rest(app, tmp_path):
    from PIL import Image

    Image.new("RGB", (40, 40), (200, 200, 200)).save(tmp_path / "frame.png")
    m = Image.new("L", (40, 40), 0)
    m.paste(255, (10, 10, 30, 30))
    m.save(tmp_path / "pick0.png")
    out = Image.open(app._picked_frame({"picks": ["pick0.png"]}, tmp_path, tmp_path / "frame.png"))
    assert out.getpixel((20, 20)) == (200, 200, 200)  # the chosen one as filmed
    assert out.getpixel((2, 2)) == (80, 80, 80)  # everyone and everything else dimmed
    assert out.getpixel((9, 20)) == app.PICKED  # outlined
    assert app._picked_frame({}, tmp_path, tmp_path / "frame.png") == tmp_path / "frame.png"


def test_try_again_looks_again_only_after_a_miss(app):
    c = TestClient(app.app)
    app.UPLOADS["up_clip"]["people"] = {"0.00_portrait": {"state": "ready", "people": [{"id": 1}]}}
    c.post("/api/uploads/up_clip/people", json={"start": 0, "retry": True})
    assert app.TASKS.qsize() == 0  # found someone: a retry keeps them
    app.UPLOADS["up_clip"]["people"] = {"0.00_portrait": {"state": "ready", "people": []}}
    c.post("/api/uploads/up_clip/people", json={"start": 0, "retry": True})
    assert app.TASKS.qsize() == 1
