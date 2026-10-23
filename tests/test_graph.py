import json
from pathlib import Path

import pytest

from recast import graph

FIX = Path(__file__).parent / "fixtures"


def _params(**kw):
    base = dict(reference="ref.png", drive="drive.mp4", appearance="a dancer", motion="dances")
    base.update(kw)
    return graph.RecastParams(**base)


def test_port_matches_a_graph_that_rendered():
    """A 3-segment graph from the pre-competition builder rendered successfully
    on a 16 GB card. The port must emit the same graph for the same config."""
    cfg = json.loads((FIX / "reference_3seg.cfg.json").read_text())
    want = json.loads((FIX / "reference_3seg.json").read_text())["prompt"]
    got = graph.build(_params(reference=cfg["ref"], drive=cfg["video"], appearance=cfg["prompt"],
                              motion=cfg["pose_prompt"], layout="portrait", segments=cfg["segments"],
                              prefix=cfg["prefix"]))
    assert got == want


def test_single_segment_has_no_join_and_no_checkpoints():
    g = graph.build(_params(segments=1))
    types = [n["class_type"] for n in g.values()]
    assert types.count("WanAnimate2ToVideo") == 1
    assert "BatchImagesNode" not in types
    assert types.count("SaveVideo") == 1
    assert g["cut"]["inputs"]["image"] == ["d0", 0]
    assert g["vid"]["inputs"]["frame_load_cap"] == 81


def test_every_link_points_at_an_existing_node():
    for segs in range(1, graph.MAX_SEGMENTS + 1):
        g = graph.build(_params(segments=segs))
        for node in g.values():
            for v in node["inputs"].values():
                if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
                    assert v[0] in g


def test_seeds_and_continuations_chain():
    g = graph.build(_params(segments=3, seed=100))
    assert [g[f"s{i}"]["inputs"]["noise_seed"] for i in range(3)] == [100, 101, 102]
    assert "continue_motion" not in g["a0"]["inputs"]
    assert g["a2"]["inputs"]["continue_motion"] == ["d1", 0]
    assert g["a2"]["inputs"]["video_frame_offset"] == ["a1", 5]


@pytest.mark.parametrize("frames,segs", [(1, 1), (81, 1), (82, 2), (161, 2), (162, 3), (241, 3)])
def test_segments_for(frames, segs):
    assert graph.segments_for(frames) == segs
    assert graph.frames_for(segs) >= frames


def test_landscape_size_reaches_every_size_input():
    g = graph.build(_params(layout="landscape", segments=2))
    for k in ("drive", "ref_rs"):
        assert g[k]["inputs"]["resize_type.width"] == 832
        assert g[k]["inputs"]["resize_type.height"] == 480
    for k in ("a0", "a1"):
        assert (g[k]["inputs"]["width"], g[k]["inputs"]["height"]) == (832, 480)
    assert g["vid"]["inputs"]["custom_height"] == 480


@pytest.mark.parametrize("bad", [
    dict(segments=0), dict(segments=graph.MAX_SEGMENTS + 1), dict(layout="cinema"), dict(fps=24),
    dict(seed=-1), dict(seed=2**60), dict(steps=50), dict(appearance=""), dict(motion="x" * 601),
    dict(prefix="../../etc/x"), dict(prefix="/abs"), dict(prefix="a;rm -rf"), dict(extra={"cfg": 7}),
])
def test_out_of_range_params_are_refused(bad):
    with pytest.raises(graph.ParamError):
        graph.build(_params(**bad))
