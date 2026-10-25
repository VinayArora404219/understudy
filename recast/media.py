"""ffmpeg/ffprobe helpers: validate an upload, normalize it for Animate-2,
and finish the result (original audio, side-by-side comparison).

Every subprocess gets an argument list (never a shell string) and a timeout,
so a filename or prompt can't become a command.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import graph

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"
TIMEOUT_S = 300

# Upload caps. A judge's clip is a few seconds of phone video.
MAX_UPLOAD_BYTES = 90 * 1024 * 1024  # under Cloudflare's 100 MB request cap in front of the public site
MAX_SECONDS = 30.0  # upload cap; the rendered window is at most MAX_SEGMENTS long
MIN_SECONDS = 1.0
MAX_SIDE = 4096
MIN_SIDE = 256
MAX_FRAMES = 60 * 60  # decoded frame ceiling, whatever the container claims


class MediaError(ValueError):
    """The file is not a usable input."""


@dataclass(frozen=True)
class VideoInfo:
    width: int  # as displayed, after rotation
    height: int
    fps: float
    seconds: float
    frames: int
    has_audio: bool

    @property
    def layout(self) -> str:
        return layout_for(self.width, self.height)


Box = tuple[int, int, int, int]  # w, h, x, y of the picture inside the frame


def layout_for(width: int, height: int) -> str:
    """The render layout whose shape is nearest to the picture's (by ratio, so 3:4 is not forced into 9:16)."""
    r = math.log(width / height)
    return min(graph.DEFAULT_LAYOUTS, key=lambda k: abs(r - math.log(graph.ASPECT[k][0] / graph.ASPECT[k][1])))


def _exact(width: int, height: int, a: int, b: int) -> tuple[int, int]:
    """The largest a:b box inside width x height, even-sized for yuv420p."""
    if width * b > height * a:
        width = height * a // b
    else:
        height = width * b // a
    return width // 2 * 2, height // 2 * 2


def delivery_size(layout: str, short_side: int | None = None) -> tuple[int, int]:
    """The exact-aspect size a render is delivered at: its largest crop, or that shape at `short_side`."""
    a, b = graph.ASPECT[layout]
    if short_side is None:
        return _exact(*graph.SIZES[layout], a, b)
    if a <= b:
        return short_side, round(short_side * b / a / 2) * 2
    return round(short_side * a / b / 2) * 2, short_side


def _run(args: list[str], timeout: float = TIMEOUT_S) -> subprocess.CompletedProcess[str]:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as e:
        raise MediaError(f"{args[0]} timed out") from e
    if r.returncode != 0:
        tail = r.stderr.strip().splitlines()[-3:]
        raise MediaError(f"{args[0]} failed: {' | '.join(tail)}")
    return r


def _ratio(text: str) -> float:
    num, _, den = text.partition("/")
    return float(num) / float(den or 1) if float(den or 1) else 0.0


def probe(path: str | Path) -> VideoInfo:
    r = _run([FFPROBE, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)], 60)
    data = json.loads(r.stdout)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise MediaError("no video stream")
    w, h = int(video["width"]), int(video["height"])
    rotation = 0
    for sd in video.get("side_data_list", []):
        if "rotation" in sd:
            rotation = int(sd["rotation"])
    rotation = int(video.get("tags", {}).get("rotate", rotation))
    if abs(rotation) % 180 == 90:
        w, h = h, w
    fps = _ratio(video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1")
    seconds = float(video.get("duration") or data.get("format", {}).get("duration") or 0)
    frames = int(video.get("nb_frames") or round(fps * seconds))
    return VideoInfo(w, h, fps, seconds, frames, any(s.get("codec_type") == "audio" for s in streams))


def validate_upload(path: str | Path) -> VideoInfo:
    """Reject anything outside the caps before it costs GPU time."""
    p = Path(path)
    size = p.stat().st_size
    if size > MAX_UPLOAD_BYTES:
        raise MediaError(f"file is over {MAX_UPLOAD_BYTES // 2**20} MB")
    if size == 0:
        raise MediaError("file is empty")
    info = probe(p)
    if not MIN_SECONDS <= info.seconds <= MAX_SECONDS:
        raise MediaError(f"clip must be {MIN_SECONDS:g}-{MAX_SECONDS:g} s long (got {info.seconds:.1f} s)")
    if not (MIN_SIDE <= min(info.width, info.height) and max(info.width, info.height) <= MAX_SIDE):
        raise MediaError(f"resolution {info.width}x{info.height} is outside {MIN_SIDE}-{MAX_SIDE} px")
    if not 5 <= info.fps <= 120:
        raise MediaError(f"frame rate {info.fps:.1f} is not supported")
    if info.frames > MAX_FRAMES:
        raise MediaError("too many frames")
    return info


def content_box(path: str | Path, *, sample_seconds: float = 10.0) -> Box | None:
    """The picture inside black bars baked into the video (letterbox or pillarbox), or None.

    Phone re-shares often carry them (a landscape clip inside a portrait frame). Left in, they
    become part of the scene the models draw. cropdetect runs with reset=0, so the box only
    ever grows across the sampled frames: one dark frame can't shrink it."""
    info = probe(path)
    r = _run([FFMPEG, "-hide_banner", "-v", "info", "-t", f"{sample_seconds:.1f}", "-i", str(path),
              "-vf", "fps=4,cropdetect=limit=24:round=2:reset=0", "-an", "-f", "null", "-"], 120)
    found = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", r.stderr)
    if not found:
        return None
    w, h, x, y = map(int, found[-1])
    if w >= 0.97 * info.width and h >= 0.97 * info.height:
        return None  # no bars worth removing
    if min(w, h) < MIN_SIDE:
        return None  # an almost-black clip, not a letterbox
    return w, h, x, y


def _crop(box: Box | None) -> str:
    return f"crop={box[0]}:{box[1]}:{box[2]}:{box[3]}," if box else ""


def normalize(src: str | Path, dst: str | Path, *, layout: str, seconds: float | None = None,
              start: float = 0.0, fps: int = 16, box: Box | None = None) -> VideoInfo:
    """Re-encode to the render shape: `fps`, centre-cropped to the layout's
    aspect at its exact size, trimmed, metadata stripped, audio kept (AAC)."""
    w, h = graph.SIZES[layout]
    vf = (f"{_crop(box)}fps={fps},scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,"
          f"crop={w}:{h},setsar=1")
    args = [FFMPEG, "-y", "-v", "error", "-ss", f"{start:.3f}", "-i", str(src)]
    # Every normalized clip carries an audio track: the video loader on the GPU side fails on a
    # clip with none (measured on a silent stock clip). Silent sources get digital silence.
    silent = not probe(src).has_audio
    if silent:
        args += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
    if seconds is not None:
        args += ["-t", f"{seconds:.3f}"]
    args += ["-vf", vf, "-map", "0:v:0", "-map", "1:a:0" if silent else "0:a:0", "-c:v", "libx264",
             "-crf", "16", "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
             "-ar", "48000", "-shortest", "-map_metadata", "-1", "-movflags", "+faststart", str(dst)]
    _run(args)
    return probe(dst)


def first_frame(src: str | Path, dst: str | Path) -> Path:
    _run([FFMPEG, "-y", "-v", "error", "-i", str(src), "-frames:v", "1", "-map_metadata", "-1", str(dst)])
    return Path(dst)


def frame_at(src: str | Path, dst: str | Path, *, layout: str, start: float = 0.0,
             long_side: int = 1472, box: Box | None = None) -> Path:
    """One full-quality frame at `start`, centre-cropped to the layout's aspect.
    It is what the reference is built from, so it gets more pixels than the render."""
    w, h = graph.SIZES[layout]
    tw, th = (round(long_side * w / h), long_side) if h >= w else (long_side, round(long_side * h / w))
    tw, th = tw - tw % 16, th - th % 16
    vf = f"{_crop(box)}scale={tw}:{th}:force_original_aspect_ratio=increase:flags=lanczos,crop={tw}:{th},setsar=1"
    _run([FFMPEG, "-y", "-v", "error", "-ss", f"{start:.3f}", "-i", str(src), "-vf", vf, "-frames:v", "1",
          "-map_metadata", "-1", str(dst)])
    return Path(dst)


def moments_sheet(src: str | Path, dst: str | Path, *, height: int = 512) -> Path:
    """Four moments of a clip (start, 1/3, 2/3, near the end) on one 2x2 picture, for a reader that sees images."""
    info = probe(src)
    times = [0.0, info.seconds / 3, 2 * info.seconds / 3, max(0.0, info.seconds - 0.3)]
    inputs: list[str] = []
    for t in times:
        inputs += ["-ss", f"{t:.2f}", "-i", str(src)]
    tiles = ";".join(f"[{i}:v]scale=-2:{height},setsar=1[t{i}]" for i in range(4))
    _run([FFMPEG, "-y", "-v", "error", *inputs, "-filter_complex",
          f"{tiles};[t0][t1]hstack[top];[t2][t3]hstack[bottom];[top][bottom]vstack[out]",
          "-map", "[out]", "-frames:v", "1", "-map_metadata", "-1", str(dst)])
    return Path(dst)


def clean_image(src: str | Path, dst: str | Path, *, max_side: int = 1536) -> Path:
    """Re-encode an uploaded still: decoded (so it is really an image), metadata
    stripped, long side capped, aspect kept."""
    vf = (f"scale='if(gt(iw,ih),min({max_side},iw),-2)':'if(gt(iw,ih),-2,min({max_side},ih))'"
          f":flags=lanczos,setsar=1")
    _run([FFMPEG, "-y", "-v", "error", "-i", str(src), "-vf", vf, "-frames:v", "1",
          "-map_metadata", "-1", str(dst)])
    return Path(dst)


def edge_colour(path: str | Path, *, border: float = 0.06) -> int:
    """Median colour of a picture's outer band, as 0xRRGGBB: what its background most likely is.
    Used as the backdrop for cut-outs, so a backdrop that leaks into an edit matches the room."""
    import cv2
    import numpy as np

    img = cv2.imread(str(path))
    if img is None:
        raise MediaError("image could not be read")
    h, w = img.shape[:2]
    bh, bw = max(1, int(h * border)), max(1, int(w * border))
    band = np.concatenate([img[:bh].reshape(-1, 3), img[-bh:].reshape(-1, 3),
                           img[:, :bw].reshape(-1, 3), img[:, -bw:].reshape(-1, 3)])
    b, g, r = (int(v) for v in np.median(band, axis=0))
    return (r << 16) | (g << 8) | b


def crop_image(src: str | Path, dst: str | Path, box: Box) -> Path:
    _run([FFMPEG, "-y", "-v", "error", "-i", str(src), "-vf", f"{_crop(box).rstrip(',')},setsar=1",
          "-frames:v", "1", "-map_metadata", "-1", str(dst)])
    return Path(dst)


def fit_image(src: str | Path, dst: str | Path, *, layout: str, mode: str = "pad") -> Path:
    """Fit a reference still to the render size. The input guide says pad, don't
    crop: a cropped reference loses the body the motion needs."""
    w, h = graph.SIZES[layout]
    if mode == "pad":
        vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,"
              f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=white,setsar=1")
    else:
        vf = f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,crop={w}:{h},setsar=1"
    _run([FFMPEG, "-y", "-v", "error", "-i", str(src), "-vf", vf, "-frames:v", "1",
          "-map_metadata", "-1", str(dst)])
    return Path(dst)


def with_source_audio(render: str | Path, source: str | Path, dst: str | Path) -> Path:
    """Video from the render, audio from the source clip, cut to the shorter."""
    _run([FFMPEG, "-y", "-v", "error", "-i", str(render), "-i", str(source),
          "-map", "0:v:0", "-map", "1:a:0?", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
          "-shortest", "-map_metadata", "-1", "-movflags", "+faststart", str(dst)])
    return Path(dst)


def without_audio(src: str | Path, dst: str | Path) -> Path:
    _run([FFMPEG, "-y", "-v", "error", "-i", str(src), "-map", "0:v:0", "-c:v", "copy", "-an",
          "-map_metadata", "-1", "-movflags", "+faststart", str(dst)])
    return Path(dst)


def deliver(src: str | Path, dst: str | Path, *, layout: str, short_side: int | None = None) -> Path:
    """Centre-crop a render to its layout's exact aspect, then (with short_side) lanczos-scale it.
    Scaling adds pixels, not detail, and is labelled "upscaled" wherever it is shown."""
    info = probe(src)
    a, b = graph.ASPECT[layout]
    cw, ch = _exact(info.width, info.height, a, b)
    w, h = delivery_size(layout, short_side) if short_side else (cw, ch)
    _run([FFMPEG, "-y", "-v", "error", "-i", str(src), "-vf", f"crop={cw}:{ch},scale={w}:{h}:flags=lanczos,setsar=1",
          "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264", "-crf", "16", "-preset", "medium",
          "-pix_fmt", "yuv420p", "-c:a", "copy", "-map_metadata", "-1", "-movflags", "+faststart", str(dst)])
    return Path(dst)


def upscale(src: str | Path, dst: str | Path, *, short_side: int) -> Path:
    """Lanczos resize to `short_side`, aspect kept. Labelled "upscaled" wherever it is shown:
    it adds pixels, not detail."""
    info = probe(src)
    f = short_side / min(info.width, info.height)
    w, h = round(info.width * f / 2) * 2, round(info.height * f / 2) * 2
    _run([FFMPEG, "-y", "-v", "error", "-i", str(src), "-vf", f"scale={w}:{h}:flags=lanczos,setsar=1",
          "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264", "-crf", "16", "-preset", "medium",
          "-pix_fmt", "yuv420p", "-c:a", "copy", "-map_metadata", "-1", "-movflags", "+faststart", str(dst)])
    return Path(dst)


def side_by_side(left: str | Path, right: str | Path, dst: str | Path, *, height: int = 832,
                 vertical: bool = False) -> Path:
    """Source next to (or above) the recast, both at one size, audio from the source."""
    stack = "vstack" if vertical else "hstack"
    scale = f"scale=-2:{height}:flags=lanczos" if not vertical else f"scale={height}:-2:flags=lanczos"
    fc = (f"[0:v]{scale},setsar=1,fps=16[a];[1:v]{scale},setsar=1,fps=16[b];"
          f"[a][b]{stack}=inputs=2:shortest=1[v]")
    _run([FFMPEG, "-y", "-v", "error", "-i", str(left), "-i", str(right), "-filter_complex", fc,
          "-map", "[v]", "-map", "0:a:0?", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
          "-c:a", "aac", "-shortest", "-map_metadata", "-1", "-movflags", "+faststart", str(dst)])
    return Path(dst)
