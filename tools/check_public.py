#!/usr/bin/env python3
"""Refuse to commit anything that should not be public.

Runs as the git pre-commit hook (tools/install_hooks.sh) on the staged files, or by hand:
    python3 tools/check_public.py            # staged files
    python3 tools/check_public.py --all      # every file git would track

Checks:
  * media, model weights and archives (outputs and uploads never enter git)
  * any file over 2 MB
  * private network addresses, home/mount paths, key-like strings
  * project-specific private words from private/patterns.txt (git-ignored; one regex per line),
    which is where machine names, usernames and private asset names belong
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_BYTES = 2 * 1024 * 1024
BLOCKED_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".wav", ".mp3", ".flac", ".m4a",
               ".safetensors", ".gguf", ".ckpt", ".pt", ".pth", ".onnx", ".bin",
               ".zip", ".tar", ".gz", ".7z", ".sqlite", ".db"}
GENERIC = [
    (r"\b(?:10|127)\.\d{1,3}\.\d{1,3}\.\d{1,3}\b|\b192\.168\.\d{1,3}\.\d{1,3}\b|\b172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b",
     "private IP address"),
    (r"/home/[a-z_][\w-]*/|/mnt/[\w-]+|/Users/[\w-]+/|[A-Z]:\\\\Users\\\\", "machine-specific path"),
    (r"(?i)\b(?:api[_-]?key|secret|token|password)\b\s*[:=]\s*['\"][^'\"\s]{12,}['\"]", "hard-coded secret"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\bsk-[A-Za-z0-9]{20,}|\bhf_[A-Za-z0-9]{30,}|\bAKIA[0-9A-Z]{16}\b",
     "key material"),
]
# Files allowed to mention loopback/example addresses (docs of how to run locally).
ALLOW = {".env.example", "tools/check_public.py", "README.md", "docs/APP_DESIGN.md"}
LOOPBACK = re.compile(r"\b127\.0\.0\.1\b")


def files(all_tracked: bool) -> list[str]:
    if all_tracked:
        cmd = ["git", "ls-files", "--cached", "--others", "--exclude-standard"]
    else:
        cmd = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"]
    out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [f for f in out.splitlines() if f]


def private_patterns() -> list[tuple[str, str]]:
    p = ROOT / "private" / "patterns.txt"
    if not p.exists():
        return []
    return [(line.strip(), "private word (private/patterns.txt)") for line in p.read_text().splitlines()
            if line.strip() and not line.startswith("#")]


def main() -> int:
    targets = files("--all" in sys.argv)
    rules = [(re.compile(rx), why) for rx, why in GENERIC + private_patterns()]
    problems: list[str] = []
    for rel in targets:
        path = ROOT / rel
        if not path.is_file():
            continue
        if path.suffix.lower() in BLOCKED_EXT:
            problems.append(f"{rel}: {path.suffix} files never go in git (media/weights/archives)")
            continue
        if path.stat().st_size > MAX_BYTES:
            problems.append(f"{rel}: over {MAX_BYTES // 2**20} MB")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # images etc.: size/extension rules already applied
        for n, line in enumerate(text.splitlines(), 1):
            for rx, why in rules:
                m = rx.search(line)
                if not m:
                    continue
                if rel in ALLOW and why == "private IP address" and LOOPBACK.search(m.group(0)):
                    continue
                if why == "private IP address" and m.group(0).startswith("127."):
                    continue  # loopback is not private information
                problems.append(f"{rel}:{n}: {why}: {m.group(0)[:60]}")
    if problems:
        print("check_public: refusing — these would be published:", file=sys.stderr)
        for p in problems:
            print("  " + p, file=sys.stderr)
        return 1
    print(f"check_public: {len(targets)} file(s) clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
