"""Who is recast is chosen in the start frame; a job can only name people that were found there."""
import importlib
from pathlib import Path

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
    assert app.QUEUES["quick"].qsize() == 1


def test_a_job_can_only_choose_people_found_at_its_start(app):
    c = TestClient(app.app)
    assert c.post("/api/jobs", json=_params([2])).status_code == 400  # nobody looked yet
    app.UPLOADS["up_clip"]["people"] = {"0.00_portrait": {"state": "ready", "people": [{"id": 1}, {"id": 2}]}}
    assert c.post("/api/jobs", json=_params([2])).status_code == 200
    assert c.post("/api/jobs", json=_params([3])).status_code == 400
    assert c.post("/api/jobs", json=_params([1, 2])).status_code == 400  # one performer, two people


def test_a_ready_made_motion_is_used_as_the_visitors_copy(app):
    """The page sent the motion's id with its copy, and every job from "Use one of ours" was refused."""
    app.UPLOADS["up_clip"]["people"] = {"0.00_portrait": {"state": "ready", "people": [{"id": 1}]}}
    p = _params([1])
    p["motion"]["preset_id"] = "dance_breaking"
    r = TestClient(app.app).post("/api/jobs", json=p)
    assert r.status_code == 200 and "preset_id" not in r.json()["params"]["motion"]
    p["motion"].pop("upload_id")
    assert TestClient(app.app).post("/api/jobs", json=p).status_code == 400


def test_two_people_at_most_can_be_chosen(app):
    """With four chosen, one half behind a kept person bled into them; two leaves SCAIL room for neighbours."""
    app.UPLOADS["up_clip"]["people"] = {"0.00_portrait": {"state": "ready", "people": [{"id": i} for i in (1, 2, 3)]}}
    faces = [{"upload_id": "up_face", "text": t} for t in ("a man in glasses", "a tall knight", "a chef")]
    c = TestClient(app.app)
    assert c.post("/api/jobs", json=_params([1, 2], characters=faces[:2], performers=2)).status_code == 200
    r = c.post("/api/jobs", json=_params([1, 2, 3], characters=faces, performers=3))
    assert r.status_code == 400 and "Up to 2 performers" in r.text


def test_a_posted_character_keeps_only_what_the_page_sends(app):
    """"dressed" names a folder under the data that the server reads and writes: never from a request."""
    app.UPLOADS["up_clip"]["people"] = {"0.00_portrait": {"state": "ready", "people": [{"id": 1}]}}
    sneaky = [{"upload_id": "up_face", "text": "a man in glasses", "dressed": "../../elsewhere", "keep_outfit": "yes"}]
    r = TestClient(app.app).post("/api/jobs", json=_params([1], characters=sneaky))
    assert r.status_code == 200
    assert r.json()["params"]["characters"] == [{"upload_id": "up_face", "text": "a man in glasses", "keep_outfit": False}]


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
    assert app.QUEUES["quick"].qsize() == 0  # found someone: a retry keeps them
    app.UPLOADS["up_clip"]["people"] = {"0.00_portrait": {"state": "ready", "people": []}}
    c.post("/api/uploads/up_clip/people", json={"start": 0, "retry": True})
    assert app.QUEUES["quick"].qsize() == 1


def test_swap_chooses_its_performer_from_the_people_found(app):
    c = TestClient(app.app)
    found = [{"id": 1, "area": 0.30}, {"id": 2, "area": 0.01}, {"id": 3, "area": 0.12}]  # 2: a far-off pedestrian
    app.UPLOADS["up_clip"]["people"] = {"0.00_portrait": {"state": "ready", "people": found}}
    outfit = {**_params(None, mode="swap", characters=[], outfit={"upload_id": "up_face", "text": "a red t-shirt"})}
    outfit["motion"].pop("picks")
    r = c.post("/api/jobs", json=outfit).json()
    assert r["params"]["motion"]["picks"] == [1] and r["params"]["performers"] == 1  # the biggest one
    place = _params(None, mode="swap", characters=[], place={"mode": "describe", "text": "a beach"})
    place["motion"].pop("picks")
    r = c.post("/api/jobs", json=place).json()
    assert r["params"]["motion"]["picks"] == [1, 3] and r["params"]["performers"] == 2  # everyone clearly in view
    app.UPLOADS["up_clip"]["people"] = {}
    r = c.post("/api/jobs", json=place).json()
    assert "picks" not in r["params"]["motion"]  # nobody found yet: by words, as before


def test_a_short_outage_is_retried_before_the_visitor_sees_an_error(app, monkeypatch, tmp_path):
    import contextlib

    from recast import runner

    calls = []

    def submit(client, make, state):
        calls.append(state)
        if len(calls) == 1:  # the first look hits a model folder that didn't answer
            raise RuntimeError("Prompt outputs failed validation")
        return "job"

    monkeypatch.setattr(app, "FIND_RETRIES", (0, 0))
    monkeypatch.setattr(app, "_comfy", contextlib.nullcontext)
    monkeypatch.setattr(app.media, "frame_at", lambda src, dst, **kw: dst.write_bytes(b"x") and dst)
    monkeypatch.setattr(runner, "submit_graph", submit)
    monkeypatch.setattr(runner, "follow", lambda j: j)
    monkeypatch.setattr(runner, "download", lambda j, d, node_id: [])
    app.find_people("up_clip", ("0.00_portrait", 0.0, "portrait", None))
    entry = app.UPLOADS["up_clip"]["people"]["0.00_portrait"]
    assert len(calls) == 2 and "error" not in entry and entry["state"] == "ready"

    calls.clear()
    monkeypatch.setattr(runner, "submit_graph", lambda *a: calls.append(1) or (_ for _ in ()).throw(RuntimeError("down")))
    app.find_people("up_clip", ("0.00_portrait", 0.0, "portrait", None))
    assert len(calls) == 3 and "error" in app.UPLOADS["up_clip"]["people"]["0.00_portrait"]  # then it says so



def test_the_preview_is_the_renders_first_chunk(app, tmp_path):
    work = {"layout": "portrait", "segments": 2, "replace": True, "track": "person", "people": 1, "seed": 777,
            "picks": None, "texts": ["a man in glasses"]}
    p = _params(None)
    full = app._scail_params({"id": "job_x"}, work, tmp_path, p, tmp_path / "r.png", tmp_path / "d.mp4")
    first = app._scail_params({"id": "job_x"}, work, tmp_path, p, tmp_path / "r.png", tmp_path / "d.mp4", chunks=1)
    assert (full.chunks, first.chunks) == (2, 1)
    assert full.seed == first.seed == 777  # the version shown is the version rendered
    g_full, g_first = app.scail.build(full), app.scail.build(first)
    assert all(g_first[k] == g_full[k] for k in g_first if k.startswith("c0_") or k in ("pos", "ref", "sigmas"))
    # a one-chunk video's render graph is the preview's, so the preview's output is delivered as the video
    one = {**work, "segments": 1}
    assert app.scail.build(app._scail_params({"id": "job_x"}, one, tmp_path, p, tmp_path / "r.png", tmp_path / "d.mp4")) \
        == app.scail.build(app._scail_params({"id": "job_x"}, one, tmp_path, p, tmp_path / "r.png", tmp_path / "d.mp4", chunks=1))


def test_who_replaces_whom_is_paired_left_to_right_for_the_preview(app, tmp_path):
    import json

    src = tmp_path / "uploads" / "up_clip" / "people_0.00_portrait"
    src.mkdir(parents=True)
    (src / "frame.png").write_bytes(b"x")
    found = [{"id": 1, "box": [0.6, 0.1, 0.2, 0.8], "area": 0.16, "cx": 0.7, "mask": "person_1.png"},
             {"id": 2, "box": [0.1, 0.1, 0.2, 0.8], "area": 0.16, "cx": 0.2, "mask": "person_2.png"},
             {"id": 3, "box": [0.4, 0.1, 0.1, 0.4], "area": 0.04, "cx": 0.45, "mask": "person_3.png"}]
    (src / "people.json").write_text(json.dumps(found))
    two = [{"upload_id": "up_face", "text": "a man in glasses"}, {"upload_id": "up_face", "text": "a racer"}]
    work = {"people_dir": "uploads/up_clip/people_0.00_portrait"}
    pairs = app._cast_pairs(work, _params([1, 2], characters=two, performers=2), two)
    assert [(c["person"], c["text"]) for c in pairs] == [(2, "a man in glasses"), (1, "a racer")]  # left to right
    assert pairs[0]["box"] == [0.1, 0.1, 0.2, 0.8] and pairs[0]["frame_url"].endswith("people_0.00_portrait/frame.png")
    assert app._cast_pairs(work, _params([1, 2], characters=two, place={"mode": "describe", "text": "a beach"}), two) == []
    assert app._cast_pairs(work, _params([1, 2], characters=two, mode="restyle"), two) == []


def test_quick_work_never_waits_behind_a_render(app, monkeypatch):
    c = TestClient(app.app)
    app.UPLOADS["up_clip"]["people"] = {"0.00_portrait": {"state": "ready", "people": [{"id": 1}]}}
    keep = c.post("/api/jobs", json=_params([1])).json()["id"]
    place = c.post("/api/jobs", json=_params([1], place={"mode": "describe", "text": "a beach"})).json()["id"]
    assert app._lane_of("render", place) == "heavy"
    assert app._lane_of("preview", keep) == "heavy"  # the clip's place previews with a real render
    assert app._lane_of("preview", place) == "quick"  # a picture from the image editor
    restage = c.post("/api/jobs", json=_params([1], mode="swap", characters=[], outfits=[{"text": "a red jacket"}])).json()
    assert app._lane_of("preview", restage["id"]) == "heavy"  # Restage in the clip's place previews with a render too
    assert app._lane_of("find_people", "up_clip") == app._lane_of("describe_upload", "up_face") == "quick"
    monkeypatch.setenv("COMFY_BASE_URL", "http://big:1")
    monkeypatch.delenv("COMFY_QUICK_BASE_URL", raising=False)
    assert app._endpoint("quick") == app._endpoint("heavy")  # one endpoint: both lanes share it
    monkeypatch.setenv("COMFY_QUICK_BASE_URL", "http://small:2")
    assert app._endpoint("quick")[0] == "http://small:2" and app._endpoint("heavy")[0] == "http://big:1"
    with app._comfy("quick") as client:
        assert "small" in repr(client)
    assert app.os.environ["COMFY_BASE_URL"] == "http://big:1"  # put back for everyone else


def test_recast_with_an_outfit_dresses_each_character_once(app, monkeypatch, tmp_path):
    import contextlib
    import shutil
    from types import SimpleNamespace

    from recast import runner

    fake = SimpleNamespace(assets=SimpleNamespace(from_file=lambda path: path.name))
    prompts, graphs = [], []

    def submit(client, make, state):
        g = make()
        graphs.append(state.name)
        prompts.extend(n["inputs"]["prompt"] for k, n in g.items() if k == "pos")
        return state

    def download(gjob, d, node_id):
        d.mkdir(parents=True, exist_ok=True)
        out = d / ("out.png" if gjob.name == "edit_submission.json" else "out.txt")
        out.write_text("words")
        return [out]

    monkeypatch.setattr(app, "_comfy", lambda lane=None: contextlib.nullcontext(fake))
    monkeypatch.setattr(app.media, "clean_image", lambda src, dst, **kw: Path(shutil.copy(src, dst)))
    monkeypatch.setattr(app.media, "edge_colour", lambda path: 0x808080)
    monkeypatch.setattr(app.describe, "build_role", lambda img, role, prefix: {})
    monkeypatch.setattr(app.describe, "parse_role", lambda text, role: "a man in glasses and a red raincoat")
    monkeypatch.setattr(runner, "submit_graph", submit)
    monkeypatch.setattr(runner, "follow", lambda j: j)
    monkeypatch.setattr(runner, "download", download)

    c = {"upload_id": "up_face", "text": "a man in glasses"}
    dressed = app._dressed(c, {"text": "a red raincoat"})
    assert graphs == ["edit_submission.json", "describe_submission.json"]
    assert "now wears a red raincoat" in prompts[0]  # words alone: no outfit picture
    assert dressed["text"] == "a man in glasses and a red raincoat" and dressed["keep_outfit"]
    assert app._photo_of(dressed).name == "dressed.png" and app._photo_of(c).name == "image.png"
    assert app._dressed(c, {"text": "a red raincoat"}) == dressed and len(graphs) == 2  # kept, not redone
    assert app._dressed(c, {"text": "a blue suit"})["dressed"] != dressed["dressed"]  # another outfit, another copy

    p = _params([1], outfit={"text": "a red raincoat"})
    assert "wearing a red raincoat" in app._summary(p) and "stays themselves" not in app._summary(p)


def test_a_render_costs_the_seconds_it_delivers(app):
    c = TestClient(app.app)
    app.UPLOADS["up_clip"]["people"] = {"0.00_portrait": {"state": "ready", "people": [{"id": 1}]}}

    def cost(length, **kw):
        r = c.post("/api/jobs", json=_params([1], motion={"upload_id": "up_clip", "start": 0, "length": length,
                                                          "picks": [1]}, **kw))
        return r.json()["cost_seconds"] if r.status_code == 200 else r.status_code

    assert cost(7) == 7  # 113 frames: a whole chunk and a short one
    assert app._plan(_params([1], motion={"length": 5}), 10) == [81]  # 5 s is one whole chunk, as before
    assert cost(5) == 5 and cost(2) == 2
    assert cost(20) == 10  # the clip has 10 seconds: only those are charged
    assert cost(1) == cost(21) == cost("5") == 400
    assert app._cost({"cost_renders": 2}) == 10  # jobs from before credits


def test_straight_to_the_video_holds_its_credits_from_the_start(app, monkeypatch):
    c = TestClient(app.app)
    app.UPLOADS["up_clip"]["people"] = {"0.00_portrait": {"state": "ready", "people": [{"id": 1}]}}
    monkeypatch.setattr(app, "_enqueue", lambda *a: None)
    left = c.get("/api/session").json()["credits_left"]
    j = c.post("/api/jobs", json=_params([1], auto=True)).json()
    assert j["auto"] is True and "auto" not in j["params"]
    c.post(f"/api/jobs/{j['id']}/preview", json={})
    assert c.get("/api/session").json()["credits_left"] == left - 5  # held while it is being prepared
    draft = c.post("/api/jobs", json=_params([1])).json()
    c.post(f"/api/jobs/{draft['id']}/preview", json={})
    assert c.get("/api/session").json()["credits_left"] == left - 5  # a draft is free until approved
    app._update(app.JOBS[j["id"]], state="failed", error={"message": "x", "refunded": True})
    assert c.get("/api/session").json()["credits_left"] == left  # given back
    monkeypatch.setattr(app, "CREDITS_TOTAL", 3)
    big = c.post("/api/jobs", json=_params([1], auto=True)).json()
    r = c.post(f"/api/jobs/{big['id']}/preview", json={})
    assert r.status_code == 402 and "needs 5 credits" in r.json()["message"]
    assert c.post("/api/jobs", json=_params([1], auto="yes")).status_code == 400


def test_only_a_bust_for_a_performer_showing_more_body_gets_its_body_drawn(app, monkeypatch, tmp_path):
    import json as _json

    from PIL import Image

    home = app._upload_path("up_face", "image").parent
    Image.new("RGB", (400, 400)).save(home / "image.png")
    (home / "cutout_people").mkdir()
    (home / "cutout_people" / "people.json").write_text(_json.dumps(
        [{"id": 1, "box": [0.0, 0.1, 1.0, 0.9], "area": 0.6, "cx": 0.5, "mask": "person_1.png"}]))  # to the edge
    frame = tmp_path / "frame.png"
    Image.new("RGB", (480, 832)).save(frame)
    c = {"upload_id": "up_face", "text": "a man"}
    lengths = {}
    monkeypatch.setattr(app, "_body_length", lambda image, box: lengths["photo" if image.name == "image.png" else "clip"])
    tall, square = (0.3, 0.1, 0.3, 0.6), (0.1, 0.4, 0.8, 0.6)  # in the frame: a tall outline, a wide one
    lengths.update(photo=1.6, clip=6.3)
    assert app._needs_body(c, square, frame)  # a bust for a performer seen to the waist or more
    lengths.update(photo=1.6, clip=2.0)
    assert not app._needs_body(c, square, frame)  # a head-and-shoulders performer: the bust is right
    lengths.update(photo=4.5, clip=8.0)
    assert not app._needs_body(c, tall, frame)  # waist-up photos render fine
    lengths.update(photo=1.6, clip=None)  # an animal: by where it ends, or by shape
    assert app._needs_body(c, tall, frame) and not app._needs_body(c, (0.1, 0.5, 0.8, 0.5), frame)
    lengths.update(photo=None, clip=6.0)  # a drawing: left as it is
    assert not app._needs_body(c, square, frame)
