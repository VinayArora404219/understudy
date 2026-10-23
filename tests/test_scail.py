import subprocess

import pytest

from recast import scail


def _p(**kw):
    base = dict(drive="d.mp4", reference="r.png", prompt="On the left, a man.", track="dog, cat", people=2,
                replace=True, layout="square")
    base.update(kw)
    return scail.ScailParams(**base)


def test_one_chunk_is_the_blueprint_graph():
    g = scail.build(_p())
    s = g["c0_scail"]["inputs"]
    assert (s["width"], s["height"], s["length"], s["replacement_mode"]) == (640, 640, 81, True)
    assert s["pose_video"] == ["c0_frames", 0] and s["reference_image_mask"] == ["c0_masks", 1]
    assert "previous_frames" not in s
    assert g["c0_masks"]["inputs"]["sort_by"] == "left_to_right"
    assert g["sigmas"]["inputs"]["model"] == ["fast", 0]  # the schedule skips the shift, as in the blueprint
    assert g["out"]["inputs"]["images"] == ["c0_dec", 0]
    assert {n["class_type"] for n in g.values()} >= {"WanSCAILToVideo", "SCAIL2ColoredMask", "SAM3_VideoTrack"}


def test_later_chunks_anchor_on_the_previous_chunk_and_drop_the_overlap():
    g = scail.build(_p(chunks=3))
    assert g["c1_frames"]["inputs"]["batch_index"] == scail.STRIDE
    assert g["c2_frames"]["inputs"]["batch_index"] == 2 * scail.STRIDE
    assert g["c1_scail"]["inputs"]["previous_frames"] == ["c0_dec", 0]
    assert g["c2_scail"]["inputs"]["previous_frames"] == ["c1_out", 0]
    # each chunk is already sliced: an offset as well would slice it again (the node does pose_video[offset:])
    assert all(g[f"c{i}_scail"]["inputs"]["video_frame_offset"] == 0 for i in range(3))
    assert g["c1_new"]["inputs"]["batch_index"] == scail.OVERLAP
    assert g["c2_join"]["inputs"] == {"image1": ["c1_join", 0], "image2": ["c2_out", 0]}
    assert g["out"]["inputs"]["images"] == ["c2_join", 0]
    assert [g[f"c{i}_sample"]["inputs"]["noise_seed"] for i in range(3)] == [1, 2, 3]
    assert scail.frames_for(3) == 81 + 2 * 76


def test_animate_mode_uses_the_reference_as_the_room():
    g = scail.build(_p(replace=False, people=1, track="person"))
    assert g["c0_scail"]["inputs"]["replacement_mode"] is False
    assert g["c0_masks"]["inputs"]["replacement_mode"] is False
    assert g["ref_track"]["inputs"]["max_objects"] == 1


def test_sizes_are_multiples_of_32():
    for layout in ("portrait", "landscape", "square", "portrait_3x4", "landscape_4x3"):
        w, h = scail.size(layout)
        assert w % 32 == 0 and h % 32 == 0


@pytest.mark.parametrize("bad", [dict(chunks=0), dict(chunks=5), dict(people=3), dict(prompt=" "),
                                 dict(track=""), dict(layout="cinema")])
def test_bad_params_are_refused(bad):
    with pytest.raises(scail.ScailError):
        scail.build(_p(**bad))


def test_track_words_name_each_kind_once():
    assert scail.track_words(["dog", "cat"], "animal") == "dog, cat"
    assert scail.track_words(["man", "Man"], "person") == "man"
    assert scail.track_words([], "person") == "person"
    assert scail.track_words(["", " "], "animal") == "animal"


def test_prompt_places_each_character_and_the_place():
    text = scail.prompt(["a man in a racing suit", "a man in a hard hat"], ["leans forward"], replace=True)
    assert text.startswith("On the left, a man in a racing suit, who leans forward. On the right, a man in a hard hat.")
    assert "same place as the video" in text
    assert "place shown in the picture" in scail.prompt(["a robot"], [], replace=False)


def test_reference_sheet_is_square_and_keeps_both(tmp_path):
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    for f, s in ((a, "300x600"), (b, "400x400")):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=red:s={s}", "-frames:v", "1",
                        str(f)], check=True, timeout=60)
    from recast import media
    info = media.probe(scail.reference_sheet([a, b], tmp_path / "sheet.png", height=200))
    assert info.width == info.height == 300  # 100 + 200 wide, padded to a square


def test_the_apps_default_seed_is_accepted():
    from recast import graph
    g = scail.build(_p(seed=graph.DEFAULT_SEED, chunks=scail.MAX_CHUNKS))
    assert g["c3_sample"]["inputs"]["noise_seed"] == graph.DEFAULT_SEED + 3
    with pytest.raises(scail.ScailError):
        scail.build(_p(seed=graph.MAX_SEED))
