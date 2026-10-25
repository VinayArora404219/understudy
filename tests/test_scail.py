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


def test_chosen_performers_are_tracked_once_from_their_start_masks():
    g = scail.build(_p(chunks=2, picks=["pick0.png", "pick1.png"]))
    t = g["track"]["inputs"]
    assert t["initial_mask"] == ["start_masks", 0] and "conditioning" not in t  # who, not what: no words
    assert t["max_objects"] == 2 and g["clip_frames"]["inputs"]["length"] == scail.frames_for(2)
    assert g["picks1"]["inputs"] == {"image1": ["pick0", 0], "image2": ["pick1", 0]}
    # each chunk takes its slice of the one coloured track, so nobody can swap at a chunk join
    assert g["c1_masks"]["inputs"] == {"image": ["masks", 0], "batch_index": scail.STRIDE, "length": scail.CHUNK}
    assert g["c1_scail"]["inputs"]["pose_video_mask"] == ["c1_masks", 0]
    assert g["c1_scail"]["inputs"]["reference_image_mask"] == ["masks", 1]
    assert "drive_words" not in g and "c0_track" not in g


def test_picks_must_match_the_characters():
    with pytest.raises(scail.ScailError):
        scail.build(_p(picks=["pick0.png"]))  # two characters, one chosen performer
    scail.build(_p(people=1, track="", picks=["pick0.png"]))  # words aren't needed once someone is chosen


def test_keeping_the_clip_adds_the_two_masks():
    g = scail.build(_p(people=1, track="", picks=["pick0.png"], keep_points=[[[10, 20], [12, 40], [14, 60]]]))
    assert g["keep_find0"]["inputs"]["positive_coords"] == '[{"x": 10, "y": 20}, {"x": 12, "y": 40}, {"x": 14, "y": 60}]'
    assert g["keep_old"]["inputs"]["track_data"] == ["track", 0]  # the performers as tracked in the clip
    assert g["keep_new_track"]["inputs"]["images"] == ["c0_dec", 0]  # the new characters, found in the render
    assert {scail.KEEP_MASK_NODE, scail.KEEP_NEW_NODE} <= set(g)
    assert g["keep_everyone_track"]["inputs"]["images"] == ["clip_frames", 0]  # anyone who walks in later
    assert g["keep_rest"]["inputs"]["source"] == ["keep_old_grown", 0]  # never the chosen ones
    g = scail.build(_p(people=1, track="", picks=["pick0.png"], others=["other0.png"],
                       keep_points=[[[10, 20], [12, 40], [14, 60]]]))
    assert g["keep_others_track"]["inputs"]["images"] == ["clip_frames", 0]  # bystanders tracked in the clip
    assert scail.KEEP_OTHERS_NODE in g
    with pytest.raises(scail.ScailError):  # another place has no clip to keep
        scail.build(_p(people=1, track="", picks=["pick0.png"], replace=False, keep_points=[[[1, 1]]]))


def test_placed_sheet_puts_each_character_where_their_performer_stands(tmp_path):
    from PIL import Image
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    Image.new("RGB", (100, 200), (255, 0, 0)).save(a)
    Image.new("RGB", (100, 200), (0, 0, 255)).save(b)
    # the right performer is listed first: the sheet still goes left to right, like the page and the masks
    boxes = [(0.5, 0.1, 0.2, 0.8), (0.25, 0.2, 0.2, 0.8)]
    out = Image.open(scail.placed_sheet([a, b], boxes, (200, 100), tmp_path / "sheet.png", 0x808080, scale=1))
    assert out.size == (200, 100)  # the clip's shape
    assert out.getpixel((70, 60)) == (255, 0, 0)  # the first character on the left performer
    assert out.getpixel((120, 60)) == (0, 0, 255)  # the second on the right one
    assert out.getpixel((5, 5)) == (128, 128, 128)  # the room's colour around them



def test_any_length_renders_whole_chunks_then_a_short_last_one():
    from recast import graph
    assert scail.lengths_for(scail.frames_for(2)) == [81, 81]  # whole chunks: the graphs from before
    assert scail.lengths_for(32) == [29]  # 2 s: one short chunk, 1 + 4n frames
    assert scail.lengths_for(112) == [81, 33]  # 7 s: the second chunk only as long as needed
    assert scail.lengths_for(83) == [81]  # a last chunk that would add nothing past its overlap is left out
    for frames in range(32, scail.frames_for(scail.MAX_CHUNKS) + 1):
        lengths = scail.lengths_for(frames)
        assert all((n - 1) % 4 == 0 for n in lengths)
        assert 0 <= frames - graph.covered(lengths, chunk=scail.CHUNK, overlap=scail.OVERLAP) <= 7
    p = scail.ScailParams(drive="d.mp4", reference="r.png", prompt="a man", track="person", people=1, replace=True,
                          layout="portrait", chunks=2, frames=112, picks=["p0.png"])
    g = scail.build(p)
    assert g["c1_scail"]["inputs"]["length"] == 33 and g["c1_frames"]["inputs"]["length"] == 33
    assert g["c1_masks"]["inputs"]["length"] == 33 and g["clip_frames"]["inputs"]["length"] == 76 + 33
    with pytest.raises(scail.ScailError):
        scail.build(scail.ScailParams(**{**p.__dict__, "chunks": 3}))
