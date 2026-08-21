"""Tests for session search snippet highlighting + cursor pagination (SPEC-250 / ADR-048)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from maistro.sessions.search import (
    SessionSummary,
    make_snippet,
    search_sessions,
)

BASE = datetime(2026, 6, 1, tzinfo=UTC)


def _summary(n: int, body: str = "hello world") -> SessionSummary:
    return SessionSummary(
        session_id=f"s{n}",
        started_at=BASE + timedelta(minutes=n),
        message_count=1,
        title=f"session {n}",
        body=body,
    )


class TestMakeSnippet:
    def test_returns_none_when_query_absent(self) -> None:
        assert make_snippet("hello world", "xyz") is None

    def test_wraps_hit_in_markers(self) -> None:
        snippet = make_snippet("the quick brown fox", "quick")
        assert snippet is not None
        assert "<<quick>>" in snippet

    def test_windows_around_hit(self) -> None:
        body = ("a" * 200) + "TARGET" + ("b" * 200)
        snippet = make_snippet(body, "TARGET", width=10)
        assert snippet is not None
        assert snippet == ("a" * 10) + "<<TARGET>>" + ("b" * 10)

    def test_case_insensitive_match_preserves_body_case(self) -> None:
        snippet = make_snippet("Hello World", "world")
        assert snippet is not None
        assert "<<World>>" in snippet


class TestSearchSessions:
    def test_no_query_returns_reverse_chronological(self) -> None:
        sessions = [_summary(0), _summary(1), _summary(2)]
        page = search_sessions(sessions)
        assert [item.session_id for item in page.items] == ["s2", "s1", "s0"]
        assert all(item.snippet is None for item in page.items)

    def test_query_filters_to_matching_bodies(self) -> None:
        sessions = [_summary(0, "talks about cats"), _summary(1, "talks about dogs")]
        page = search_sessions(sessions, query="cats")
        assert [item.session_id for item in page.items] == ["s0"]
        assert page.items[0].snippet is not None
        assert "<<cats>>" in page.items[0].snippet

    def test_since_filters_out_older_sessions(self) -> None:
        sessions = [_summary(0), _summary(1), _summary(2)]
        page = search_sessions(sessions, since=BASE + timedelta(minutes=1))
        assert [item.session_id for item in page.items] == ["s2", "s1"]

    def test_empty_input_returns_empty_page(self) -> None:
        page = search_sessions([])
        assert page.items == ()
        assert page.next_cursor is None

    def test_cursor_pagination_matches_single_page_reassembly(self) -> None:
        sessions = [_summary(i) for i in range(5)]
        single_page = search_sessions(sessions, limit=5)

        reassembled: list[str] = []
        cursor: str | None = None
        for _ in range(10):
            page = search_sessions(sessions, limit=1, cursor=cursor)
            if not page.items:
                break
            reassembled.extend(item.session_id for item in page.items)
            cursor = page.next_cursor
            if cursor is None:
                break

        assert reassembled == [item.session_id for item in single_page.items]

    def test_next_cursor_none_when_exhausted(self) -> None:
        sessions = [_summary(0), _summary(1)]
        page = search_sessions(sessions, limit=50)
        assert page.next_cursor is None
