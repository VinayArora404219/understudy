import pytest

from recast import describe


def test_reply_is_parsed_and_ordered_left_to_right():
    text = ('Sure! ```json\n{"performers": [{"side": "right", "kind": "animal", "what": "cat", '
            '"pose": "sits upright, one hand raised near the laptop"}, {"side": "left", "kind": "animal", '
            '"what": "dog", "pose": "leans forward, both hands on the keyboard."}]}\n```')
    a, b = describe.parse(text)
    assert (a.side, a.what, a.pose) == ("left", "dog", "leans forward, both hands on the keyboard")
    assert (b.side, b.what) == ("right", "cat")


def test_shot_is_read_and_anything_else_is_dropped():
    one = describe.parse('{"performers": [{"side": "center", "kind": "person", "what": "man", '
                         '"shot": "Waist up", "pose": "stands"}]}')[0]
    assert one.shot == "waist up"
    odd = describe.parse('{"performers": [{"side": "center", "kind": "person", "what": "man", '
                         '"shot": "medium close-up", "pose": "stands"}]}')[0]
    assert odd.shot == ""


def test_body_is_the_pose_without_objects_and_is_cleaned_the_same_way():
    one = describe.parse('{"performers": [{"side": "left", "kind": "animal", "what": "dog", "pose": "both hands on '
                         'the keyboard", "body": "leans forward, head down, left paw low in front, both hands low"}]}')[0]
    assert one.body == "leans forward, head down, both hands low"


@pytest.mark.parametrize("pose,kept", [
    ("sits upright, head turned slightly left, one hand raised", "sits upright, one hand raised"),
    ("raises her right paw, leans forward", "leans forward"),
    ("stands, left arm up", "stands"),
    ("looks to the right", ""),
    ("stands upright, both hands at the chest", "stands upright, both hands at the chest"),
])
def test_clauses_that_give_a_body_a_side_are_dropped(pose, kept):
    """Measured: body-relative directions mirror the subject. Only the offending clause goes."""
    text = '{"performers": [{"side": "center", "kind": "person", "what": "woman", "pose": "%s"}]}' % pose
    assert describe.parse(text)[0].pose == kept


def test_mismatch_sentences():
    dog = describe.Performer("left", "animal", "dog", "")
    cat = describe.Performer("right", "animal", "cat", "")
    assert describe.mismatch([dog, cat], performers=2, subject="animal") is None
    assert "We see two performers in this clip (a dog and a cat)" in describe.mismatch([dog, cat], performers=1, subject="person")
    assert "but this needs two people" in describe.mismatch([dog, cat], performers=2, subject="person")
    assert describe.mismatch([], performers=1, subject="person") is None  # unsure: don't block
    assert "Up to two" in describe.mismatch([dog, cat, dog], performers=2, subject="animal")


def test_graph_uses_core_nodes_only_and_greedy_decoding():
    g = describe.build("f.png")
    assert {n["class_type"] for n in g.values()} == {"CLIPLoader", "LoadImage", "FluxKontextImageScale",
                                                       "TextGenerate", "SaveText"}
    assert g["gen"]["inputs"]["sampling_mode"] == "off"
    assert g["gen"]["inputs"]["image"] == ["frame_rs", 0]


def test_no_json_is_an_error_not_a_guess():
    with pytest.raises(ValueError):
        describe.parse("I see a dog and a cat.")



def test_image_descriptions_are_one_clean_line():
    assert describe.parse_role('Description: "a grey-bearded man in a yellow hard hat, red t-shirt."\n', "character") \
        == "a grey-bearded man in a yellow hard hat, red t-shirt"
    assert describe.parse_role("a man, his left hand gloved, blue cape", "character") == "a man, blue cape"
    assert len(describe.parse_role(" ".join(["word"] * 50), "product").split()) == 12


def test_role_prompts_ask_for_no_brands_and_no_sides():
    for role, prompt in describe.ROLE_PROMPTS.items():
        assert "no brand names" in prompt.lower(), role
    assert "no left or right" in describe.ROLE_PROMPTS["character"]


def test_find_names_the_performer_for_the_tracker():
    reply = ('{"performers": [{"side": "center", "kind": "person", "what": "man", "find": "Man in a grey suit.", '
             '"pose": "stands"}, {"side": "left", "kind": "person", "what": "woman", "find": "woman on the left"}]}')
    woman, man = describe.parse(reply)  # ordered by side: left first
    assert man.find == "man in a grey suit"
    assert woman.find == ""  # a side is the picture's, not the performer's
    assert describe.parse('{"performers": [{"what": "dog", "find": "dog"}]}')[0].find == ""  # too short to help
    assert describe.Performer("left", "animal", "dog", "").find == ""  # cached performers from before still load


def test_chosen_performers_get_a_reader_that_counts_them():
    one, two = describe.prompt_for(1), describe.prompt_for(2)
    assert "exactly one performer" in one and "exactly 2 performers" in two
    assert "background is not a performer" in one
    assert one.endswith(describe.PROMPT.split("\n", 1)[1])  # the same rules and JSON shape follow


def test_nothing_said_to_be_absent_reaches_a_prompt():
    text = ("A man, mid-40s, oval face, short black hair, no facial hair, no glasses, wears a red racing suit "
            "with no logos, without a hat")
    assert describe.drop_negations(text) == "A man, mid-40s, oval face, short black hair, wears a red racing suit"
    assert describe.parse_role("No glasses, a woman with long blonde hair", "character") == "a woman with long blonde hair"
    assert describe.drop_negations("a knotted scarf, nothing else") == "a knotted scarf, nothing else"  # "no" whole words only
