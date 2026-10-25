"""Make a judge link (server/links.py). Prints the link once; only a hash of it is kept.

    python3 tools/make_link.py "Judge 1" --cap 25 --days 40 [--base https://your.domain]

Writes RECAST_DATA/links.json (default runs/app), which the running server re-reads by itself.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.links import Links  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--cap", type=int, default=25, help="renders this link may use")
    ap.add_argument("--days", type=int, default=40, help="days until it stops working")
    ap.add_argument("--base", default="", help="the site's address, to print a full link")
    a = ap.parse_args()
    data = Path(os.environ.get("RECAST_DATA", "runs/app")).resolve()
    token, link = Links(data / "links.json").create(a.name, cap=a.cap, days=a.days)
    print(f"{link['name']} ({link['id']}): {a.cap} renders, until {link['expires'][:10]}")
    print(f"{a.base.rstrip('/')}/j/{token}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
