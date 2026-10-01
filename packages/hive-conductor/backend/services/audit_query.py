"""Cursor-paginated, scope-filtered reads over the audit store (#358).

`GET /v1/audit` used to return `list(stores.audit_log.values())` — the whole
corpus, unfiltered by authority, unbounded by page size, re-sorted per request.
A mature deployment carries tens of thousands of audit entries; that answer
transferred and mounted all of them per page view.

This module is the one read seam for the audit corpus. It enforces, in order:

1. **Scope** — a non-admin principal is constrained to entries whose `actor`
   names that principal. The constraint is part of the store query, evaluated
   *before* the page limit, so another actor's entries can neither be paged
   through nor hidden behind a page boundary. `None` scope means the caller is
   an operator and sees the deployment-wide trail.
2. **Filters** — `action` / `severity` / `actor` equality, applied in the same
   query, never after pagination.
3. **Keyset pagination** — stable `(created_at, id)` descending ordering with
   an opaque cursor. Offset pagination would rescan and reshuffle under
   concurrent inserts; a keyset cursor pins the last-seen sort key, so pages
   remain contiguous while new entries land above the cursor.

Two backends implement the identical contract:

- **Durable** — SQL over the `kv_store` namespace the `JsonStore` already
  persists to, using filter-shape expression indexes (`ensure_audit_index`).
  The database scopes and filters each bounded seek before merging aliases
  and cursor ranges; request work scales with the page, not the corpus.
  Index construction is corpus-sized work performed during store startup.
- **In-memory** — the same keyset walk over keys sorted per request. No
  cache: a freshness heuristic over a dict other code mutates directly
  (seeders, tests, future purge jobs) is exactly how stale-index bugs ship,
  and one cheap enough to beat a re-sort is not honest about same-length
  corpus replacement. This path serves dev/demo deployments without
  persistence, where corpus sizes are small; the durable backend is where
  bounded page cost is proven (see the million-row envelope test).

Retention: the corpus itself is append-only today — no purge job exists (the
retention policy lane is #325). This module's contribution to retention is the
*bounded* read surface: `RETENTION` names the deployment constants, and export
walks pages instead of materialising the corpus.
"""

from __future__ import annotations

import base64
import binascii
import json
from bisect import bisect_left
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from itertools import combinations
from typing import Any

#: Default page size for `GET /v1/audit`.
DEFAULT_AUDIT_PAGE_SIZE = 50

#: Hard ceiling on `limit`, whatever the caller asks for. One page's transfer,
#: JSON-parse, and render cost is bounded independently of the corpus.
MAX_AUDIT_PAGE_SIZE = 200

#: Page size the export walk uses internally — server-side memory bound, not
#: a client-visible page.
_EXPORT_PAGE_SIZE = 500

#: Hard ceiling on entries one export may stream. An unbounded export would be
#: the same whole-corpus transfer pagination exists to remove, wearing a
#: different content type.
EXPORT_MAX_ENTRIES = 10_000

#: Ordering contract, stated once for /retention and for this module's tests.
AUDIT_ORDERING = "created_at DESC, id DESC (keyset)"

_RETENTION: dict[str, Any] = {
    "ordering": AUDIT_ORDERING,
    "default_page_size": DEFAULT_AUDIT_PAGE_SIZE,
    "max_page_size": MAX_AUDIT_PAGE_SIZE,
    "export_max_entries": EXPORT_MAX_ENTRIES,
    "corpus_purge": "none",  # honest: no purge job exists (#325 owns that lane)
}

# Each supported equality-filter shape needs its own ordered seek. One index
# with all three fields cannot serve a query omitting a leading field without
# scanning/sorting the corpus. Eight partial indexes trade audit write/storage
# amplification for bounded reads; unrelated kv_store namespaces are excluded.
# Keep store_name in the key as well: SQLite needs the leading equality to
# satisfy the expression ORDER BY without a temporary sort.
_FILTER_FIELDS = ("actor", "action", "severity")
_AUDIT_INDEXES = {
    fields: "idx_audit_log_" + ("_".join(fields) if fields else "order")
    for size in range(len(_FILTER_FIELDS) + 1)
    for fields in combinations(_FILTER_FIELDS, size)
}
_AUDIT_INDEX_MIGRATION = "DROP INDEX IF EXISTS idx_audit_log_order;" + ";".join(
    f"CREATE INDEX IF NOT EXISTS {name} ON kv_store (store_name, "
    + "".join(f"json_extract(value, '$.{field}'), " for field in fields)
    + "json_extract(value, '$.created_at') DESC, key DESC) WHERE store_name = 'audit_log'"
    for fields, name in _AUDIT_INDEXES.items()
)
_AUDIT_INDEX_MIGRATION_NAME = "audit_log_seek_idx_002"


@dataclass(frozen=True)
class AuditPage:
    """One bounded page plus the opaque handle for the next one."""

    entries: list[dict[str, Any]]
    next_cursor: str | None


def retention() -> dict[str, Any]:
    """Deployment read-surface constants. Carries no corpus data."""
    return dict(_RETENTION, durable=None)  # durable filled by the route


def _encode_cursor(created_at: str, entry_id: str) -> str:
    payload = json.dumps({"c": created_at, "i": entry_id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[str, str]:
    """(created_at, id) from an opaque cursor, or ValueError if malformed.

    The timestamp is validated but deliberately not re-spelled. Cursors are
    minted from the stored `created_at` string (`_cursor_of`), and both
    backends compare that stored spelling byte-for-byte: Pydantic's JSON
    serialization writes UTC as `...Z`, which `datetime.isoformat()` would
    rewrite to `...+00:00` — a spelling that string-sorts *before* every
    stored `...Z` key, so rows tied at the page boundary would fall outside
    the keyset predicate and be skipped. Echoing the stored spelling keeps
    the comparison exact; only well-formedness is checked here.
    """
    try:
        raw = base64.urlsafe_b64decode(cursor.encode())
        payload = json.loads(raw)
        created_at, entry_id = payload["c"], payload["i"]
        if not isinstance(created_at, str) or not isinstance(entry_id, str):
            raise ValueError("cursor fields must be strings")
    except (binascii.Error, ValueError, KeyError, TypeError) as exc:
        raise ValueError("malformed audit cursor") from exc
    try:
        # Validation only: `fromisoformat` accepts both the `Z` and
        # `+00:00` spellings on the supported Pythons, and the parsed value
        # is discarded — the persisted string is what both backends compare.
        datetime.fromisoformat(created_at)
    except ValueError as exc:
        raise ValueError("malformed audit cursor timestamp") from exc
    return created_at, entry_id


def clamp_limit(limit: int | None) -> int:
    """Caller `limit` -> page size inside [1, MAX_AUDIT_PAGE_SIZE]."""
    if limit is None:
        return DEFAULT_AUDIT_PAGE_SIZE
    return max(1, min(int(limit), MAX_AUDIT_PAGE_SIZE))


def ensure_audit_index(backend: Any) -> None:
    """Apply ordered filter indexes at store startup, before serving requests.

    Direct query clients also call this idempotent guard. Production startup
    pays the corpus-sized migration cost, not the first HTTP page.
    `run_migration` answers from `schema_migrations` (one indexed SELECT) when
    the migration is already applied, so this is safe to call on every durable
    page request — and deliberately not cached by object id: CPython reuses ids
    after garbage collection, and a stale cache hit would silently skip the
    index on a fresh database.
    """
    state = getattr(backend, "_state", None)
    run_migration = getattr(state, "run_migration", None)
    if callable(run_migration):
        run_migration(_AUDIT_INDEX_MIGRATION_NAME, _AUDIT_INDEX_MIGRATION)


def page_entries(
    store: Any,
    *,
    action: str | None = None,
    severity: str | None = None,
    actor: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
    actor_scope: frozenset[str] | None = None,
    backend: Any | None = None,
) -> AuditPage:
    """One bounded, scope-filtered page of audit entries, newest first.

    `actor_scope` is the authorization constraint: the set of actor names this
    principal may see (`None` = unrestricted operator read). It composes with
    the caller's optional `actor` filter — a non-admin asking for another
    actor's entries gets an empty page, not another actor's entries.
    """
    page_size = clamp_limit(limit)
    if backend is not None:
        ensure_audit_index(backend)
        return _page_durable(
            backend,
            action=action,
            severity=severity,
            actor=actor,
            limit=page_size,
            cursor=cursor,
            actor_scope=actor_scope,
        )
    return _page_memory(
        store,
        action=action,
        severity=severity,
        actor=actor,
        limit=page_size,
        cursor=cursor,
        actor_scope=actor_scope,
    )


def iter_export_entries(
    store: Any,
    *,
    action: str | None = None,
    severity: str | None = None,
    actor: str | None = None,
    actor_scope: frozenset[str] | None = None,
    backend: Any | None = None,
) -> Iterator[dict[str, Any]]:
    """Bounded export walk: at most `EXPORT_MAX_ENTRIES`, `_EXPORT_PAGE_SIZE`
    rows of server-side memory at a time, same scope and filter contract as
    `page_entries`. Yields entries lazily — a page is fetched only after the
    previous page has been consumed — so the route's `StreamingResponse`
    emits bytes from the first page instead of buffering the full cap.
    """
    cursor: str | None = None
    emitted = 0
    while emitted < EXPORT_MAX_ENTRIES:
        page = page_entries(
            store,
            action=action,
            severity=severity,
            actor=actor,
            limit=min(_EXPORT_PAGE_SIZE, EXPORT_MAX_ENTRIES - emitted),
            cursor=cursor,
            actor_scope=actor_scope,
            backend=backend,
        )
        if not page.entries:
            return
        yield from page.entries
        emitted += len(page.entries)
        if page.next_cursor is None:
            return
        cursor = page.next_cursor


# --------------------------------------------------------------------------- #
# Durable backend — SQL over the kv_store namespace
# --------------------------------------------------------------------------- #


def _resolve_scope(
    actor: str | None, actor_scope: frozenset[str] | None
) -> tuple[frozenset[str] | None, str | None]:
    """Scope ∩ filter -> (allowed actor set, effective actor filter).

    `(None, actor)` — unrestricted caller, optional explicit filter.
    `(frozenset(), None)` — nothing can match: the caller names no actor of
    its own, or filters for an actor outside its scope (a non-admin asking
    for another actor's entries gets an empty page, never those entries).
    Otherwise — `(scope, narrowed_filter)`, both applied in the query.
    """
    if actor_scope is None:
        return None, actor
    if not actor_scope:
        return frozenset(), None
    if actor is None:
        return actor_scope, None
    if actor not in actor_scope:
        return frozenset(), None
    return actor_scope, actor


def _page_sql(
    *,
    action: str | None,
    severity: str | None,
    actor: str | None,
    cursor: str | None,
    actor_scope: frozenset[str] | None,
    limit: int,
) -> tuple[str, list[Any]]:
    """Exact bounded production SQL, including each seek's LIMIT.

    Scope aliases are separate equality seeks, not an IN scan followed by an
    unbounded sort. A cursor uses two disjoint ranges: same timestamp / lower
    id, and older timestamps. SQLite does not seek both keys of an expression
    index for a tuple inequality or OR; splitting the ranges also bounds work
    when millions of rows share a timestamp. The final merge sorts at most
    limit * aliases * 2 rows (HTTP principals have at most two aliases).
    """
    allowed, actor_filter = _resolve_scope(actor, actor_scope)
    actors = [actor_filter] if actor_filter is not None or allowed is None else sorted(allowed)
    if not actors:
        return "SELECT key, value FROM kv_store WHERE 0", []
    boundaries: list[tuple[str, list[Any]]] = [("", [])]
    if cursor is not None:
        created_at, entry_id = _decode_cursor(cursor)
        boundaries = [
            ("json_extract(value, '$.created_at') = ? AND key < ?", [created_at, entry_id]),
            ("json_extract(value, '$.created_at') < ?", [created_at]),
        ]
    seeks: list[str] = []
    params: list[Any] = []
    for scoped_actor in actors:
        filters = {"actor": scoped_actor, "action": action, "severity": severity}
        fields = tuple(field for field in _FILTER_FIELDS if filters[field] is not None)
        where = ["store_name = 'audit_log'"] + [
            f"json_extract(value, '$.{field}') = ?" for field in fields
        ]
        filter_params = [filters[field] for field in fields]
        for boundary, boundary_params in boundaries:
            clauses = where + ([boundary] if boundary else [])
            seeks.append(
                "SELECT key, value, json_extract(value, '$.created_at') AS created_at "
                f"FROM kv_store INDEXED BY {_AUDIT_INDEXES[fields]} WHERE "
                + " AND ".join(clauses)
                + " ORDER BY created_at DESC, key DESC LIMIT ?"
            )
            params.extend([*filter_params, *boundary_params, limit])
    # Even the merge happens in SQL; no scope/filter decision follows LIMIT.
    union = " UNION ALL ".join(f"SELECT * FROM ({seek})" for seek in seeks)
    return (
        f"SELECT key, value FROM ({union}) ORDER BY created_at DESC, key DESC LIMIT ?",
        [*params, limit],
    )


def _page_durable(
    backend: Any,
    *,
    action: str | None,
    severity: str | None,
    actor: str | None,
    limit: int,
    cursor: str | None,
    actor_scope: frozenset[str] | None,
) -> AuditPage:
    allowed_actors, _actor_filter = _resolve_scope(actor, actor_scope)
    if allowed_actors is not None and not allowed_actors:
        return AuditPage(entries=[], next_cursor=None)
    sql, params = _page_sql(
        action=action,
        severity=severity,
        actor=actor,
        cursor=cursor,
        actor_scope=actor_scope,
        limit=limit + 1,
    )

    state = getattr(backend, "_state", None)
    reader = state.open_reader()
    try:
        rows = reader.execute(sql, params).fetchall()
    finally:
        reader.close()

    has_more = len(rows) > limit
    rows = rows[:limit]
    entries: list[dict[str, Any]] = []
    for _key, raw in rows:
        # SECURITY-REVIEW: durable JSON is untrusted at the deserialization
        # boundary (same posture as JsonStore.initialize). A row this build
        # cannot parse is skipped rather than served.
        try:
            entry = json.loads(raw)
        except ValueError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    next_cursor = _cursor_of(entries[-1]) if has_more and entries else None
    return AuditPage(entries=entries, next_cursor=next_cursor)


# --------------------------------------------------------------------------- #
# In-memory backend — sorted key index over the JsonStore dict
# --------------------------------------------------------------------------- #


def _sorted_ascending(store: Any) -> list[tuple[str, str]]:
    """Ascending `(created_at, id)` keys of the store, sorted per request.

    Deliberately not cached: the store's dict is mutated by holders other
    than this module (seed data, tests, any future purge), and a freshness
    heuristic cheap enough to beat a re-sort is not honest about same-length
    corpus replacement. Re-sorting per request is O(n log n) with a small
    constant — correct, but not corpus-independent. Durable deployments use
    the indexed SQL path instead.

    The mapping is snapshotted with a C-level `list(store.items())` copy
    before any per-entry work: the copy is a single GIL-atomic operation,
    whereas deriving `_created_at_of` while walking the live dict would
    race a concurrent insert into
    `RuntimeError: dictionary changed size during iteration`.
    """
    snapshot = list(store.items())
    return sorted((_created_at_of(entry), key) for key, entry in snapshot)


def _created_at_of(entry: object) -> str:
    if isinstance(entry, dict):
        value = entry.get("created_at", "")
        return value if isinstance(value, str) else ""
    return str(getattr(entry, "created_at", ""))


def _matches(entry: Any, *, action: str | None, severity: str | None) -> bool:
    def field(name: str) -> str:
        if isinstance(entry, dict):
            value = entry.get(name, "")
            return value if isinstance(value, str) else ""
        return str(getattr(entry, name, ""))

    if action is not None and field("action") != action:
        return False
    return not (severity is not None and field("severity") != severity)


def actor_of(entry: Any) -> str:
    """The entry's actor name, tolerating non-dict rows.

    Shared by the query seam and the detail route: the row-level scope check
    in `GET /{entry_id}` must read the actor exactly the way the paginated
    query does, or the two surfaces could disagree about who may see a row.
    """

    if isinstance(entry, dict):
        value = entry.get("actor", "")
        return value if isinstance(value, str) else ""
    return str(getattr(entry, "actor", ""))


def _entry_accepted(
    entry: Any,
    *,
    action: str | None,
    severity: str | None,
    allowed_actors: frozenset[str] | None,
    actor_filter: str | None,
) -> bool:
    """Scope ∩ filter predicate for one in-memory entry."""
    if not _matches(entry, action=action, severity=severity):
        return False
    entry_actor = actor_of(entry)
    if allowed_actors is not None and entry_actor not in allowed_actors:
        return False
    return not (actor_filter is not None and entry_actor != actor_filter)


def _page_memory(
    store: Any,
    *,
    action: str | None,
    severity: str | None,
    actor: str | None,
    limit: int,
    cursor: str | None,
    actor_scope: frozenset[str] | None,
) -> AuditPage:
    cursor_key: tuple[str, str] | None = None
    if cursor is not None:
        cursor_key = _decode_cursor(cursor)

    allowed_actors, actor_filter = _resolve_scope(actor, actor_scope)
    if allowed_actors is not None and not allowed_actors:
        return AuditPage(entries=[], next_cursor=None)

    snapshot = _sorted_ascending(store)
    start = len(snapshot) if cursor_key is None else bisect_left(snapshot, cursor_key)
    entries: list[dict[str, Any]] = []
    next_cursor: str | None = None
    # Walk newest→oldest (the index is ascending; iterate from the cursor
    # position downward), collecting up to limit+1 matches to learn whether
    # another page exists without a second pass.
    pending: list[tuple[str, str, dict[str, Any]]] = []
    for pos in range(start - 1, -1, -1):
        created_at, key = snapshot[pos]
        try:
            entry = store[key]
        except KeyError:
            # Deleted between sort and walk — it is not in the corpus any
            # more, so it is not in the answer either.
            continue
        if not _entry_accepted(
            entry,
            action=action,
            severity=severity,
            allowed_actors=allowed_actors,
            actor_filter=actor_filter,
        ):
            continue
        pending.append((created_at, key, entry if isinstance(entry, dict) else _dump(entry)))
        if len(pending) > limit:
            break
    has_more = len(pending) > limit
    page_rows = pending[:limit]
    entries = [row[2] for row in page_rows]
    if has_more and entries:
        next_cursor = _encode_cursor(page_rows[-1][0], page_rows[-1][1])
    return AuditPage(entries=entries, next_cursor=next_cursor)


def _dump(entry: Any) -> dict[str, Any]:
    return entry.model_dump(mode="json") if hasattr(entry, "model_dump") else dict(entry)


def _cursor_of(entry: dict[str, Any]) -> str | None:
    created_at = entry.get("created_at")
    entry_id = entry.get("id")
    if isinstance(created_at, str) and isinstance(entry_id, str):
        return _encode_cursor(created_at, entry_id)
    return None
