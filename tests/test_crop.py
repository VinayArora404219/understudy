import subprocess

import pytest

from recast import crop, media


def test_box_is_a_square_around_the_face_with_headroom():
    # a 120 px face high in a 1122x1402 full-body picture
    w, h, x, y = crop.box_around((480, 200, 120, 120), 1122, 1402)
    assert w == h == 480
    assert x == 480 + 60 - 240 and y == 200 - round(0.9 * 120)


def test_box_slides_inside_the_picture_instead_of_shrinking():
    w, h, x, y = crop.box_around((5, 5, 100, 100), 1000, 1000)  # face in the top-left corner
    assert (w, x, y) == (400, 0, 0)
    w, h, x, y = crop.box_around((900, 900, 100, 100), 1000, 1000)
    assert x + w <= 1000 and y + h <= 1000


def test_box_never_exceeds_the_picture():
    w, h, x, y = crop.box_around((100, 100, 300, 300), 800, 600)  # a close-up: 4 face heights won't fit
    assert w == h == 600 and 0 <= x <= 200 and y == 0


def test_no_face_means_no_crop(tmp_path):
    pytest.importorskip("mediapipe")
    img = tmp_path / "flat.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=0x8899aa:s=640x640",
                    "-frames:v", "1", str(img)], check=True, timeout=60)
    assert crop.find_face(img) is None
    assert crop.head_and_shoulders(img, tmp_path / "out.png") is None


def test_crop_image_writes_the_box(tmp_path):
    img = tmp_path / "src.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=800x600",
                    "-frames:v", "1", str(img)], check=True, timeout=60)
    out = media.probe(media.crop_image(img, tmp_path / "c.png", (300, 300, 100, 50)))
    assert (out.width, out.height) == (300, 300)


def test_shape_box_is_the_largest_crop_centred_on_the_face():
    # a landscape photo, a portrait clip (468x832): full height, as wide as the shape allows, around the face
    w, h, x, y = crop.shape_box(1600, 900, 468 / 832, (1100, 200, 100, 100))
    assert h == 900 and abs(w / h - 468 / 832) < 0.01
    assert x <= 1150 <= x + w and x + w <= 1600
    w, h, x, y = crop.shape_box(1600, 900, 468 / 832, None)  # no face: the middle
    assert x == (1600 - w) // 2


def test_shape_box_keeps_the_face_in_the_upper_part_of_a_tall_photo():
    w, h, x, y = crop.shape_box(900, 2000, 832 / 468, (400, 300, 100, 100))
    assert w == 900 and y <= 350 <= y + h / 2
