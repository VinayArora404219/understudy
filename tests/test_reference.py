import re

import pytest

from recast import reference as ref


def _p(**kw):
    base = dict(frame="f.png", character="c.png", character_text="a slim robot with a round blue head")
    base.update(kw)
    return ref.MatchParams(**base)


def test_frame_is_the_latent_and_character_is_image2():
    g = ref.build(_p())
    assert g["base"]["inputs"]["image"] == "f.png"
    assert g["latent"]["inputs"]["pixels"] == ["base_rs", 0]
    for k in ("pos", "neg"):
        assert g[k]["inputs"]["image1"] == ["base_rs", 0]
        assert g[k]["inputs"]["image2"] == ["character_rs", 0]


def test_fast_uses_lightning_high_does_not():
    fast, high = ref.build(_p(quality="fast")), ref.build(_p(quality="high"))
    assert fast["sample"]["inputs"]["model"] == ["lora", 0]
    assert (fast["sample"]["inputs"]["steps"], fast["sample"]["inputs"]["cfg"]) == (4, 1.0)
    assert "lora" not in high
    assert (high["sample"]["inputs"]["steps"], high["sample"]["inputs"]["cfg"]) == (20, 3.0)
    assert high["neg"]["inputs"]["prompt"] == ref.NEGATIVE


def test_keep_scene_says_nothing_about_background():
    assert "background" not in ref.prompt_for(_p(scene="keep")).lower()
    assert "neon rooftop" in ref.prompt_for(_p(scene="new", background="a neon rooftop at night"))


def test_prompt_has_no_body_relative_directions():
    """Measured: 'her right' mirrors the subject. The template must never say it."""
    text = ref.prompt_for(_p(scene="new", background="a beach"))
    assert not re.search(r"\b(her|his|their)\s+(left|right)\b", text, re.I)


@pytest.mark.parametrize("bad", [dict(subject="robot"), dict(scene="other"), dict(quality="max"),
                                 dict(character_text=" "), dict(scene="new"), dict(character_text="x" * 401),
                                 dict(seed=-1)])
def test_bad_params_are_refused(bad):
    with pytest.raises(ref.ReferenceError):
        ref.build(_p(**bad))


def test_every_link_points_at_an_existing_node():
    for q in ("fast", "high"):
        g = ref.build(_p(quality=q))
        for node in g.values():
            for v in node["inputs"].values():
                if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
                    assert v[0] in g


def test_style_only_is_a_restyle_with_one_image():
    g = ref.build(ref.MatchParams(frame="f.png", style="anime"))
    assert "image2" not in g["pos"]["inputs"]
    text = ref.prompt_for(ref.MatchParams(frame="f.png", style="anime"))
    from recast import styles
    assert text.startswith(f"Redraw the whole picture as {styles.get('anime').edit}")


def test_character_and_location_take_slots_two_and_three():
    p = _p(location="l.png", style="comic")
    assert ref.slots(p) == {"character": 2, "location": 3}
    g = ref.build(p)
    assert g["pos"]["inputs"]["image2"] == ["character_rs", 0]
    assert g["pos"]["inputs"]["image3"] == ["location_rs", 0]
    assert g["neg"]["inputs"]["image3"] == ["location_rs", 0]
    text = ref.prompt_for(p)
    assert "second picture" in text and "third picture" in text and "comic-book" in text


def test_location_alone_takes_slot_two():
    p = ref.MatchParams(frame="f.png", location="l.png")
    assert ref.slots(p) == {"location": 2}
    assert "place shown in the second picture" in ref.prompt_for(p)


@pytest.mark.parametrize("bad", [
    dict(),  # nothing changes
    dict(style="sepia"),
    dict(character_text="a robot"),  # text without an image
])
def test_unanswerable_requests_are_refused(bad):
    with pytest.raises(ref.ReferenceError):
        ref.build(ref.MatchParams(frame="f.png", **bad))


def test_every_style_prompt_avoids_body_relative_directions():
    from recast import styles
    for key in styles.STYLES:
        text = ref.prompt_for(ref.MatchParams(frame="f.png", style=key))
        assert not re.search(r"\b(her|his|their)\s+(left|right)\b", text, re.I)


def test_render_failure_reads_as_one_line():
    from recast.runner import RenderFailed

    class Err:
        code = "node_execution_error"
        message = "VHS failed to extract audio from x.mp4:\nffmpeg version 8 ...\n..."
    e = RenderFailed("job-1", Err())
    assert str(e) == "job job-1 failed (node_execution_error): VHS failed to extract audio from x.mp4:"


def test_framing_follows_the_clip_not_a_fixed_rule():
    """A waist-up clip got a full-body reference when the prompt demanded 'whole body' (h3b)."""
    text = ref.prompt_for(_p())
    assert "whole body" not in text
    assert "framing as the first picture" in text


def _duo(**kw):
    base = dict(frame="f.png", character="a.png", character_text="a bearded man in a yellow hard hat",
                character2="b.png", character2_text="a young woman with long blonde hair", subject="animal")
    base.update(kw)
    return ref.MatchParams(**base)


def test_duo_puts_each_character_in_its_own_slot():
    p = _duo()
    assert ref.slots(p) == {"character": 2, "character2": 3}
    g = ref.build(p)
    for k in ("pos", "neg"):
        assert g[k]["inputs"]["image2"] == ["character_rs", 0]
        assert g[k]["inputs"]["image3"] == ["character2_rs", 0]


def test_duo_names_performers_by_side_of_the_picture():
    text = ref.prompt_for(_duo(pose="leans over the keyboard", pose2="stands upright"))
    assert "animal on the left of the first picture with the character from the second picture: a bearded man" in text
    assert "animal on the right of the first picture with the character from the third picture: a young woman" in text
    assert "The character on the left leans over the keyboard." in text
    assert "The character on the right stands upright." in text
    assert not re.search(r"\b(her|his|their|its)\s+(left|right)\b", text, re.I)


@pytest.mark.parametrize("bad", [
    dict(character2_text=" "),  # second image, no description
    dict(location="l.png"),  # frame + two characters + place = four images; the edit node takes three
    dict(character=None, character_text=""),  # a second character without a first
])
def test_duo_refuses_what_it_cannot_do(bad):
    with pytest.raises(ref.ReferenceError):
        ref.build(_duo(**bad))


def test_pose_words_join_the_single_character_prompt():
    assert "The character stands upright on its hind legs." in ref.prompt_for(_p(pose="stands upright on its hind legs."))
    assert "The character " not in ref.prompt_for(_p()).replace("The character takes", "")


def test_in_the_characters_place_their_photo_is_the_latent_and_the_clip_is_not_an_input():
    p = _p(frame=None, base="character", side="center", shot="whole body",
           pose="stands upright, both hands raised above the head")
    g = ref.build(p)
    assert g["base"]["inputs"]["image"] == "c.png"
    assert ref.slots(p) == {}
    assert "f.png" not in str(g) and "image2" not in g["pos"]["inputs"]
    text = ref.prompt_for(p)
    assert text.startswith("One single photograph of one continuous scene in the place of the first picture. "
                           "In the middle of the frame, the person from the first picture: a slim robot")
    assert "This person stands upright, both hands raised above the head, the whole body in view" in text
    assert "place of the first picture" in text
    assert "same camera" not in text.lower()  # the photo's camera is not the clip's


def test_a_duo_in_the_left_characters_place():
    p = _p(frame=None, base="character", character2="d.png", character2_text="a tall man in a green coat",
           pose="dances", pose2="films with a phone", shot="whole body", shot2="waist up")
    assert ref.slots(p) == {"character2": 2}
    text = ref.prompt_for(p)
    assert "On the left of the frame, the person from the first picture" in text
    assert "On the right of the frame, the person from the second picture: a tall man in a green coat" in text
    assert "This person films with a phone, seen from the waist up." in text
    assert "Exactly two people, one on the left" in text and "Use the second picture only for faces" in text
    g = ref.build(p)
    assert "character2_matte" in g and "character_matte" not in g  # only content images are cut out


def test_props_come_along_only_to_another_place():
    p = _p(frame=None, base="character", props="a small keyboard and an open laptop on the table")
    assert "In front of them, as in the video: a small keyboard and an open laptop on the table." in ref.prompt_for(p)
    with pytest.raises(ref.ReferenceError):
        ref.build(_p(props="a laptop"))


def test_in_a_place_image_both_characters_are_content():
    p = _p(frame=None, base="location", location="l.png", character2="d.png", character2_text="a tall man")
    assert ref.slots(p) == {"character": 2, "character2": 3}
    assert ref.build(p)["base"]["inputs"]["image"] == "l.png"
    assert "The scene is the place shown in the first picture" in ref.prompt_for(p)


@pytest.mark.parametrize("bad", [
    dict(base="sky"),
    dict(base="character", character=None, character_text=""),
    dict(base="location"),  # no location image
    dict(base="character", location="l.png"),  # two places
    dict(base="character", scene="new", background="a beach"),
    dict(base="character", shot="full shot"),
    dict(frame=None),  # base frame needs the frame
])
def test_bad_bases_are_refused(bad):
    with pytest.raises(ref.ReferenceError):
        ref.build(_p(**bad))


def test_shot_words_cover_what_the_describer_may_say():
    from recast import describe
    assert set(ref.SHOT_WORDS) == set(describe.SHOTS)


def test_outfit_swap_keeps_the_performer():
    p = ref.MatchParams(frame="f.png", outfit="o.png", outfit_text="a red leather biker jacket",
                        pose="stands upright, one hand on top of the head")
    assert ref.slots(p) == {"outfit": 2}
    text = ref.prompt_for(p)
    assert "now wears the red leather biker jacket shown in the second picture" in text
    assert "The person stands upright, one hand on top of the head." in text
    assert "Replace" not in text


def test_product_goes_in_the_hand_that_stays_in_view():
    """Measured (V5b): a product placed in the hand the performer keeps low stays in shot."""
    p = ref.MatchParams(frame="f.png", product="b.png", product_text="a green glass soda bottle", product_hand="right",
                        other_hand="is raised, hand resting on top of the head")
    text = ref.prompt_for(p)
    assert "arm on the left side of the picture is raised, hand resting on top of the head, exactly as" in text
    assert ("arm on the right side of the picture hangs down by the hip as in the first picture, and that hand now "
            "holds the green glass soda bottle shown in the second picture") in text
    assert not re.search(r"\b(her|his|their|its)\s+(left|right)\b", text, re.I)
    assert "in one hand" in ref.prompt_for(ref.MatchParams(frame="f.png", product="b.png", product_text="a bottle"))


@pytest.mark.parametrize("bad", [
    dict(outfit="o.png", outfit_text="a jacket", character="c.png", character_text="a robot"),  # swap keeps the performer
    dict(outfit="o.png", outfit_text="a jacket", product="b.png", product_text="a bottle"),  # one thing at a time
    dict(product="b.png", product_text=" "),
    dict(product="b.png", product_text="a bottle", product_hand="his right"),
])
def test_swaps_refuse_what_they_cannot_do(bad):
    with pytest.raises(ref.ReferenceError):
        ref.build(ref.MatchParams(frame="f.png", **bad))


def test_a_changed_prompt_changes_the_job_key():
    """Submissions are keyed by graph content: same seed, different words must not reattach (found in use)."""
    from recast import recipe
    a = recipe.graph_sha(ref.build(_p(pose="leans back")))
    b = recipe.graph_sha(ref.build(_p(pose="leans forward")))
    assert a != b and a == recipe.graph_sha(ref.build(_p(pose="leans back")))


def test_every_image_but_the_place_is_cut_out_onto_grey():
    """Measured: a busy character photo's set (wall, microphones) leaked into the clip's room, with or
    without a head crop and with a "keep the room" sentence. Only the place source may bring a background."""
    g = ref.build(_duo())
    for name in ("character", "character2"):
        assert g[f"{name}_rs"]["inputs"]["image"] == [f"{name}_cut", 0]
        assert g[f"{name}_cut"]["inputs"]["mask"] == [f"{name}_matte", 0]
        assert g[f"{name}_grey"]["inputs"]["color"] == ref.CUTOUT_GREY
    assert g["bg_model"]["inputs"]["bg_removal_name"] == ref.BG_REMOVAL
    p = _p(location="l.png")
    g = ref.build(p)
    assert g["location_rs"]["inputs"]["image"] == ["location", 0]  # a place is used whole
    assert "character_cut" in g
    assert "bg_model" not in ref.build(_p(cutout=False))


def test_another_place_is_worded_by_what_the_characters_are():
    assert ref.cast_word(["A middle-aged man with short dark hair", "a woman in red"]) == "person"
    assert ref.cast_word(["an orange tabby kitten"]) == "cat"
    assert ref.cast_word(["a green robot"]) == "character"


def test_an_outfit_in_words_dresses_the_first_picture():
    from recast import reference as r
    p = r.MatchParams(frame="photo.png", outfit_text="matching silver sequin jackets", seed=1)
    p.validate()
    text = r.prompt_for(p)
    assert "now wears matching silver sequin jackets" in text and "Same pose, same camera" in text


def test_two_people_each_get_their_own_outfit_by_side():
    p = ref.MatchParams(frame="f.png", outfit="jacket.png", outfit_text="a red leather jacket", outfit_side="left",
                              outfit2_text="a blue suit")
    text = ref.prompt_for(p)
    assert "The person on the left of the first picture now wears the red leather jacket shown in the second" in text
    assert "The person on the right of the first picture now wears a blue suit, fitted" in text
    with pytest.raises(ref.ReferenceError):  # a second outfit always belongs to the right one
        ref.MatchParams(frame="f.png", outfit_text="a hat", outfit2_text="a suit").validate()
