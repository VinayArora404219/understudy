"""Each mode changes only its own thing; the server refuses mixtures the UI never sends."""
import pytest

pytest.importorskip("fastapi")

from server import app as srv  # noqa: E402


@pytest.fixture
def uploads(monkeypatch, tmp_path):
    monkeypatch.setattr(srv, "DATA", tmp_path)
    for uid, kind in (("vid", "video"), ("img", "image")):
        (tmp_path / "uploads" / uid).mkdir(parents=True)
        (tmp_path / "uploads" / uid / ("original.mp4" if kind == "video" else "image.png")).write_bytes(b"x")
        srv.UPLOADS[uid] = {"id": uid, "kind": kind, "_file": f"uploads/{uid}/original.{'mp4' if kind == 'video' else 'png'}"}
    yield


def _params(**kw):
    base = {"mode": "recast", "performers": 1, "subject": "person", "characters": [], "place": {"mode": "keep"}}
    base.update(kw)
    return base


CHAR = [{"upload_id": "img", "text": "a tall knight", "keep_outfit": False}]
ITEM = {"upload_id": "img", "text": "a red jacket"}


@pytest.mark.parametrize("params", [
    _params(characters=CHAR),
    _params(characters=CHAR, style="anime", place={"mode": "describe", "text": "a castle"}),
    _params(mode="restyle", style="anime"),
    _params(mode="swap", outfit=ITEM),
    _params(mode="swap", prop=ITEM),
    _params(mode="swap", place={"mode": "describe", "text": "a beach"}),
    _params(mode="swap", performers=2, subject="animal", place={"mode": "describe", "text": "a beach"}),
])
def test_each_mode_accepts_its_own_change(uploads, params):
    srv._check_mode(params, params["characters"], params["place"], params["performers"])


@pytest.mark.parametrize("params,why", [
    (_params(), "needs a character"),
    (_params(characters=CHAR, outfit=ITEM), "use Swap"),
    (_params(mode="restyle"), "Pick a look"),
    (_params(mode="restyle", style="anime", place={"mode": "describe", "text": "a castle"}), "only the look"),
    (_params(mode="swap", outfit=ITEM, prop=ITEM), "one thing at a time"),
    (_params(mode="swap"), "one thing at a time"),
    (_params(mode="swap", style="anime", outfit=ITEM), "changes one thing"),
    (_params(mode="swap", subject="animal", prop=ITEM), "one person"),
    (_params(mode="swap", outfit={"upload_id": "img", "text": ""}), "a few words"),
    (_params(mode="other"), "Recast, Restyle or Swap"),
])
def test_mixtures_are_refused_with_a_reason(uploads, params, why):
    with pytest.raises(srv.UserError, match=why):
        srv._check_mode(params, params["characters"], params["place"], params["performers"])
