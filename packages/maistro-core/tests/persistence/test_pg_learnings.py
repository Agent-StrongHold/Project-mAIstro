"""Coverage for maistro.persistence.pg_learnings.PgLearningStore (was 0%).

asyncpg.Pool/Connection are faked with a small in-process test double that
records the exact SQL string and params passed to .execute()/.fetch()/
.fetchrow(), and returns canned rows, so tests assert on the SQL emitted and
the data round-tripped instead of merely "didn't raise".
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.persistence.pg_learnings import PgLearningStore
from maistro.types.memory import Learning, MemoryScope


class FakeRecord(dict):
    """Mimics asyncpg.Record: supports both ``row["x"]`` and ``row.get("x")``."""


class Call:
    """One recorded call to a Connection method."""

    def __init__(self, method: str, query: str, args: tuple[Any, ...]) -> None:
        self.method = method
        self.query = query
        self.args = args


class FakeConnection:
    """Records calls; returns canned rows queued via .queue_fetch/.queue_fetchrow."""

    def __init__(self) -> None:
        self.calls: list[Call] = []
        self._fetch_results: list[list[FakeRecord]] = []
        self._fetchrow_results: list[FakeRecord | None] = []
        self._execute_results: list[str] = []

    def queue_fetch(self, rows: list[dict[str, Any]]) -> None:
        self._fetch_results.append([FakeRecord(r) for r in rows])

    def queue_fetchrow(self, row: dict[str, Any] | None) -> None:
        self._fetchrow_results.append(FakeRecord(row) if row is not None else None)

    def queue_execute(self, status: str = "UPDATE 1") -> None:
        self._execute_results.append(status)

    async def fetch(self, query: str, *args: Any) -> list[FakeRecord]:
        self.calls.append(Call("fetch", query, args))
        return self._fetch_results.pop(0) if self._fetch_results else []

    async def fetchrow(self, query: str, *args: Any) -> FakeRecord | None:
        self.calls.append(Call("fetchrow", query, args))
        return self._fetchrow_results.pop(0) if self._fetchrow_results else None

    async def execute(self, query: str, *args: Any) -> str:
        self.calls.append(Call("execute", query, args))
        return self._execute_results.pop(0) if self._execute_results else "OK"


class FakePool:
    """Fakes asyncpg.Pool.acquire() as an async context manager yielding conn."""

    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn

    def acquire(self) -> _AcquireCtx:
        return _AcquireCtx(self._conn)


class _AcquireCtx:
    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn

    async def __aenter__(self) -> FakeConnection:
        return self._conn

    async def __aexit__(self, *exc: Any) -> None:
        return None


@pytest.fixture
def conn() -> FakeConnection:
    return FakeConnection()


@pytest.fixture
def store(conn: FakeConnection) -> PgLearningStore:
    return PgLearningStore(FakePool(conn))


def make_learning(**overrides: Any) -> Learning:
    defaults: dict[str, Any] = {
        "category": "general",
        "trigger_keys": ["foo", "bar"],
        "learning": "do not do X",
        "tool_name": "bash",
        "agent_id": "scribe",
        "user_id": "u1",
        "scope": MemoryScope.AGENT,
        "status": "active",
        "rca_category": None,
        "rca_prevention": "",
        "success_after_use": 0,
        "failure_after_use": 0,
    }
    defaults.update(overrides)
    return Learning(**defaults)


# --------------------------------------------------------------------------
# store()
# --------------------------------------------------------------------------


async def test_store_inserts_new_learning_when_no_existing_match(
    store: PgLearningStore, conn: FakeConnection
) -> None:
    conn.queue_fetch([])  # no existing rows for dedup check
    conn.queue_fetchrow({"id": 42})

    new_id = await store.store(make_learning())

    assert new_id == 42
    assert len(conn.calls) == 2
    dedup_call, insert_call = conn.calls
    assert dedup_call.method == "fetch"
    # H8: the dedup probe is scoped, so a store for one org cannot match,
    # bump and return another org's row.
    assert "WHERE tool_name = $1 AND org_id = $2 AND status = 'active'" in dedup_call.query
    assert dedup_call.args == ("bash", "")

    assert insert_call.method == "fetchrow"
    assert "INSERT INTO learnings" in insert_call.query
    assert "RETURNING id" in insert_call.query
    assert insert_call.args == (
        "general",
        ["foo", "bar"],
        "do not do X",
        "bash",
        "scribe",
        "u1",
        "",
        MemoryScope.AGENT,
        "active",
        None,
        "",
        0,
        0,
    )


async def test_store_dedupes_on_50pct_trigger_key_overlap_and_bumps_hit_count(
    store: PgLearningStore, conn: FakeConnection
) -> None:
    conn.queue_fetch([{"id": 7, "trigger_keys": ["foo", "baz"]}])
    conn.queue_execute()

    learning = make_learning(trigger_keys=["foo", "qux"])  # 1/2 = 50% overlap
    new_id = await store.store(learning)

    assert new_id == 7
    assert len(conn.calls) == 2
    update_call = conn.calls[1]
    assert update_call.method == "execute"
    assert update_call.query == "UPDATE learnings SET hit_count = hit_count + 1 WHERE id = $1"
    assert update_call.args == (7,)


async def test_store_inserts_when_overlap_below_threshold(
    store: PgLearningStore, conn: FakeConnection
) -> None:
    # existing has 4 keys, new shares only 1 -> 25% overlap, below 0.5 threshold
    conn.queue_fetch([{"id": 7, "trigger_keys": ["a", "b", "c", "d"]}])
    conn.queue_fetchrow({"id": 99})

    learning = make_learning(trigger_keys=["a", "x", "y", "z"])
    new_id = await store.store(learning)

    assert new_id == 99
    assert conn.calls[1].method == "fetchrow"


async def test_store_inserts_when_no_overlap_at_all(
    store: PgLearningStore, conn: FakeConnection
) -> None:
    conn.queue_fetch([{"id": 7, "trigger_keys": ["unrelated"]}])
    conn.queue_fetchrow({"id": 100})

    learning = make_learning(trigger_keys=["foo", "bar"])
    new_id = await store.store(learning)

    assert new_id == 100


async def test_store_defaults_missing_agent_id_to_empty_string(
    store: PgLearningStore, conn: FakeConnection
) -> None:
    conn.queue_fetch([])
    conn.queue_fetchrow({"id": 1})

    await store.store(make_learning(agent_id=None))

    insert_call = conn.calls[1]
    assert insert_call.args[4] == ""  # agent_id position


async def test_store_returns_zero_when_insert_returns_no_row(
    store: PgLearningStore, conn: FakeConnection
) -> None:
    conn.queue_fetch([])
    conn.queue_fetchrow(None)

    new_id = await store.store(make_learning())

    assert new_id == 0


# --------------------------------------------------------------------------
# find_relevant()
# --------------------------------------------------------------------------


async def test_find_relevant_filters_by_agent_id_when_given(
    store: PgLearningStore, conn: FakeConnection
) -> None:
    conn.queue_fetch([])

    await store.find_relevant("hello", agent_id="scribe")

    call = conn.calls[0]
    # $1 is now org_id (always bound); agent_id shifted to $2.
    assert "AND org_id = $1" in call.query
    assert "AND (agent_id = $2 OR agent_id = '')" in call.query
    assert call.args == ("", "scribe")


async def test_find_relevant_omits_agent_filter_when_agent_id_absent(
    store: PgLearningStore, conn: FakeConnection
) -> None:
    conn.queue_fetch([])

    await store.find_relevant("hello")

    call = conn.calls[0]
    assert "agent_id" not in call.query
    # The scope predicate is NOT optional — omitting org_id means global scope,
    # not "no filter". H8: this query previously had no scope predicate at all.
    assert "AND org_id = $1" in call.query
    assert call.args == ("",)


async def test_find_relevant_scores_and_sorts_by_keyword_match_count(
    store: PgLearningStore, conn: FakeConnection
) -> None:
    conn.queue_fetch(
        [
            {
                "id": 1,
                "category": "c",
                "trigger_keys": ["foo"],
                "learning": "low score",
                "tool_name": "t",
                "agent_id": None,
                "user_id": None,
                "scope": "agent",
                "hit_count": 0,
                "status": "active",
                "rca_category": None,
                "rca_prevention": "",
                "success_after_use": 0,
                "failure_after_use": 0,
            },
            {
                "id": 2,
                "category": "c",
                "trigger_keys": ["foo", "bar"],
                "learning": "high score",
                "tool_name": "t",
                "agent_id": None,
                "user_id": None,
                "scope": "agent",
                "hit_count": 0,
                "status": "active",
                "rca_category": None,
                "rca_prevention": "",
                "success_after_use": 0,
                "failure_after_use": 0,
            },
            {
                "id": 3,
                "category": "c",
                "trigger_keys": ["nomatch"],
                "learning": "zero score excluded",
                "tool_name": "t",
                "agent_id": None,
                "user_id": None,
                "scope": "agent",
                "hit_count": 0,
                "status": "active",
                "rca_category": None,
                "rca_prevention": "",
                "success_after_use": 0,
                "failure_after_use": 0,
            },
        ]
    )

    results = await store.find_relevant("foo bar baz")

    assert [r.id for r in results] == [2, 1]


async def test_find_relevant_respects_max_results(
    store: PgLearningStore, conn: FakeConnection
) -> None:
    conn.queue_fetch(
        [
            {
                "id": i,
                "category": "c",
                "trigger_keys": ["foo"],
                "learning": f"l{i}",
                "tool_name": "t",
                "agent_id": None,
                "user_id": None,
                "scope": "agent",
                "hit_count": 0,
                "status": "active",
                "rca_category": None,
                "rca_prevention": "",
                "success_after_use": 0,
                "failure_after_use": 0,
            }
            for i in range(5)
        ]
    )

    results = await store.find_relevant("foo", max_results=2)

    assert len(results) == 2


async def test_find_relevant_is_case_insensitive(
    store: PgLearningStore, conn: FakeConnection
) -> None:
    conn.queue_fetch(
        [
            {
                "id": 1,
                "category": "c",
                "trigger_keys": ["FOO"],
                "learning": "l",
                "tool_name": "t",
                "agent_id": None,
                "user_id": None,
                "scope": "agent",
                "hit_count": 0,
                "status": "active",
                "rca_category": None,
                "rca_prevention": "",
                "success_after_use": 0,
                "failure_after_use": 0,
            }
        ]
    )

    results = await store.find_relevant("text with foo in it")

    assert len(results) == 1


# --------------------------------------------------------------------------
# mark_used()
# --------------------------------------------------------------------------


async def test_mark_used_executes_update_with_id_array(
    store: PgLearningStore, conn: FakeConnection
) -> None:
    conn.queue_execute()

    await store.mark_used([1, 2, 3])

    call = conn.calls[0]
    assert call.method == "execute"
    assert call.query == "UPDATE learnings SET hit_count = hit_count + 1 WHERE id = ANY($1::int[])"
    assert call.args == ([1, 2, 3],)


async def test_mark_used_is_noop_for_empty_list(
    store: PgLearningStore, conn: FakeConnection
) -> None:
    await store.mark_used([])

    assert conn.calls == []


# --------------------------------------------------------------------------
# mark_outcome()
# --------------------------------------------------------------------------


async def test_mark_outcome_success_increments_success_counter(
    store: PgLearningStore, conn: FakeConnection
) -> None:
    conn.queue_execute()

    await store.mark_outcome([5], success=True)

    call = conn.calls[0]
    assert "success_after_use = success_after_use + 1" in call.query
    assert "AND org_id = $2" in call.query
    assert call.args == ([5], "")


async def test_mark_outcome_failure_increments_failure_counter(
    store: PgLearningStore, conn: FakeConnection
) -> None:
    conn.queue_execute()

    await store.mark_outcome([5], success=False)

    call = conn.calls[0]
    assert "failure_after_use = failure_after_use + 1" in call.query
    assert "AND org_id = $2" in call.query
    assert call.args == ([5], "")


async def test_mark_outcome_is_noop_for_empty_list(
    store: PgLearningStore, conn: FakeConnection
) -> None:
    await store.mark_outcome([], success=True)

    assert conn.calls == []


# --------------------------------------------------------------------------
# check_auto_promotions()
# --------------------------------------------------------------------------


async def test_check_auto_promotions_promotes_rows_above_threshold(
    store: PgLearningStore, conn: FakeConnection
) -> None:
    conn.queue_fetch(
        [
            {
                "id": 1,
                "category": "c",
                "trigger_keys": ["foo"],
                "learning": "l",
                "tool_name": "t",
                "agent_id": None,
                "user_id": None,
                "scope": "agent",
                "hit_count": 5,
                "status": "promoted",
                "rca_category": None,
                "rca_prevention": "",
                "success_after_use": 0,
                "failure_after_use": 0,
            }
        ]
    )

    results = await store.check_auto_promotions(threshold=5)

    call = conn.calls[0]
    assert "UPDATE learnings SET status = 'promoted'" in call.query
    assert "hit_count >= $1" in call.query
    assert "AND org_id = $2" in call.query
    assert call.args == (5, "")
    assert len(results) == 1
    assert results[0].status == "promoted"


async def test_check_auto_promotions_default_threshold_is_five(
    store: PgLearningStore, conn: FakeConnection
) -> None:
    conn.queue_fetch([])

    await store.check_auto_promotions()

    assert conn.calls[0].args == (5, "")


# --------------------------------------------------------------------------
# get_promoted()
# --------------------------------------------------------------------------


async def test_get_promoted_filters_by_task_type_when_given(
    store: PgLearningStore, conn: FakeConnection
) -> None:
    conn.queue_fetch([])

    await store.get_promoted(task_type="coding")

    call = conn.calls[0]
    assert "AND category = $2" in call.query
    assert "AND org_id = $1" in call.query
    assert call.args == ("", "coding")


async def test_get_promoted_omits_filter_when_task_type_absent(
    store: PgLearningStore, conn: FakeConnection
) -> None:
    conn.queue_fetch([])

    await store.get_promoted()

    call = conn.calls[0]
    assert "category" not in call.query
    assert "AND org_id = $1" in call.query
    assert call.args == ("",)


# --------------------------------------------------------------------------
# list_all()
# --------------------------------------------------------------------------


async def test_list_all_orders_by_id_desc_with_limit(
    store: PgLearningStore, conn: FakeConnection
) -> None:
    conn.queue_fetch([])

    await store.list_all(limit=50)

    call = conn.calls[0]
    assert call.query == ("SELECT * FROM learnings WHERE org_id = $1 ORDER BY id DESC LIMIT $2")
    assert call.args == ("", 50)


async def test_list_all_default_limit_is_200(store: PgLearningStore, conn: FakeConnection) -> None:
    conn.queue_fetch([])

    await store.list_all()

    assert conn.calls[0].args == ("", 200)


async def test_list_all_maps_rows_to_learning_dataclasses(
    store: PgLearningStore, conn: FakeConnection
) -> None:
    conn.queue_fetch(
        [
            {
                "id": 9,
                "category": "rca",
                "trigger_keys": ["k1", "k2"],
                "learning": "lesson text",
                "tool_name": "git",
                "agent_id": "",
                "user_id": "u9",
                "scope": "team",
                "hit_count": 3,
                "status": "active",
                "rca_category": "config",
                "rca_prevention": "validate first",
                "success_after_use": 2,
                "failure_after_use": 1,
            }
        ]
    )

    [learning] = await store.list_all()

    assert learning.id == 9
    assert learning.category == "rca"
    assert learning.trigger_keys == ["k1", "k2"]
    assert learning.learning == "lesson text"
    assert learning.tool_name == "git"
    assert learning.agent_id is None  # "" coerced to None by _row_to_learning
    assert learning.user_id == "u9"
    assert learning.scope == "team"
    assert learning.hit_count == 3
    assert learning.status == "active"
    assert learning.rca_category == "config"
    assert learning.rca_prevention == "validate first"
    assert learning.success_after_use == 2
    assert learning.failure_after_use == 1
