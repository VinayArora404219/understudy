from recast import graph, prompts


def test_composed_prompts_fit_the_graph_limits():
    a = prompts.appearance(subject="person", character_text="a tall knight in silver armour",
                           style="pixel", scene="new", background="a castle courtyard at dusk")
    assert a.startswith("Character appearance description: a tall knight")
    assert "\nBackground description: a castle courtyard at dusk, drawn as 16-bit" in a
    p = graph.RecastParams(reference="r.png", drive="d.mp4", appearance=a, motion=prompts.motion(subject="person"))
    p.validate()


def test_restyle_without_character_names_the_reference():
    a = prompts.appearance(subject="cat", style="anime")
    from recast import styles
    assert f"the cat shown in the reference image, drawn as {styles.get('anime').look}" in a
    assert "same place, light and camera" in a


def test_style_words_never_invite_a_maker_into_frame():
    """Prompt hygiene: words naming a maker or tool describe something that could appear in frame.
    (Not proven causal: the clay look invented a prop with and without them, see bench/RESULTS.md.)
    'hand-drawn' is exempt: the anime run used it and rendered clean (t5_restyle_anime)."""
    import re
    from recast import styles
    for st in styles.STYLES.values():
        for text in (st.edit, st.look):
            assert not re.search(r"(?i)\bhand(made|s)?\b(?!-drawn)|thumbprint|\btool|\bmaker|crafted by", text), st.key


def test_duo_prompts_name_both_sides():
    a = prompts.appearance(subject="animal", character_text="a man in a hard hat.", character2_text="a woman in black", two=True)
    assert a.startswith("Character appearance description: on the left, a man in a hard hat; on the right, a woman in black.")
    assert "two performers" in prompts.motion(subject="animal", two=True)
    assert prompts.appearance(subject="cat", two=True).startswith("Character appearance description: the two cats shown")
