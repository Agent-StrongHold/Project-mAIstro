"""Session search: snippet highlighting + stable cursor pagination (SPEC-250 / ADR-048)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SessionSummary:
    session_id: str
    started_at: datetime
    message_count: int
    title: str
    body: str


@dataclass(frozen=True)
class SessionSearchResult(SessionSummary):
    snippet: str | None = None


@dataclass(frozen=True)
class SessionSearchPage:
    items: tuple[SessionSearchResult, ...]
    next_cursor: str | None


def make_snippet(body: str, query: str, *, width: int = 80) -> str | None:
    """Case-insensitive substring search; windows `width` chars around the first hit."""
    if not query:
        return None
    lower_body = body.lower()
    lower_query = query.lower()
    pos = lower_body.find(lower_query)
    if pos == -1:
        return None
    end = pos + len(query)
    start_window = max(0, pos - width)
    end_window = min(len(body), end + width)
    return f"{body[start_window:pos]}<<{body[pos:end]}>>{body[end:end_window]}"


def _cursor_key(summary: SessionSummary) -> tuple[datetime, str]:
    return (summary.started_at, summary.session_id)


def _encode_cursor(summary: SessionSummary) -> str:
    return f"{summary.started_at.isoformat()}|{summary.session_id}"


def search_sessions(
    sessions: Sequence[SessionSummary],
    *,
    query: str = "",
    since: datetime | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> SessionSearchPage:
    candidates = [s for s in sessions if since is None or s.started_at >= since]
    if query:
        candidates = [s for s in candidates if query.lower() in s.body.lower()]

    ordered = sorted(candidates, key=_cursor_key, reverse=True)

    if cursor is not None:
        started_at_str, _, session_id = cursor.partition("|")
        cursor_key = (datetime.fromisoformat(started_at_str), session_id)
        ordered = [s for s in ordered if _cursor_key(s) < cursor_key]

    page_items = ordered[:limit]
    next_cursor = _encode_cursor(page_items[-1]) if len(page_items) == limit else None

    results = tuple(
        SessionSearchResult(
            session_id=s.session_id,
            started_at=s.started_at,
            message_count=s.message_count,
            title=s.title,
            body=s.body,
            snippet=make_snippet(s.body, query) if query else None,
        )
        for s in page_items
    )
    return SessionSearchPage(items=results, next_cursor=next_cursor)
