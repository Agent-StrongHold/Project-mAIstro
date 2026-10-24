---
id: SPEC-250
title: "Session search — snippet highlighting + stable cursor pagination (ADR-048)"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-06-20
substrate:
  - maistro-engine#ADR-016
  - maistro-engine#ADR-034
implements:
  - maistro-engine#ADR-048
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/sessions/test_search.py
layer: Memory
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-250: Session search — snippet highlighting + stable cursor pagination

## Context

ADR-048 asks for a `GET /v1/sessions` endpoint over episodic/session history with full-text
search, `<<term>>` snippet highlighting, and stable cursor pagination. Nothing implementing any
part of this exists — `maistro.sessions.store.InMemorySessionStore` only exposes
`get_history(session_id)`; there is no cross-session search, no snippet generation, no
pagination. This SPEC scopes the pure, store-agnostic core: given a list of session summaries
(already fetched), rank/filter by a text query, generate `ts_headline`-style `<<term>>`
snippets, and paginate with a stable `(started_at, session_id)` cursor — the logic ADR-048's
acceptance criteria actually test, independent of which backing store (Postgres pg_trgm,
SQLite FTS5, in-memory) supplies the rows.

## Goals

- Add `SessionSummary` dataclass (`session_id`, `started_at`, `message_count`, `title`, `body`
  — `body` is the searchable text, e.g. concatenated message contents) to
  `maistro/sessions/search.py`.
- Add `make_snippet(body: str, query: str, *, width: int = 80) -> str | None`: case-insensitive
  substring search, returns the text window around the first hit with the hit wrapped in
  `<<...>>`; returns `None` if `query` doesn't appear in `body`.
- Add `search_sessions(sessions: Sequence[SessionSummary], *, query: str = "", since:
  datetime | None = None, limit: int = 50, cursor: str | None = None) -> SessionSearchPage`:
  - `query` empty → reverse-chronological order (by `started_at`), no snippet computed.
  - `query` non-empty → filter to sessions whose `body` contains `query`
    (case-insensitive), each result carries a `snippet` from `make_snippet`.
  - `since` filters out sessions started before it.
  - Cursor is an opaque, stable encoding of `(started_at, session_id)` of the last item on the
    previous page — pagination state survives concurrent inserts/deletes because it never
    relies on row offset.
- Add `SessionSearchPage` (`items: list[SessionSearchResult]`, `next_cursor: str | None`).
  `SessionSearchResult` extends `SessionSummary` with an optional `snippet: str | None`.

## Non-goals

- The `GET /v1/sessions` FastAPI route, profile-middleware auth/scoping enforcement, and the
  cross-tenant-leak boundary test — follow-up once a maistro-server route exists to host this
  logic (this SPEC is the pure function the route would call).
- Postgres `pg_trgm`/`ts_headline`/GIN index, SQLite FTS5 — production storage/ranking
  backends; this SPEC's `make_snippet`/`search_sessions` are deliberately simple
  substring-based reference implementations a real backend's SQL query would approximate.
- OTel `sessions.search` span instrumentation (ADR-037) — added at the route boundary, not here.
- Title derivation/caching, soft-delete filtering, `mode=semantic` vector search — explicitly
  out of scope per ADR-048 itself.
- Wiring into `InMemorySessionStore`/`EpisodicStore` — those stores hold per-session message
  lists, not pre-aggregated `SessionSummary` rows; the aggregation step is store-specific and
  deferred to the route-wiring follow-up.

## Decision

```python
# maistro/sessions/search.py
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

def make_snippet(body: str, query: str, *, width: int = 80) -> str | None: ...

def search_sessions(
    sessions: Sequence[SessionSummary],
    *,
    query: str = "",
    since: datetime | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> SessionSearchPage: ...
```

Cursor encoding: `f"{started_at.isoformat()}|{session_id}"`, opaque to callers (treated as a
black box, not parsed by them). `search_sessions` sorts candidates by `(started_at, session_id)`
descending, finds the cursor's position (or starts at the top if `cursor is None`), and returns
the next `limit` items plus a `next_cursor` (the last item's encoding, or `None` if exhausted).

## Acceptance criteria

- [x] `search_sessions` with no `query` returns sessions reverse-chronologically by `started_at`.
- [x] `search_sessions` with `query="foo"` only returns sessions whose `body` contains "foo"
      (case-insensitive), each with `snippet` containing `<<foo>>` (case-preserved from body).
- [x] `make_snippet` returns `None` when the query isn't present in `body`.
- [x] `make_snippet` windows `width` characters on each side of the first hit.
- [x] Cursor pagination is stable: inserting a new session between two pages does not change
      already-returned items or cause duplicates/gaps in the next page (property test —
      paginate the same fixed sessions list at `limit=1` and reassemble; result matches a
      single `limit=len(sessions)` call).
- [x] `since` filters out sessions with `started_at < since`.
- [x] Empty `sessions` input returns an empty page with `next_cursor=None`.

## Testing

- `packages/maistro-core/tests/sessions/test_search.py` (new) — unit tests for `make_snippet`
  edge cases, `search_sessions` filtering/ordering/since, and a Hypothesis or manual
  reassembly property test for cursor-pagination stability.

## Open questions

- Whether real backends (pg_trgm/FTS5) should be required to match `make_snippet`'s exact
  windowing behavior, or just its `<<term>>` marker convention — deferred to the route-wiring
  SPEC once a concrete backend is chosen.

## References

- `packages/maistro-core/src/maistro/sessions/store.py`
- `packages/maistro-core/src/maistro/types/session.py`
- [ADR-048: Session Search](../adr/ADR-048-session-search.md)
