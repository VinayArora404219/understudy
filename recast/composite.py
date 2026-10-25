"""Put the people who aren't recast back as filmed (the CPU half of recast/keep.py).

The render's colours drift from the clip's (a white studio came back slightly grey), so a bystander pasted
back as filmed would sit in a cut-out of the clip's colour. Each frame's clip is first matched to the render
with a per-channel gain and offset, fitted on pixels that are background in both (outside every mask), then
blended in by the bystanders' soft mask. A new character in front of a bystander stays as rendered.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from . import media

GRADE_FRAMES = 12  # frames sampled for the clip's one grade
GRADE_KEEP = 0.5  # the share of pixels kept as room at each pass: those the fit already explains best
GRADE_GAIN = (0.8, 1.25)
BACKGROUND = 0.02  # masks below this are background for the colour fit
SMOOTH = 0.8  # the fit is smoothed over frames, so a hand passing by doesn't make the colour pulse


def _frames(src: Path, w: int, h: int, gray: bool = False):
    fmt, ch = ("gray", 1) if gray else ("rgb24", 3)
    p = subprocess.Popen([media.FFMPEG, "-v", "error", "-i", str(src), "-f", "rawvideo", "-pix_fmt", fmt,
                          "-s", f"{w}x{h}", "-"], stdout=subprocess.PIPE)
    size = w * h * ch
    try:
        while (buf := p.stdout.read(size)) and len(buf) == size:
            yield np.frombuffer(buf, np.uint8).reshape(h, w, ch).astype(np.float32)
    finally:  # the shortest of the three inputs ends the composite; stop the others quietly
        p.stdout.close()
        p.kill()
        p.wait()


def fit(src: np.ndarray, dst: np.ndarray, bg: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per-channel gain and offset taking `src`'s background to `dst`'s (least squares)."""
    gain, off = np.ones(3, np.float32), np.zeros(3, np.float32)
    if bg.sum() < 500:  # almost no background in view: leave the colour as rendered
        return gain, off
    for c in range(3):
        r, k = src[..., c][bg], dst[..., c][bg]
        var = r.var()
        if var > 1.0:
            gain[c] = np.clip(np.cov(r, k, bias=True)[0, 1] / var, 0.7, 1.4)
        off[c] = k.mean() - gain[c] * r.mean()
    return gain, off


def keep_others(clip: Path, render: Path, others: Path, new: Path, performers: Path, dst: Path, *,
                fps: float = 16.0) -> Path:
    """`render` with the people not recast (`others`, white = kept) as filmed, colour-matched to the render, and
    the new characters (`new`) always as rendered. `performers` (old and new) stay out of the colour fit: the
    clip shows the old performer there, the render the new one. Audio from `render`."""
    info = media.probe(render)
    w, h = info.width, info.height
    counts = {x.name: media.probe(x).frames for x in (render, others, new, performers)}
    if min(counts.values()) < counts[render.name]:  # measured once: a mask download came back half long
        raise RuntimeError(f"a keep mask is shorter than the render: {counts}")
    frames = min(media.probe(clip).frames, counts[render.name])
    # the length is set with -t: -shortest drops the frames still in the encoder when the pipe ends
    # (measured: 17 of 81 frames came out)
    enc = subprocess.Popen([media.FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
                            "-r", str(fps), "-i", "-", "-i", str(render), "-map", "0:v", "-map", "1:a?", "-c:v", "libx264",
                            "-crf", "14", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", f"{frames / fps:.4f}", str(dst)],
                           stdin=subprocess.PIPE)
    gain = off = None
    for r, c, o, nm, pm in zip(_frames(render, w, h), _frames(clip, w, h), _frames(others, w, h, gray=True),
                               _frames(new, w, h, gray=True), _frames(performers, w, h, gray=True)):
        keep = o[..., :1] / 255.0 * (1 - nm[..., :1] / 255.0)  # a new character in front wins
        g, f = fit(c, r, (o[..., 0] / 255.0 < BACKGROUND) & (pm[..., 0] / 255.0 < BACKGROUND))
        gain, off = (g, f) if gain is None else (SMOOTH * gain + (1 - SMOOTH) * g, SMOOTH * off + (1 - SMOOTH) * f)
        enc.stdin.write((r * (1 - keep) + np.clip(c * gain + off, 0, 255) * keep).astype(np.uint8).tobytes())
    enc.stdin.close()
    enc.wait()
    if enc.returncode:
        raise RuntimeError("encoding the composite failed")
    return dst


def grade_fit(render: np.ndarray, clip: np.ndarray, passes: int = 3) -> np.ndarray:
    """One gain per channel taking the render's colours to the clip's (an exposure and white balance), fitted on
    the room: pixels of `render` and `clip` (N, H, W, 3 each) that agree once graded. The new characters differ
    from the performers they replace, so each pass keeps only the half the fit explains best and fits again.
    A gain with an offset, fitted on a room that is all light (a white studio), took the contrast down and
    left the people washed out; a gain alone keeps dark things dark."""
    r, c = render.reshape(-1, 3), clip.reshape(-1, 3)
    use = np.ones(len(r), bool)
    gain = np.ones(3, np.float32)
    for _ in range(passes):
        for ch in range(3):
            x = r[use, ch].sum()
            gain[ch] = np.clip(c[use, ch].sum() / x, *GRADE_GAIN) if x > 0 else 1.0
        err = np.abs(r * gain - c).sum(1)
        use = err <= np.quantile(err, GRADE_KEEP)
    return gain


def grade(clip: Path, render: Path, dst: Path) -> Path:
    """`render` graded to the clip's colours, every frame alike (no pulsing), audio kept. In the clip's place
    the room is the render's own, and it drifts: a white studio came back about 27 levels darker. Matching
    the room and grading the whole frame keeps the people lit as the model drew them, with no seam."""
    info = media.probe(render)
    n = min(info.frames, media.probe(clip).frames)
    w, h = 288, max(2, round(288 * info.height / info.width / 2) * 2)
    every = max(1, n // GRADE_FRAMES)
    pick = lambda src: np.stack([f for i, f in enumerate(_frames(src, w, h)) if i % every == 0][:GRADE_FRAMES])
    gain = grade_fit(pick(render), pick(clip))
    lut = ":".join(f"{k}=clip(val*{gain[i]:.4f}\\,0\\,255)" for i, k in enumerate("rgb"))
    subprocess.run([media.FFMPEG, "-v", "error", "-y", "-i", str(render), "-vf", f"lutrgb={lut},format=yuv420p",
                    "-c:v", "libx264", "-crf", "14", "-c:a", "copy", str(dst)], check=True, timeout=600)
    return dst
