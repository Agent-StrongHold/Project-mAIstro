"""Audit log pagination, scoping, and the million-row envelope (#358).

`GET /v1/audit` used to answer `list(stores.audit_log.values())` — the whole
corpus, unscoped, unbounded. These tests pin the replacement contract:

- bounded cursor (keyset) pagination, stable (created_at, id) DESC ordering,
  a hard maximum page size, and 400 (not silent page one) on a bad cursor;
- scope applied *in the query* before pagination — a non-admin principal
  cannot page into another actor's entries, on either backend;
- cursor stability under concurrent inserts: arrivals land above the cursor
  and never duplicate, skip, or reorder the walk below it;
- empty pages and walks past the end are empty pages, not errors;
- backend parity: the in-memory and durable (SQLite kv_store) engines answer
  identical queries with identical pages;
- the million-row performance envelope: on the durable backend, a page costs
  its own rows — measured wall-clock plus EXPLAIN QUERY PLAN evidence that
  the ordered walk uses idx_audit_log_order and no temp B-tree sort.

The durable tests run the real `maistro.state` State/PersistedStore pair over
a temp SQLite file seeded through the writer queue — the same kv_store
namespace production persists `stores.audit_log` into — without touching the
process-global store configuration.
"""

from __future__ import annotations

import json
import pathlib
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import stores  # noqa: E402
from services.audit_query import (  # noqa: E402
    EXPORT_MAX_ENTRIES,
    MAX_AUDIT_PAGE_SIZE,
    _encode_cursor,
    _page_sql,
    clamp_limit,
    iter_export_entries,
    page_entries,
)
from services.model_store import JsonStore  # noqa: E402

_BASE = datetime(2026, 1, 1, tzinfo=UTC)


def ts(i: int) -> str:
    """Distinct, monotonically increasing ISO-8601 UTC timestamp."""
    return (_BASE + timedelta(microseconds=i)).isoformat()


def entry(
    i: int,
    *,
    action: str = "login",
    actor: str = "alice",
    severity: str = "info",
    created_at: str | None = None,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": f"e-{i:06d}",
        "action": action,
        "actor": actor,
        "target": None,
        "detail": detail or {},
        "severity": severity,
        "created_at": created_at or ts(i),
    }


def seed(store: Any, entries: list[dict[str, Any]]) -> None:
    for e in entries:
        store[e["id"]] = dict(e)


def walk(
    store: Any, *, limit: int, start_cursor: str | None = None, **kwargs: Any
) -> list[dict[str, Any]]:
    """Walk every page from the top (or `start_cursor`); entries in page order."""
    collected: list[dict[str, Any]] = []
    cursor: str | None = start_cursor
    while True:
        page = page_entries(store, limit=limit, cursor=cursor, **kwargs)
        collected.extend(page.entries)
        if page.next_cursor is None:
            return collected
        cursor = page.next_cursor


@pytest.fixture(autouse=True)
def _clear_global_audit_log():
    for key in list(stores.audit_log.keys()):
        stores.audit_log.pop(key, None)
    yield
    for key in list(stores.audit_log.keys()):
        stores.audit_log.pop(key, None)


class DurableAudit:
    """Real State/PersistedStore over a temp SQLite file.

    Seeds the `audit_log` kv_store namespace through the writer queue — the
    acknowledged path production writes take — and serves queries through the
    engine's durable backend.
    """

    def __init__(self, tmp_path: pathlib.Path) -> None:
        from maistro.state import PersistedStore, State

        self.state = State(db_path=tmp_path / "state.db")
        self.backend = PersistedStore(self.state)
        self.backend.initialize()

    def seed_rows(self, entries: list[dict[str, Any]]) -> None:
        rows = [("audit_log", e["id"], json.dumps(e), ts(0)) for e in entries]

        def _insert(conn: Any) -> None:
            conn.executemany(
                "INSERT OR REPLACE INTO kv_store (store_name, key, value, updated_at) "
                "VALUES (?, ?, ?, ?)",
                rows,
            )

        self.state.submit_sync(_insert)

    def close(self) -> None:
        self.state.close()


@pytest.fixture()
def durable(tmp_path: pathlib.Path):
    harness = DurableAudit(tmp_path)
    yield harness
    harness.close()


# --------------------------------------------------------------------------- #
# Limit clamping and page bounds
# --------------------------------------------------------------------------- #


def test_limit_clamped_to_the_maximum_page_size() -> None:
    assert clamp_limit(None) == 50
    assert clamp_limit(0) == 1
    assert clamp_limit(-5) == 1
    assert clamp_limit(10) == 10
    assert clamp_limit(10**9) == MAX_AUDIT_PAGE_SIZE


def test_no_request_gets_more_than_the_maximum_page_size(
    admin_client: Any,
) -> None:
    for i in range(MAX_AUDIT_PAGE_SIZE + 50):
        stores.audit_log[f"e-{i:06d}"] = entry(i)
    r = admin_client.get("/v1/audit", params={"limit": 10**9})
    assert r.status_code == 200
    body = r.json()
    assert len(body["entries"]) == MAX_AUDIT_PAGE_SIZE
    assert body["next_cursor"] is not None


def test_limit_floor_is_one_entry(admin_client: Any) -> None:
    for i in range(3):
        stores.audit_log[f"e-{i:06d}"] = entry(i)
    r = admin_client.get("/v1/audit", params={"limit": 0})
    assert r.status_code == 200
    assert len(r.json()["entries"]) == 1


# --------------------------------------------------------------------------- #
# Ordering, continuation, empty pages
# --------------------------------------------------------------------------- #


def test_pages_are_newest_first_and_contiguous() -> None:
    store = JsonStore("audit_order")
    seed(store, [entry(i) for i in range(7)])
    page1 = page_entries(store, limit=3)
    assert [e["id"] for e in page1.entries] == ["e-000006", "e-000005", "e-000004"]
    page2 = page_entries(store, limit=3, cursor=page1.next_cursor)
    assert [e["id"] for e in page2.entries] == ["e-000003", "e-000002", "e-000001"]
    page3 = page_entries(store, limit=3, cursor=page2.next_cursor)
    assert [e["id"] for e in page3.entries] == ["e-000000"]
    assert page3.next_cursor is None


def test_cursor_preserves_the_stored_z_spelling_through_ties() -> None:
    """Production rows come from `AuditEntry.model_dump(mode="json")`, which
    spells UTC with a `Z` suffix, not `+00:00`. Normalising a decoded cursor
    to `+00:00` sorted it before every stored `...Z` key, so rows tied at a
    page boundary were skipped instead of ordered by id. Regression: a full
    walk over `Z`-spelled tied rows must yield every row, id DESC.
    """
    same = ts(1).replace("+00:00", "Z")
    store = JsonStore("audit_ties_z")
    seed(store, [entry(i, created_at=same) for i in range(5)])
    walked = walk(store, limit=2)
    assert [e["id"] for e in walked] == [
        "e-000004",
        "e-000003",
        "e-000002",
        "e-000001",
        "e-000000",
    ]


def test_durable_cursor_preserves_the_stored_z_spelling_through_ties(
    durable: DurableAudit,
) -> None:
    """Same regression against the SQL backend: the cursor value is compared
    byte-for-byte against `json_extract(value, '$.created_at')`, so it must
    carry the stored `Z` spelling.
    """
    same = ts(1).replace("+00:00", "Z")
    durable.seed_rows([entry(i, created_at=same) for i in range(5)])
    store = JsonStore("audit_ties_z_durable")
    walked = walk(store, limit=2, backend=durable.backend)
    assert [e["id"] for e in walked] == [
        "e-000004",
        "e-000003",
        "e-000002",
        "e-000001",
        "e-000000",
    ]


def test_equal_timestamps_are_broken_by_id_stably() -> None:
    store = JsonStore("audit_ties")
    same = ts(1)
    seed(
        store,
        [
            entry(3, created_at=same),
            entry(1, created_at=same),
            entry(2, created_at=same),
        ],
    )
    walked = walk(store, limit=2)
    # id DESC inside the tie: deterministic, not insertion-order-dependent.
    assert [e["id"] for e in walked] == ["e-000003", "e-000002", "e-000001"]


def test_empty_corpus_and_unmatched_filters_are_empty_pages() -> None:
    store = JsonStore("audit_empty")
    page = page_entries(store, limit=10)
    assert page.entries == []
    assert page.next_cursor is None
    seed(store, [entry(i) for i in range(3)])
    page = page_entries(store, limit=10, action="no-such-action")
    assert page.entries == []
    assert page.next_cursor is None


def test_walking_past_the_end_yields_an_empty_page_not_an_error() -> None:
    store = JsonStore("audit_past_end")
    seed(store, [entry(i) for i in range(2)])
    # A valid cursor older than every entry: a client resuming a walk the
    # corpus has outlived gets an empty page, not a 500.
    ancient = _encode_cursor(ts(-10), "e-000000")
    page = page_entries(store, limit=2, cursor=ancient)
    assert page.entries == []
    assert page.next_cursor is None


def test_malformed_cursor_is_refused(admin_client: Any) -> None:
    stores.audit_log["e-000000"] = entry(0)
    r = admin_client.get("/v1/audit", params={"cursor": "not-a-cursor"})
    assert r.status_code == 400


def test_malformed_cursor_timestamp_is_refused() -> None:
    import base64

    forged = base64.urlsafe_b64encode(
        json.dumps({"c": "not-a-timestamp", "i": "e-000001"}).encode()
    ).decode()
    store = JsonStore("audit_forged")
    seed(store, [entry(i) for i in range(3)])
    with pytest.raises(ValueError, match="cursor"):
        page_entries(store, limit=2, cursor=forged)


# --------------------------------------------------------------------------- #
# Cursor stability under concurrent inserts
# --------------------------------------------------------------------------- #


def test_arrivals_between_pages_never_duplicate_or_skip() -> None:
    store = JsonStore("audit_concurrent")
    seed(store, [entry(i) for i in range(200)])
    page1 = page_entries(store, limit=50)
    # 60 entries arrive concurrently — all newer than everything seeded, so
    # a keyset cursor must place them *above* the walk, never inside it.
    seed(store, [entry(i) for i in range(200, 260)])
    rest = walk(store, limit=50, start_cursor=page1.next_cursor)
    ids = [e["id"] for e in page1.entries] + [e["id"] for e in rest]
    assert len(ids) == len(set(ids)), "an entry appeared on two pages"
    pre_existing = {f"e-{i:06d}" for i in range(200)}
    assert pre_existing <= set(ids), "a pre-existing entry was skipped"
    assert not ({f"e-{i:06d}" for i in range(200, 260)} & set(ids[50:]))


def test_threaded_writes_keep_the_walk_strictly_ordered() -> None:
    store = JsonStore("audit_threaded")
    seed(store, [entry(i) for i in range(100)])

    stop = threading.Event()

    def writer() -> None:
        i = 100
        while not stop.is_set() and i < 400:
            store[f"e-{i:06d}"] = entry(i)
            i += 1
            time.sleep(0.0005)

    thread = threading.Thread(target=writer)
    thread.start()
    try:
        walked = walk(store, limit=17)
    finally:
        stop.set()
        thread.join()

    keys = [(e["created_at"], e["id"]) for e in walked]
    assert keys == sorted(keys, reverse=True), "walk was not strictly newest-first"
    assert len({e["id"] for e in walked}) == len(walked), "duplicate across pages"
    # Everything that existed before the walk began is in the walk.
    assert {f"e-{i:06d}" for i in range(100)} <= {e["id"] for e in walked}


# --------------------------------------------------------------------------- #
# Scope isolation
# --------------------------------------------------------------------------- #


def test_non_admin_scope_pages_only_their_own_entries() -> None:
    store = JsonStore("audit_scope")
    seed(store, [entry(i, actor="testuser" if i % 2 == 0 else "hidden-actor") for i in range(40)])
    scope = frozenset({"testuser", "user"})
    walked = walk(store, limit=7, actor_scope=scope)
    assert len(walked) == 20
    assert {e["actor"] for e in walked} == {"testuser"}
    # Scope applies before pagination: paging the scoped query never shows
    # another actor's entry at any page boundary.
    keys = [(e["created_at"], e["id"]) for e in walked]
    assert keys == sorted(keys, reverse=True)


def test_non_admin_cannot_filter_for_another_actor() -> None:
    store = JsonStore("audit_scope_filter")
    seed(store, [entry(i, actor="hidden-actor") for i in range(5)])
    page = page_entries(store, limit=10, actor="hidden-actor", actor_scope=frozenset({"testuser"}))
    assert page.entries == []
    assert page.next_cursor is None


def test_scope_isolation_through_the_route(admin_client: Any, authed_client: Any) -> None:
    stores.audit_log["e-000000"] = entry(0, actor="testuser", action="login")
    stores.audit_log["e-000001"] = entry(1, actor="other-user", action="login")
    stores.audit_log["e-000002"] = entry(2, actor="user", action="elevate")

    mine = authed_client.get("/v1/audit", params={"limit": 1})
    assert mine.status_code == 200
    body = mine.json()
    assert [e["id"] for e in body["entries"]] == ["e-000002"]
    assert body["next_cursor"] is not None
    second = authed_client.get("/v1/audit", params={"limit": 10, "cursor": body["next_cursor"]})
    second_ids = [e["id"] for e in second.json()["entries"]]
    assert second_ids == ["e-000000"], "scope leaked across a page boundary"
    assert "e-000001" not in second_ids

    probed = authed_client.get("/v1/audit", params={"actor": "other-user"})
    assert probed.status_code == 200
    assert probed.json()["entries"] == []

    everything = admin_client.get("/v1/audit")
    assert {e["id"] for e in everything.json()["entries"]} == {
        "e-000000",
        "e-000001",
        "e-000002",
    }


# --------------------------------------------------------------------------- #
# Backend parity (in-memory vs durable SQLite)
# --------------------------------------------------------------------------- #


def test_durable_backend_pages_identically_to_memory(durable: DurableAudit) -> None:
    corpus = [
        entry(i, actor="alice" if i % 3 else "bob", severity="warning" if i % 5 == 0 else "info")
        for i in range(120)
    ]
    memory_store = JsonStore("audit_parity")
    seed(memory_store, corpus)
    durable.seed_rows(corpus)

    for kwargs in (
        {},
        {"action": "login"},
        {"severity": "warning"},
        {"actor": "bob"},
        {"action": "login", "severity": "info", "actor": "alice"},
        {"actor_scope": frozenset({"bob"})},
    ):
        expected = walk(memory_store, limit=9, **kwargs)
        actual = walk(memory_store, limit=9, backend=durable.backend, **kwargs)
        assert actual == expected, f"backend parity broken for {kwargs}"


# --------------------------------------------------------------------------- #
# Export: bounded, filtered, scoped, streamable
# --------------------------------------------------------------------------- #


def test_export_is_capped_and_streamable(durable: DurableAudit) -> None:
    corpus = [entry(i) for i in range(EXPORT_MAX_ENTRIES + 50)]
    durable.seed_rows(corpus)
    exported = list(iter_export_entries(JsonStore("audit_export_cap"), backend=durable.backend))
    assert len(exported) == EXPORT_MAX_ENTRIES
    assert all(isinstance(e, dict) and e["id"] for e in exported)


def test_export_honors_filters_and_scope() -> None:
    store = JsonStore("audit_export_filter")
    seed(
        store,
        [entry(i, actor="testuser" if i % 2 else "hidden", action="login") for i in range(30)],
    )
    mine = list(iter_export_entries(store, action="login", actor_scope=frozenset({"testuser"})))
    assert len(mine) == 15
    assert {e["actor"] for e in mine} == {"testuser"}


def test_export_route_streams_ndjson_scoped(admin_client: Any, authed_client: Any) -> None:
    stores.audit_log["e-000000"] = entry(0, actor="testuser")
    stores.audit_log["e-000001"] = entry(1, actor="hidden-actor")
    r = authed_client.get("/v1/audit/export")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-ndjson")
    lines = [json.loads(line) for line in r.text.splitlines()]
    assert [e["id"] for e in lines] == ["e-000000"]

    admin = admin_client.get("/v1/audit/export", params={"action": "login"})
    admin_ids = [json.loads(line)["id"] for line in admin.text.splitlines()]
    # Newest first — the same ordering contract the list route walks.
    assert admin_ids == ["e-000001", "e-000000"]


# --------------------------------------------------------------------------- #
# Retention surface
# --------------------------------------------------------------------------- #


def test_retention_endpoint_states_the_bounds(admin_client: Any, authed_client: Any) -> None:
    r = admin_client.get("/v1/audit/retention")
    assert r.status_code == 200
    body = r.json()
    assert body["max_page_size"] == MAX_AUDIT_PAGE_SIZE
    assert body["export_max_entries"] == EXPORT_MAX_ENTRIES
    assert body["durable"] is False  # this test process runs in-memory
    assert body["corpus_purge"] == "none"
    # The scope answer is the server's own authorization decision, so the UI
    # never has to guess from a role field.
    assert body["scope"] == "deployment"
    assert authed_client.get("/v1/audit/retention").json()["scope"] == "own"


def test_retention_does_not_swallow_entry_detail(admin_client: Any) -> None:
    stores.audit_log["e-000000"] = entry(0)
    r = admin_client.get("/v1/audit/e-000000")
    assert r.status_code == 200
    assert r.json()["id"] == "e-000000"


# --------------------------------------------------------------------------- #
# Million-row performance envelope (durable backend)
# --------------------------------------------------------------------------- #


_PERF_ROWS = 1_000_000


def _perf_row(i: int) -> tuple[str, str, str, str]:
    created = (_BASE + timedelta(microseconds=i)).isoformat()
    value = (
        f'{{"id":"perf-{i:08d}","action":"login","actor":"perf-actor-{i % 500:04d}",'
        f'"target":null,"detail":{{"seq":{i}}},"severity":"info","created_at":"{created}"}}'
    )
    return ("audit_log", f"perf-{i:08d}", value, created)


def test_million_row_corpus_pages_in_bounded_time(durable: DurableAudit) -> None:
    """A page costs its own rows, not the corpus (#358 definition of done).

    Seeds 1,000,000 audit rows through one batched writer transaction (the
    shape a real corpus arrives in), then measures the ordered keyset walk.
    The bounds below are generous enough for shared CI hardware; the *plan*
    assertions carry the structural proof: the ordered walk must use
    idx_audit_log_order and must not sort.
    """
    durable.state.submit_sync(
        lambda conn: conn.executemany(
            "INSERT OR REPLACE INTO kv_store (store_name, key, value, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (_perf_row(i) for i in range(_PERF_ROWS)),
        )
    )

    # First page — this is also where production applies the ordering-index
    # migration (ensure_audit_index runs on the first durable query).
    started = time.perf_counter()
    page1 = page_entries(JsonStore("audit_perf"), backend=durable.backend, limit=100)
    first_page_s = time.perf_counter() - started
    assert len(page1.entries) == 100
    assert first_page_s < 5.0, f"first page took {first_page_s:.3f}s on {_PERF_ROWS} rows"

    # Structural evidence: the exact production SQL is index-driven, no sort.
    sql, params = _page_sql(action=None, severity=None, actor=None, cursor=None, actor_scope=None)
    reader = durable.state.open_reader()
    try:
        plan = reader.execute("EXPLAIN QUERY PLAN " + sql + " LIMIT 50", params).fetchall()
    finally:
        reader.close()
    plan_text = " ".join(str(row) for row in plan)
    assert "idx_audit_log_order" in plan_text, plan_text
    assert "TEMP B-TREE" not in plan_text, plan_text

    cursor = page1.next_cursor
    walked_ids = [e["id"] for e in page1.entries]
    for _page in range(3):
        started = time.perf_counter()
        page = page_entries(
            JsonStore("audit_perf"), backend=durable.backend, limit=100, cursor=cursor
        )
        elapsed = time.perf_counter() - started
        assert len(page.entries) == 100
        assert elapsed < 2.0, f"cursor page took {elapsed:.3f}s"
        walked_ids.extend(e["id"] for e in page.entries)
        cursor = page.next_cursor

    assert len(set(walked_ids)) == len(walked_ids)
    # Newest first: the first walk is the highest ids, contiguously.
    assert walked_ids[0] == f"perf-{_PERF_ROWS - 1:08d}"

    # A scoped (non-admin) page on the same corpus stays bounded: the scope
    # predicate rides the same indexed plan.
    started = time.perf_counter()
    scoped = page_entries(
        JsonStore("audit_perf"),
        backend=durable.backend,
        limit=50,
        actor_scope=frozenset({"perf-actor-0000"}),
    )
    scoped_s = time.perf_counter() - started
    assert len(scoped.entries) == 50
    assert scoped_s < 5.0, f"scoped page took {scoped_s:.3f}s"
    assert {e["actor"] for e in scoped.entries} == {"perf-actor-0000"}
