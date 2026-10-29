import subprocess

import pytest

from recast import media


def _clip(path, *, seconds=3.0, size="1080x1920", fps=30, audio=True):
    args = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={fps}:duration={seconds}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-shortest", str(path)]
    subprocess.run(args, check=True, timeout=120)
    return path


def test_probe_and_layout(tmp_path):
    info = media.validate_upload(_clip(tmp_path / "p.mp4"))
    assert (info.width, info.height, info.has_audio) == (1080, 1920, True)
    assert info.layout == "portrait_hd"
    assert media.probe(_clip(tmp_path / "l.mp4", size="1920x1080", audio=False)).layout == "landscape_hd"


def test_normalize_hits_render_shape(tmp_path):
    src = _clip(tmp_path / "in.mp4", seconds=4.0)
    out = media.normalize(src, tmp_path / "n.mp4", layout="portrait", seconds=2.0)
    assert (out.width, out.height) == (480, 832)
    assert out.fps == pytest.approx(16, abs=0.01)
    assert out.seconds == pytest.approx(2.0, abs=0.1)
    assert out.has_audio


def test_too_long_clip_is_refused(tmp_path):
    with pytest.raises(media.MediaError, match="long"):
        media.validate_upload(_clip(tmp_path / "long.mp4", seconds=31, size="320x568", audio=False))


def test_not_a_video_is_refused(tmp_path):
    p = tmp_path / "x.mp4"
    p.write_bytes(b"#!/bin/sh\necho hi\n" * 50)
    with pytest.raises(media.MediaError):
        media.validate_upload(p)


def test_shell_like_filename_is_inert(tmp_path):
    p = _clip(tmp_path / "a; touch PWNED.mp4", seconds=1.5, size="320x568")
    media.validate_upload(p)
    assert not (tmp_path / "PWNED.mp4").exists()


def test_compare_and_audio(tmp_path):
    a = media.normalize(_clip(tmp_path / "a.mp4", seconds=2), tmp_path / "an.mp4", layout="portrait")
    render = _clip(tmp_path / "render.mp4", seconds=2, size="480x832", fps=16, audio=False)  # like a GPU render
    assert a.has_audio and not media.probe(render).has_audio
    final = media.with_source_audio(render, tmp_path / "an.mp4", tmp_path / "f.mp4")
    assert media.probe(final).has_audio
    cmp_ = media.probe(media.side_by_side(tmp_path / "an.mp4", final, tmp_path / "c.mp4"))
    assert (cmp_.width, cmp_.height) == (960, 832)


def test_silent_clip_gets_a_silent_track(tmp_path):
    """The GPU-side video loader fails on a clip with no audio stream (measured)."""
    src = _clip(tmp_path / "silent.mp4", seconds=2.0, audio=False)
    assert not media.probe(src).has_audio
    out = media.normalize(src, tmp_path / "n.mp4", layout="portrait", seconds=1.5)
    assert out.has_audio
    assert out.seconds == pytest.approx(1.5, abs=0.1)


def test_baked_in_black_bars_are_found_and_removed(tmp_path):
    # a landscape picture inside a portrait frame, as phone re-shares carry it
    src = tmp_path / "bars.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=720x664:rate=30:duration=2",
                    "-vf", "pad=720:1128:0:232:black", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)],
                   check=True, timeout=120)
    box = media.content_box(src)
    assert box is not None
    w, h, x, y = box
    assert abs(w - 720) <= 4 and abs(h - 664) <= 4 and abs(y - 232) <= 4
    assert media.layout_for(w, h) == "square"  # the picture's shape, not the frame's
    out = media.normalize(src, tmp_path / "n.mp4", layout="square", box=box)
    assert (out.width, out.height) == (640, 640)


def test_clip_without_bars_has_no_box(tmp_path):
    assert media.content_box(_clip(tmp_path / "clean.mp4", seconds=2, size="480x832")) is None


def test_upscale_keeps_aspect_and_says_so(tmp_path):
    src = _clip(tmp_path / "r.mp4", seconds=1, size="480x832", fps=16)
    out = media.probe(media.upscale(src, tmp_path / "u.mp4", short_side=720))
    assert (out.width, out.height) == (720, 1248)
    assert not media.probe(media.without_audio(src, tmp_path / "m.mp4")).has_audio


@pytest.mark.parametrize("wh,layout", [((1080, 1920), "portrait_hd"), ((1202, 2312), "portrait_hd"), ((1440, 1920), "portrait_3x4"),
                                       ((1920, 1440), "landscape_4x3"), ((1920, 1080), "landscape_hd"), ((710, 664), "square")])
def test_layout_is_the_nearest_shape(wh, layout):
    """3:4 phone video used to be forced into 9:16, losing about a quarter of the picture."""
    assert media.layout_for(*wh) == layout


def test_delivery_is_the_exact_shape():
    assert media.delivery_size("portrait") == (468, 832)  # 480x832 renders are not exactly 9:16
    assert media.delivery_size("portrait", 1080) == (1080, 1920)
    assert media.delivery_size("landscape", 720) == (1280, 720)
    assert media.delivery_size("portrait_3x4", 720) == (720, 960)
    for k in ("portrait", "landscape", "square", "portrait_3x4", "landscape_4x3"):
        w, h = media.delivery_size(k)
        a, b = __import__("recast.graph", fromlist=["ASPECT"]).ASPECT[k]
        assert abs(w / h - a / b) < 0.01 and w % 2 == 0 and h % 2 == 0


def test_deliver_crops_then_scales(tmp_path):
    src = _clip(tmp_path / "r.mp4", seconds=1, size="480x832", fps=16)
    native = media.probe(media.deliver(src, tmp_path / "n.mp4", layout="portrait"))
    assert (native.width, native.height) == (468, 832)
    big = media.probe(media.deliver(src, tmp_path / "b.mp4", layout="portrait", short_side=720))
    assert (big.width, big.height) == (720, 1280)


def test_edge_colour_reads_the_background(tmp_path):
    img = tmp_path / "studio.png"  # a near-white room with a dark subject in the middle
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=0xEEEAE6:s=400x400",
                    "-vf", "drawbox=x=120:y=80:w=160:h=300:color=black:t=fill", "-frames:v", "1", str(img)],
                   check=True, timeout=60)
    c = media.edge_colour(img)
    r, g, b = c >> 16, (c >> 8) & 255, c & 255
    assert abs(r - 0xEE) <= 3 and abs(g - 0xEA) <= 3 and abs(b - 0xE6) <= 3


def test_moments_sheet_is_four_frames_in_a_grid(tmp_path):
    clip = tmp_path / "c.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=160x284:d=3:r=16",
                    "-pix_fmt", "yuv420p", str(clip)], check=True, timeout=60)
    info = media.probe(media.moments_sheet(clip, tmp_path / "m.png", height=100))
    assert info.height == 200 and info.width == 2 * (round(160 * 100 / 284) // 2 * 2)



@pytest.mark.parametrize("fps", ["24000/1001", "25", "30"])
@pytest.mark.parametrize("frames", [81, 161])
def test_normalize_gives_exactly_the_frames_asked(tmp_path, fps, frames):
    # The graph needs 1 + 4n frames exactly. ffmpeg 7.1 cut a 23.976 fps clip to 80 where 81 were asked
    # (a duration alone), and the render failed on 81 vs 80; a frame count can't come out short.
    rate = eval(fps)  # noqa: S307 - a literal from this test
    src = _clip(tmp_path / "in.mp4", seconds=frames / 16 + 1.0, fps=rate)
    out = media.normalize(src, tmp_path / "n.mp4", layout="portrait", seconds=frames / 16)
    n = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                        "stream=nb_read_frames", "-of", "csv=p=0", str(tmp_path / "n.mp4")],
                       capture_output=True, text=True, check=True).stdout.strip()
    assert int(n) == frames
    assert out.has_audio
