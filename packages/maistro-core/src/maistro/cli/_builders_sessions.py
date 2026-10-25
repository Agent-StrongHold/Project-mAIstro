"""Local session history for `maistro builders`.

No Docker, no dev containers — `maistro builders` runs the agent loop directly
against a local checkout (see _builders_tui.py). This module just remembers
recently-opened checkouts in a small JSON file so the "Resume" button on the
welcome screen has something real to show.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

_HISTORY_FILE = Path.home() / ".maistro" / "builders_sessions.json"
_MAX_ENTRIES = 10


@dataclass
class BuilderSessionEntry:
    id: str
    path: str
    repo_url: str
    last_opened: float = field(default_factory=time.time)

    @property
    def status_label(self) -> str:
        return "available" if Path(self.path).is_dir() else "missing"


def make_session_id(repo: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9-]", "-", repo.rstrip("/").split("/")[-1].replace(".git", ""))
    slug = slug.strip("-") or "session"
    return f"{slug}-{int(time.time())}"


def load_sessions() -> list[BuilderSessionEntry]:
    if not _HISTORY_FILE.is_file():
        return []
    try:
        raw = json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    entries = [
        BuilderSessionEntry(**e) for e in raw if isinstance(e, dict) and "id" in e and "path" in e
    ]
    entries.sort(key=lambda e: e.last_opened, reverse=True)
    return entries


def record_session(session_id: str, path: Path, repo_url: str) -> None:
    entries = [e for e in load_sessions() if e.id != session_id]
    entries.insert(
        0,
        BuilderSessionEntry(
            id=session_id, path=str(path), repo_url=repo_url, last_opened=time.time()
        ),
    )
    entries = entries[:_MAX_ENTRIES]
    _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _HISTORY_FILE.write_text(
        json.dumps([e.__dict__ for e in entries], indent=2),
        encoding="utf-8",
    )


def get_session(session_id: str) -> BuilderSessionEntry | None:
    for e in load_sessions():
        if e.id == session_id:
            return e
    return None
