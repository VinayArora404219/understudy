"""Rebuild the example clips in examples/clips/ from their sources (examples/README.md lists every credit).

    python3 tools/fetch_examples.py                    # -> examples/clips/<name>.mp4
    python3 tools/fetch_examples.py --music ~/Downloads --out examples/clips

The picture is each Pexels video, downloaded from Pexels and copied in unchanged (checked against the hash of
the clip we used). The raw files are not re-hosted here; the Pexels License doesn't allow that.

The sound is a Pixabay track. Pixabay doesn't allow scripted downloads, so download each track by hand from
pixabay.com/music (the title, creator and track id are below) into the --music folder. A track whose file is
missing is left out and that clip is made without sound, which the app accepts. With the tracks there, each is
cut from the same second, levelled and faded as in the clips we used. Needs ffmpeg.

Then `python3 tools/add_presets.py` lists them under "Use one of ours".
"""

import argparse
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
PEXELS = "https://videos.pexels.com/video-files/"

# Pixabay tracks: id -> (title, creator, integrated loudness of the whole track in LUFS, measured with ebur128)
TRACKS = {
    593670: ("Hip Hop Music", "kiravale", -10.6),
    544088: ("Chill Hip Hop (Version 2)", "BombinSound", -9.3),
    607791: ("Hip Hop Beat", "lnplusmusic", None),  # levelled with loudnorm instead
}

# name -> Pexels file, md5 of its video stream, and (Pixabay track id, start second) or None
CLIPS = {
    "dance_trio": ("8811210/8811210-hd_1920_1080_25fps.mp4", "247b4ce26413774c5ec3ea7557368a4e", (607791, 28)),
    "street_sunglasses": ("14955510/14955510-hd_1080_1920_30fps.mp4", "70cd123175cd9ca53d1e60299831f41a", None),
    "dance_duo_studio": ("4820385/4820385-hd_1080_1920_25fps.mp4", "145f10c5c7f33ae2681ceaa28d3dcb38", (593670, 12)),
    "dance_ballet_balcony": ("8854001/8854001-hd_720_1280_24fps.mp4", "6b1772c93234bae5f3b0b0670753caab", (544088, 24)),
    "dance_breaking": ("5363330/5363330-hd_1080_1920_25fps.mp4", "9651b61cf33252486957c08efcb976d0", (593670, 39)),
    "dance_man_and_dog": ("20186498/20186498-hd_1080_1920_24fps.mp4", "6412a5e08c2715da8467fea337916ef7", (544088, 44)),
}


def video_md5(p: Path) -> str:
    out = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(p), "-map", "0:v", "-c", "copy", "-f", "md5", "-"])
    return out.decode().strip().removeprefix("MD5=")


def duration(p: Path) -> float:
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                          "-of", "csv=p=0", str(p)]))


def track_file(music: Path, tid: int) -> Path | None:
    hits = sorted(music.glob(f"*{tid}*.mp3"))
    return hits[0] if hits else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--music", type=Path, default=Path.home() / "Downloads", help="folder with the Pixabay mp3s")
    ap.add_argument("--out", type=Path, default=ROOT / "examples" / "clips")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    missing = set()
    with tempfile.TemporaryDirectory() as tmp:
        for name, (path, md5, sound) in CLIPS.items():
            src = Path(tmp) / f"{name}.mp4"
            req = urllib.request.Request(PEXELS + path, headers={"User-Agent": UA})
            src.write_bytes(urllib.request.urlopen(req, timeout=300).read())
            if md5 and video_md5(src) != md5:
                print(f"  {name}: Pexels sent a different file than the one we used; skipped")
                continue
            dst, d = a.out / f"{name}.mp4", duration(src)
            mp3 = track_file(a.music, sound[0]) if sound else None
            if sound and not mp3:
                missing.add(sound[0])
            if not mp3:
                cmd = ["-i", str(src), "-map", "0:v", "-c:v", "copy", "-an"]
                note = "no sound"
            else:
                tid, start = sound
                lufs = TRACKS[tid][2]
                level = (f"volume={-14.0 - lufs:.1f}dB" if lufs is not None
                         else "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000,"
                              "aformat=sample_fmts=fltp:channel_layouts=stereo")
                af = f"atrim=0:{d:.3f},asetpts=PTS-STARTPTS,{level},afade=t=in:d=0.3,afade=t=out:st={d - 0.8:.2f}:d=0.8"
                cmd = ["-i", str(src), "-ss", str(start), "-i", str(mp3), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                       "-af", af, "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest"]
                note = f"{TRACKS[tid][1]} from {start} s"
            subprocess.run(["ffmpeg", "-y", "-v", "error", *cmd, "-movflags", "+faststart", str(dst)], check=True)
            print(f"  {dst.relative_to(ROOT) if dst.is_relative_to(ROOT) else dst}: {d:.1f} s, {note}")
    for tid in sorted(missing):
        title, creator, _ = TRACKS[tid]
        print(f"  no sound yet: download \"{title}\" by {creator} (Pixabay track {tid}) into {a.music} and run again")
    return 0


if __name__ == "__main__":
    sys.exit(main())
