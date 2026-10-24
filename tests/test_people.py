"""Choosing who is recast: masks from the start frame, numbered left to right, a tap finds the one in front."""
import numpy as np
from PIL import Image

from recast import people


def _mask(path, w, h, x0, x1, y0=0, y1=None):
    m = np.zeros((h, w), np.uint8)
    m[y0:y1 or h, x0:x1] = 255
    Image.fromarray(m).save(path)
    return path


def test_people_are_numbered_left_to_right_without_specks_or_doubles(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    files = [_mask(raw / "a.png", 100, 100, 60, 90),  # right
             _mask(raw / "b.png", 100, 100, 5, 40),  # left
             _mask(raw / "c.png", 100, 100, 6, 40),  # the left one again, found by the other word
             _mask(raw / "d.png", 100, 100, 45, 47, 0, 10)]  # a far-off head: too small to recast
    found = people.read(files, tmp_path / "people")
    assert [p.id for p in found] == [1, 2] and found[0].cx < found[1].cx
    assert found[0].box == (0.05, 0.0, 0.35, 1.0)
    assert [p.id for p in people.load(tmp_path / "people")] == [1, 2]


def test_a_tap_picks_the_person_in_front(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    big = _mask(raw / "big.png", 100, 100, 0, 80)  # someone behind, covering most of the frame
    small = _mask(raw / "small.png", 100, 100, 30, 50, 40, 80)  # someone standing in front of them
    found = people.read([big, small], tmp_path / "p")
    front = min(found, key=lambda p: p.area)
    assert people.at(found, tmp_path / "p", 0.4, 0.6) == front.id
    assert people.at(found, tmp_path / "p", 0.95, 0.5) is None


def test_picks_are_written_left_to_right_at_the_render_size(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    found = people.read([_mask(raw / "a.png", 200, 100, 10, 60), _mask(raw / "b.png", 200, 100, 120, 190)],
                        tmp_path / "p")
    out = people.write_picks(found, [2, 1], tmp_path / "p", tmp_path, (48, 24))
    assert [o.name for o in out] == ["pick_0.png", "pick_1.png"]
    first = np.asarray(Image.open(out[0]))
    assert first.shape == (24, 48) and first[:, :12].any() and not first[:, 30:].any()  # pick_0 is the left one
    x, y, w, h = people.crop_box(found, [2])
    assert 0.6 - people.CROP_PAD - 0.01 < x < 0.6 and x + w <= 1  # the chosen one with room around them


def test_the_character_is_cut_out_of_their_photo_on_the_rooms_colour(tmp_path):
    from PIL import Image

    from recast import people

    photo = Image.new("RGB", (100, 100), (0, 0, 255))  # a blue backdrop with a helmet on it
    photo.paste((255, 0, 0), (20, 10, 60, 90))  # the racer
    photo.paste((255, 255, 0), (70, 60, 95, 90))  # the helmet on the desk
    photo.save(tmp_path / "photo.png")
    m = Image.new("L", (100, 100), 0)
    m.paste(255, (20, 10, 60, 90))
    m.save(tmp_path / "person_1.png")
    small = Image.new("L", (100, 100), 0)
    small.paste(255, (70, 60, 95, 90))
    small.save(tmp_path / "person_2.png")
    found = [people.Person(1, (0.2, 0.1, 0.4, 0.8), 0.32, 0.4, "person_1.png"),
             people.Person(2, (0.7, 0.6, 0.25, 0.3), 0.075, 0.82, "person_2.png")]
    out = Image.open(people.cut_out(tmp_path / "photo.png", found, tmp_path, tmp_path / "cut.png", 0xEEEEEE))
    assert out.size == (48, 88)  # round the racer only, with a little room
    assert out.getpixel((24, 44)) == (255, 0, 0)
    assert out.getpixel((1, 1)) == (0xEE, 0xEE, 0xEE)  # the backdrop is the room's colour
    assert (255, 255, 0) not in {px for _, px in out.getcolors(10000)}  # no helmet
    assert people.cut_out(tmp_path / "photo.png", [], tmp_path, tmp_path / "none.png", 0) is None
