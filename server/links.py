"""Judge links: who is using the demo, and how many renders they have.

Each judge gets their own link, `/j/<token>`. Opening it sets a cookie, and everything they upload or render
is theirs alone: lists show only their work, anyone else's answers 404, and each link has its own render
cap. The links live in RECAST_DATA/links.json, never in git, and only a SHA-256 of each token is stored, so
the file can't be used to sign in.

    python3 tools/make_link.py "Judge 1" --cap 25 --days 40     # prints the link once
"""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

LOCAL = "local"  # the owner of everything made without a link (the self-host server, or work from before links)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Links:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._seen: float | None = None
        self._links: list[dict] = []

    def _read(self) -> list[dict]:
        """Re-read when the file changes, so a link made while the server runs works at once."""
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError:
            return []
        with self._lock:
            if mtime != self._seen:
                self._links = json.loads(self.path.read_text()).get("links", [])
                self._seen = mtime
            return self._links

    @staticmethod
    def _live(link: dict) -> bool:
        return datetime.fromisoformat(link["expires"]) > datetime.now(timezone.utc)

    def find(self, token: str) -> dict | None:
        """The link a token opens, while it hasn't expired."""
        if not token or len(token) > 200:
            return None
        digest = _digest(token)
        for link in self._read():
            if secrets.compare_digest(link["token_sha256"], digest) and self._live(link):
                return link
        return None

    def get(self, link_id: str | None) -> dict | None:
        return next((link for link in self._read() if link["id"] == link_id), None)

    def create(self, name: str, *, cap: int, days: int) -> tuple[str, dict]:
        """A new link: returns (token, record). The token is shown once and never stored."""
        if not name.strip() or not 1 <= cap <= 1000 or not 1 <= days <= 365:
            raise ValueError("a name, a cap of 1..1000 renders and 1..365 days")
        token = secrets.token_urlsafe(18)
        link = {"id": f"ln_{secrets.token_hex(4)}", "name": name.strip(), "token_sha256": _digest(token),
                "cap": cap, "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "expires": (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec="seconds")}
        links = list(self._read())
        links.append(link)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"links": links}, indent=1))
        tmp.replace(self.path)
        return token, link
