"""Bystanders put back as filmed: their colour fitted to the render on background only."""
import numpy as np

from recast import composite


def test_the_colour_fit_takes_the_renders_grey_to_the_clips_white():
    rng = np.random.default_rng(0)
    clip = rng.uniform(200, 250, (40, 40, 3)).astype(np.float32)
    render = (clip - 60) / 1.1  # darker and flatter: a white studio rendered grey
    bg = np.ones((40, 40), bool)
    gain, off = composite.fit(render, clip, bg)
    assert np.allclose(render * gain + off, clip, atol=1.0)


def test_no_background_means_no_change():
    a = np.full((10, 10, 3), 100, np.float32)
    gain, off = composite.fit(a, a + 50, np.zeros((10, 10), bool))
    assert (gain == 1).all() and (off == 0).all()


def test_only_bystanders_go_back_and_a_new_character_in_front_wins(tmp_path):
    import subprocess

    from recast import media

    def video(path, frame):  # 4 identical frames
        subprocess.run([media.FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "64x64",
                        "-r", "16", "-i", "-", "-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv444p", str(path)],
                       input=np.repeat(frame[None], 4, 0).astype(np.uint8).tobytes(), check=True)
        return path

    clip = np.full((64, 64, 3), 230.0)
    clip[10:30, 40:60] = 40  # a bystander, dark, on a white wall
    render = np.full((64, 64, 3), 180.0)  # the wall rendered grey
    render[10:30, 4:24] = 120  # the new character
    others = np.zeros((64, 64, 3))
    others[10:30, 40:60] = 255
    new = np.zeros((64, 64, 3))
    new[10:30, 4:24] = 255
    new[20:30, 40:44] = 255  # ... with a hand in front of the bystander
    out = composite.keep_others(video(tmp_path / "c.mp4", clip), video(tmp_path / "r.mp4", render),
                                video(tmp_path / "o.mp4", others), video(tmp_path / "n.mp4", new),
                                video(tmp_path / "p.mp4", new), tmp_path / "out.mp4")
    f = next(composite._frames(out, 64, 64))
    assert abs(f[5, 30, 0] - 180) < 6  # the wall stays as rendered
    assert abs(f[15, 10, 0] - 120) < 6  # the new character as rendered
    assert f[15, 50, 0] < 100  # the bystander is back (graded toward the render, still dark)
    assert abs(f[25, 41, 0] - 180) < 12  # the hand in front of him stays rendered


def test_the_grade_is_fitted_on_the_room_not_the_new_character():
    """The render's room is darker than the clip's; where the character stands the two differ anyway."""
    rng = np.random.default_rng(0)
    clip = rng.uniform(150, 230, (4, 40, 30, 3)).astype(np.float32)
    render = clip * np.array([0.88, 0.87, 0.85], np.float32)
    render[:, 10:30, 10:20] = 30.0  # a dark new character where a light performer stood
    gain = composite.grade_fit(render, clip)
    assert np.allclose(gain, 1 / np.array([0.88, 0.87, 0.85]), atol=0.01)
