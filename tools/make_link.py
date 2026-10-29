"""Make, list or revoke judge links (server/links.py). A new link is printed once; only a hash of it is kept.

    python3 tools/make_link.py "Judge 1" --credits 300 --days 40 [--base https://your.domain]
    python3 tools/make_link.py --list
    python3 tools/make_link.py --revoke <link id>

Writes RECAST_DATA/links.json (default runs/app), which the running server re-reads by itself. The same can be
done in the browser at /admin when RECAST_ADMIN_PASSWORD is set.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.links import Links  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("name", nargs="?")
    ap.add_argument("--credits", type=int, default=300, help="seconds of video this link may render")
    ap.add_argument("--days", type=int, default=40, help="days until it stops working")
    ap.add_argument("--base", default="", help="the site's address, to print a full link")
    ap.add_argument("--list", action="store_true", help="list the links (never their addresses)")
    ap.add_argument("--revoke", metavar="LINK_ID", help="stop a link working, at once")
    a = ap.parse_args()
    links = Links(Path(os.environ.get("RECAST_DATA", "runs/app")).resolve() / "links.json")
    if a.list:
        for link in links.all():
            state = "revoked" if link.get("revoked") else "live" if Links.live(link) else "expired"
            print(f"{link['id']}  {state:7}  {Links.credits(link):5} credits  until {link['expires'][:10]}  {link['name']}")
        return 0
    if a.revoke:
        try:
            link = links.revoke(a.revoke)
        except KeyError:
            print(f"no link {a.revoke}", file=sys.stderr)
            return 1
        print(f"{link['name']} ({link['id']}) revoked")
        return 0
    if not a.name:
        ap.error("give the new link a name, or use --list / --revoke")
    token, link = links.create(a.name, credits=a.credits, days=a.days)
    print(f"{link['name']} ({link['id']}): {a.credits} credits (seconds of video), until {link['expires'][:10]}")
    print(f"{a.base.rstrip('/')}/j/{token}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
