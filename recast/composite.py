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
