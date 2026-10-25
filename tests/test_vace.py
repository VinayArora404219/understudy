import pytest

from recast import graph, vace


def _p(**kw):
    base = dict(drive="d.mp4", reference="r.png", prompt="a man on a street, drawn as anime", layout="portrait")
    base.update(kw)
    return vace.VaceParams(**base)


def test_one_chunk_follows_depth_with_the_restyled_frame_as_reference():
    g = vace.build(_p())
    v = g["c0_vace"]["inputs"]
    assert (v["width"], v["height"], v["length"]) == (480, 832, 81)
    assert v["control_video"] == ["c0_control", 0] and v["reference_image"] == ["ref", 0]
    assert "control_masks" not in v  # all frames generated from depth
    assert g["depth_raw"]["inputs"]["ckpt_name"] == "depth_anything_v2_vits.pth"  # Small: Apache-2.0
    assert g["fast"]["inputs"]["strength_model"] == 1.0 and g["c0_ks"]["inputs"]["steps"] == vace.STEPS
    assert "style" not in g["neg"]["inputs"]["text"]


def test_later_chunks_start_from_the_previous_chunks_last_frames():
    g = vace.build(_p(chunks=3))
    assert g["clip_frames"]["inputs"]["length"] == vace.frames_for(3) == 81 + 2 * 72
    assert g["c1_anchor"]["inputs"] == {"image": ["c0_dec", 0], "batch_index": -vace.OVERLAP, "length": vace.OVERLAP}
    assert g["c2_anchor"]["inputs"]["image"] == ["c1_out", 0]
    # the depth after the anchor: chunk i covers clip frames STRIDE*i .. STRIDE*i + CHUNK
    assert g["c1_depth"]["inputs"]["batch_index"] == vace.STRIDE + vace.OVERLAP
    assert g["c2_depth"]["inputs"]["batch_index"] == 2 * vace.STRIDE + vace.OVERLAP
    assert g["c1_depth"]["inputs"]["length"] + vace.OVERLAP == vace.CHUNK
    assert g["c1_vace"]["inputs"]["control_masks"] == ["mask", 0]
    assert (g["keep"]["inputs"]["batch_size"], g["keep"]["inputs"]["color"]) == (vace.OVERLAP, 0)  # kept
    assert g["make"]["inputs"]["color"] == 0xFFFFFF  # generated
    assert g["c1_new"]["inputs"]["batch_index"] == vace.OVERLAP
    assert g["out"]["inputs"]["images"] == ["c2_join", 0]
    assert [g[f"c{i}_ks"]["inputs"]["seed"] for i in range(3)] == [1, 2, 3]


def test_overlap_fills_whole_latent_frames():
    assert (vace.OVERLAP - 1) % 4 == 0


@pytest.mark.parametrize("bad", [dict(chunks=0), dict(chunks=5), dict(prompt=""), dict(layout="cinema"),
                                 dict(seed=graph.MAX_SEED)])
def test_bad_params_are_refused(bad):
    with pytest.raises(vace.VaceError):
        vace.build(_p(**bad))


def test_the_apps_default_seed_is_accepted():
    vace.build(_p(seed=graph.DEFAULT_SEED, chunks=vace.MAX_CHUNKS))


def test_prompt_is_the_scene_then_the_look():
    text = vace.prompt("A young man in a white t-shirt on a city street.", "anime")
    assert text.startswith("A young man in a white t-shirt on a city street, everything drawn as hand-drawn anime")


def test_a_short_last_chunk_gets_its_own_mask():
    g = vace.build(vace.VaceParams(drive="d.mp4", reference="r.png", prompt="x", layout="portrait", chunks=2,
                                   frames=120))
    assert vace.lengths_for(120) == [81, 45]
    assert g["c1_vace"]["inputs"]["length"] == 45 and g["c1_depth"]["inputs"]["length"] == 45 - vace.OVERLAP
    assert g["make_45"]["inputs"]["batch_size"] == 45 - vace.OVERLAP and "make" not in g
    assert g["c1_vace"]["inputs"]["control_masks"] == ["mask_45", 0]
