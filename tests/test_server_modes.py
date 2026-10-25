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
    _params(characters=CHAR, outfit=ITEM),  # Recast + outfit: the characters dressed in it
    _params(characters=CHAR, outfit={"text": "matching silver sequin jackets"}),  # words alone are enough
    _params(mode="swap", outfit=ITEM),
    _params(mode="swap", place={"mode": "describe", "text": "a beach"}),
    _params(mode="swap", performers=2, subject="animal", place={"mode": "describe", "text": "a beach"}),
    _params(mode="swap", outfit={"text": "a red jacket"}),  # words alone dress them too
    _params(mode="swap", outfit=ITEM, place={"mode": "describe", "text": "a beach"}),  # both at once
    _params(mode="swap", performers=2, outfits=[ITEM, None]),  # an outfit for each, or none
    _params(mode="swap", subject="animal", outfit=ITEM),  # a dog in a raincoat
])
def test_each_mode_accepts_its_own_change(uploads, params):
    srv._check_mode(params, params["characters"], params["place"], params["performers"])


@pytest.mark.parametrize("params,why", [
    (_params(), "needs a character"),
    (_params(characters=CHAR, prop=ITEM), "Products in hand"),
    (_params(characters=CHAR, outfit={"text": "x"}), "a few words"),
    (_params(mode="restyle"), "Pick a look"),
    (_params(mode="restyle", style="anime", place={"mode": "describe", "text": "a castle"}), "only the look"),
    (_params(mode="swap", prop=ITEM), "Products in hand aren't offered"),
    (_params(mode="swap"), "new clothes, or pick a new place"),
    (_params(mode="swap", outfits=[None, None]), "new clothes, or pick a new place"),
    (_params(mode="swap", style="anime", outfit=ITEM), "their clothes or the place"),
    (_params(mode="swap", outfits="a red jacket"), "for each person"),
    (_params(mode="swap", outfit={"upload_id": "img", "text": ""}), "a few words"),
    (_params(mode="other"), "Recast, Restyle or Restage"),
])
def test_mixtures_are_refused_with_a_reason(uploads, params, why):
    with pytest.raises(srv.UserError, match=why):
        srv._check_mode(params, params["characters"], params["place"], params["performers"])


def test_the_summary_reads_as_one_sentence():
    p = _params(characters=[{"upload_id": "img", "text": "A young woman with long blonde hair"}],
                place={"mode": "describe", "text": "a snowy mountain road"})
    assert srv._summary(p) == ("The performer becomes a young woman with long blonde hair, "
                               "in the place you described: a snowy mountain road.")


def test_restage_dresses_each_chosen_person_and_fits_one_edit(uploads):
    two = [ITEM, {"upload_id": "img", "text": "a blue suit"}]
    srv._check_restage(_params(mode="swap", outfits=two), 2)  # in the clip's place: one edit each
    srv._check_restage(_params(mode="swap", outfits=two, place={"mode": "describe", "text": "a beach"}), 2)
    with pytest.raises(srv.UserError, match="don't fit together"):  # frame + 2 outfits + a place picture
        srv._check_restage(_params(mode="swap", outfits=two, place={"mode": "image", "upload_id": "img"}), 2)
    with pytest.raises(srv.UserError, match="for each person"):
        srv._check_restage(_params(mode="swap", outfits=[ITEM]), 2)
    p = _params(mode="swap", outfits=[None, ITEM], place={"mode": "describe", "text": "a beach"},
                motion={"length": 5})
    assert srv._title(p) == "New outfit, new place · 5 s"
    assert srv._summary(p) == "The performer on the right now wears a red jacket; in the place you described: a beach."
    assert srv._title(_params(mode="swap", outfits=[ITEM, ITEM], motion={"length": 5})) == "New outfits · 5 s"


def test_up_to_four_in_the_clips_place_and_two_elsewhere(uploads):
    four = [{"upload_id": "img", "text": t} for t in ("a chef", "an astronaut", "a runner", "a grandpa")]
    assert srv._title(_params(characters=four, motion={"length": 5})) == "Recast of 4 · 5 s"
    assert srv._summary(_params(characters=four)).startswith("From the left, the performers become a chef; an astronaut")
