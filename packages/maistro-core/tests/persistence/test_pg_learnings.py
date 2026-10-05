"""Coverage for maistro.persistence.pg_learnings.PgLearningStore (was 0%).

asyncpg.Pool/Connection are faked with a small in-process test double that
records the exact SQL string and params passed to .execute()/.fetch()/
.fetchrow(), and returns canned rows, so tests assert on the SQL emitted and
the data round-tripped instead of merely "didn't raise".
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from maistro.memory.exposure import MemoryExposureMode
from maistro.memory.vectors import EMBEDDING_DIMENSIONS
from maistro.observability.correlation import bind_execution_context
from maistro.persistence.pg_learnings import (
    _PG_INSERT_FIELDS,
    PgLearningStore,
    similarity_query,
)
from maistro.types.memory import EpistemicType, Learning, LearningStage, MemoryScope

from .conftest import requires_postgres


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
    return PgLearningStore(FakePool(conn), exposure_mode=MemoryExposureMode.AGENT_MANAGED)


def make_learning(**overrides: Any) -> Learning:
    defaults: dict[str, Any] = {
        "category": "general",
        "trigger_keys": ["foo", "bar"],
        "learning": "do not do X",
        "tool_name": "bash",
        "source_query": "why did X fail",
        "team_id": "team-a",
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
# scope query helpers
# --------------------------------------------------------------------------


def test_similarity_query_applies_all_learning_scope_axes() -> None:
    query = similarity_query(scoped_to_team=True, scoped_to_user=True, scoped_to_agent=True)

    assert "org_id = $2" in query
    assert "team_id = $3" in query
    assert "user_id = $4" in query
    assert "agent_id = $5" in query
    assert "LIMIT $6" in query


# --------------------------------------------------------------------------
# store()
# --------------------------------------------------------------------------


async def test_store_inserts_new_learning_when_no_existing_match(
    store: PgLearningStore, conn: FakeConnection
) -> None:
    conn.queue_fetch([])  # no existing rows for dedup check
    conn.queue_fetchrow({"id": 42})

    learning = make_learning()
    new_id = await store.store(learning)

    assert new_id == 42
    assert len(conn.calls) == 2
    dedup_call, insert_call = conn.calls
    assert dedup_call.method == "fetch"
    # H8: the dedup probe is scoped, so a store for one org cannot match,
    # bump and return another org's row.
    assert "WHERE tool_name = $1 AND org_id = $2" in dedup_call.query
    assert "team_id = $3" in dedup_call.query
    assert "user_id IS NOT DISTINCT FROM $4" in dedup_call.query
    assert "agent_id = $5" in dedup_call.query
    assert dedup_call.args == ("bash", "", "team-a", "u1", "scribe")

    assert insert_call.method == "fetchrow"
    assert "INSERT INTO learnings" in insert_call.query
    assert "RETURNING id" in insert_call.query
    columns = insert_call.query.split("(", 1)[1].split(")", 1)[0]
    assert tuple(c.strip() for c in columns.split(",")) == _PG_INSERT_FIELDS
    # `trigger_keys` goes out as JSON text, not as a list: the column is JSONB
    # and asyncpg's codec for it is text in both directions, so a list raised.
    # `source_query`, `team_id` and `hit_count` are written rather than omitted
    # because all three are columns the read paths select, and a column the
    # writer skips always reads back as its default (#122). `hit_count` in
    # particular is what `find_relevant` orders by, so a caller that supplies
    # one — a re-import, a merge — must get it back.
    assert insert_call.args == (
        "general",
        '["foo", "bar"]',
        "do not do X",
        "bash",
        # source_query and team_id, which the insert used to omit while the read
        # paths selected them — see #122.
        "why did X fail",
        "scribe",
        "u1",
        "",
        "team-a",
        MemoryScope.AGENT,
        0,
        "active",
        None,
        "",
        0,
        0,
        # The producer, written as NULL rather than "" because this learning was
        # made with no execution in scope: an empty string would name a Run
        # whose id is empty, which is a claim (#709).
        None,
        None,
        None,
        # M4-B3 + pipeline epistemics, reconciled (ADR-100126-b3c7,
        # ADR-100126-8c2d): a fresh learning lands empirical at the default
        # confidence, with no applicability recorded and empty evidence lists.
        "empirical",
        "[]",
        "[]",
        0.5,
        "[]",
        "[]",
        # Knowledge-stage ladder + lifecycle (ADR-103, ADR-100126-8c2d):
        # written like every other durable field so a restart cannot demote a
        # validated learning back to a local belief. A fresh learning lands on
        # the bottom rung, naming no validator, no promotion actor, no
        # confirmation instant, and no supersession lineage.
        "{}",
        0,
        0,
        learning.created_at,
        None,
        LearningStage.MEMORY,
        "",
        None,
        # The Gauntlet's audit trail (M4-B2): a fresh row has never been
        # validated, so blank/empty is the honest value for all three.
        "",
        "[]",
        "",
        "",
        None,
        None,
    )


async def test_store_dedupes_on_50pct_trigger_key_overlap_and_bumps_hit_count(
    store: PgLearningStore, conn: FakeConnection
) -> None:
    conn.queue_fetch(
        [
            {
                "id": 7,
                "trigger_keys": ["foo", "baz"],
                "works_when": [],
                "avoid_in": [],
                "confidence": None,
                "evidence_run_ids": [],
                "evaluation_ids": [],
            }
        ]
    )
    conn.queue_execute()

    learning = make_learning(trigger_keys=["foo", "qux"])  # 1/2 = 50% overlap
    new_id = await store.store(learning)

    assert new_id == 7
    assert len(conn.calls) == 3
    # M4-B3: the dedup consolidates — the merged applicability/evidence are
    # written back before the hit_count bump (unions of empty stay empty here).
    merge_call, bump_call = conn.calls[1], conn.calls[2]
    assert merge_call.method == "execute"
    assert "UPDATE learnings SET works_when" in merge_call.query
    assert bump_call.method == "execute"
    assert bump_call.query == "UPDATE learnings SET hit_count = hit_count + 1 WHERE id = $1"
    assert bump_call.args == (7,)


async def test_store_dedup_merges_the_resolved_ambient_run_id(
    store: PgLearningStore, conn: FakeConnection
) -> None:
    conn.queue_fetch(
        [
            {
                "id": 7,
                "trigger_keys": ["foo", "baz"],
                "works_when": [],
                "avoid_in": [],
                "confidence": None,
                "evidence_run_ids": ["run-old"],
                "evaluation_ids": [],
            }
        ]
    )
    conn.queue_execute()

    # The caller names no ids; the execution is ambient (`bind_execution_context`).
    # The dedup merge must fold in the *resolved* provenance — a merge fed the
    # original blank-ID learning would drop the current execution from the
    # surviving row's evidence, losing exactly what consolidation retains.
    learning = make_learning(trigger_keys=["foo", "qux"])  # 1/2 = 50% overlap
    with bind_execution_context(run_id="run-ambient"):
        new_id = await store.store(learning)

    assert new_id == 7
    merge_call = conn.calls[1]
    assert merge_call.method == "execute"
    assert "UPDATE learnings SET works_when" in merge_call.query
    assert json.loads(merge_call.args[3]) == ["run-old", "run-ambient"]


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
    # Position derived from the query's own column list, not hardcoded: this
    # assertion silently moved onto source_query when the insert gained it
    # (#122), which is the failure mode of asserting on argument tuples.
    columns = insert_call.query.split("(", 1)[1].split(")", 1)[0]
    position = [c.strip() for c in columns.split(",")].index("agent_id")

    assert insert_call.args[position] == ""


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
    # $1 is org_id (always bound); agent_id follows the optional scope axes.
    # The agent clause keeps the widening both SQL twins shipped: the empty
    # agent is the org-wide shared pool an agent-scoped read still sees.
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
    # M4-B3: the same statement re-measures confidence from the counters.
    assert "confidence = (success_after_use + $3::int)::float" in call.query
    assert "AND org_id = $2" in call.query
    assert call.args == ([5], "", 1)


async def test_mark_outcome_failure_increments_failure_counter(
    store: PgLearningStore, conn: FakeConnection
) -> None:
    conn.queue_execute()

    await store.mark_outcome([5], success=False)

    call = conn.calls[0]
    assert "failure_after_use = failure_after_use + 1" in call.query
    assert "confidence = (success_after_use + $3::int)::float" in call.query
    assert "AND org_id = $2" in call.query
    assert call.args == ([5], "", 0)


async def test_mark_outcome_is_noop_for_empty_list(
    store: PgLearningStore, conn: FakeConnection
) -> None:
    await store.mark_outcome([], success=True)

    assert conn.calls == []


# --------------------------------------------------------------------------
# check_auto_promotions()
# --------------------------------------------------------------------------


def _promotable_row(**overrides: Any) -> dict[str, Any]:
    """A candidate row that carries the M4-B3 evidence promotion requires."""
    row: dict[str, Any] = {
        "id": 1,
        "category": "c",
        "trigger_keys": ["foo"],
        "learning": "l",
        "tool_name": "t",
        "agent_id": None,
        "user_id": None,
        "scope": "agent",
        "hit_count": 5,
        "status": "active",
        "rca_category": None,
        "rca_prevention": "",
        "success_after_use": 2,
        "failure_after_use": 0,
        "run_id": "run-1",
        "node_run_id": None,
        "attempt_id": None,
        "org_id": "",
        "team_id": "",
        "source_query": "",
        "epistemic_type": "observed",
        "works_when": [],
        "avoid_in": [],
        "confidence": 1.0,
        "evidence_run_ids": ["run-1"],
        "evaluation_ids": [],
    }
    row.update(overrides)
    return row


async def test_check_auto_promotions_promotes_rows_above_threshold(
    store: PgLearningStore, conn: FakeConnection
) -> None:
    conn.queue_fetch([_promotable_row()])
    # The claim UPDATE runs as fetch ... RETURNING, so the fake must queue the
    # rows the claim won; an empty result means the caller lost the race.
    conn.queue_fetch([{"id": 1}])

    results = await store.check_auto_promotions(threshold=5)

    select_call, claim_call = conn.calls[0], conn.calls[1]
    assert select_call.method == "fetch"
    assert "hit_count >= $1" in select_call.query
    assert "AND org_id = $2" in select_call.query
    assert claim_call.method == "fetch"
    assert "UPDATE learnings SET status = 'promoted'" in claim_call.query
    # Atomic claim: only rows still `active` flip, and RETURNING — not the
    # candidate list — decides what this caller reports as promoted.
    assert "AND status = 'active'" in claim_call.query
    assert "RETURNING id" in claim_call.query
    assert claim_call.args == ([1],)
    assert len(results) == 1
    assert results[0].status == "promoted"


async def test_check_auto_promotions_loses_race_for_already_claimed_row(
    store: PgLearningStore, conn: FakeConnection
) -> None:
    """A row another worker flipped to `promoted` first is not reported here."""
    conn.queue_fetch([_promotable_row()])
    conn.queue_fetch([])  # RETURNING comes back empty: the claim was lost.

    results = await store.check_auto_promotions(threshold=5)

    assert results == []


async def test_check_auto_promotions_leaves_unevidenced_rows_active(
    store: PgLearningStore, conn: FakeConnection
) -> None:
    """M4-B3: without a source Run/evaluation id and measured confidence,
    a candidate is not promoted and no UPDATE is even issued."""
    conn.queue_fetch([_promotable_row(run_id=None, confidence=None, evidence_run_ids=[])])

    results = await store.check_auto_promotions(threshold=5)

    assert results == []
    assert [call.method for call in conn.calls] == ["fetch"]


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


# --- the #121 ineffective read and anti-pattern reclassification ------------


async def test_list_ineffective_applies_the_ineffective_predicate_in_sql(
    store: PgLearningStore, conn: FakeConnection
) -> None:
    conn.queue_fetch(
        [
            {
                "id": 5,
                "category": "tool",
                "trigger_keys": ["force-push"],
                "learning": "force-pushing over the protected branch",
                "tool_name": "git",
                "org_id": "org-1",
                "success_after_use": 1,
                "failure_after_use": 4,
                "epistemic_type": "empirical",
                "applicability": '{"task_types": ["deploy"]}',
            }
        ]
    )

    [learning] = await store.list_ineffective(min_uses=3)

    # The same predicate the in-memory store and the SQLite twin apply: enough
    # recorded outcomes, and strictly more failures than successes. A backend
    # that answered a different question would be a different store (#121).
    [call] = conn.calls
    assert "success_after_use + failure_after_use >= $1" in call.query
    assert "failure_after_use > success_after_use" in call.query
    assert call.args == (3,)

    assert learning.id == 5
    assert learning.epistemic_type is EpistemicType.EMPIRICAL
    assert learning.applicability == {"task_types": ["deploy"]}


async def test_mark_anti_pattern_writes_the_reclassification_scoped_to_org(
    store: PgLearningStore, conn: FakeConnection
) -> None:
    conn.queue_fetchrow({"id": 5})

    assert await store.mark_anti_pattern(5, 0.6, org_id="org-1") is True

    [call] = conn.calls
    assert call.method == "fetchrow"
    assert "epistemic_type = 'anti_pattern'" in call.query
    assert "GREATEST(confidence, $2)" in call.query
    assert "WHERE id = $1 AND org_id = $3" in call.query
    assert call.args == (5, 0.6, "org-1")


async def test_mark_anti_pattern_reports_a_miss_when_the_org_hides_the_row(
    store: PgLearningStore, conn: FakeConnection
) -> None:
    conn.queue_fetchrow(None)

    assert await store.mark_anti_pattern(999, 0.6, org_id="org-1") is False


def test_applicability_decodes_from_every_shape_a_pool_can_hand_back() -> None:
    """The column is JSONB: asyncpg's default codec hands back `str`, a pool
    that registered its own JSON codec hands back `dict` (the same store class
    runs against both — `maistro.persistence._register_json_codecs` is exactly
    such a pool), and a row from before migration 052 may hold anything.
    A malformed column costs that column, never the read."""
    from maistro.persistence.pg_learnings import _load_applicability

    assert _load_applicability(None) == {}
    assert _load_applicability({"task_types": ["deploy"]}) == {"task_types": ["deploy"]}
    assert _load_applicability('{"task_types": ["deploy"]}') == {"task_types": ["deploy"]}
    assert _load_applicability("not json at all") == {}
    assert _load_applicability('["not", "a", "dict"]') == {}
    assert _load_applicability(42) == {}


# --------------------------------------------------------------------------
# real-PostgreSQL leg: the #121 capture sweep's read and write
#
# The fakes above pin the SQL strings; only a server proves they run. A typo
# in `list_ineffective`'s two-column predicate or `mark_anti_pattern`'s
# GREATEST lift would fail every production capture sweep while the
# fake-verified strings stayed green, so this leg binds them against the
# migrated chain — same contract as the similarity legs below.
# --------------------------------------------------------------------------


@requires_postgres
async def test_the_ineffective_read_and_the_anti_pattern_write_bind_against_a_real_server(
    pg_pool: Any,
) -> None:
    store = PgLearningStore(pg_pool, exposure_mode=MemoryExposureMode.AGENT_MANAGED)
    org = "org-anti-real"

    chronic = await store.store(
        make_learning(
            learning="force-pushing over the protected branch",
            trigger_keys=["force-push"],
            org_id=org,
            success_after_use=1,
            failure_after_use=4,
        )
    )
    healthy = await store.store(
        make_learning(
            learning="snapshot before deploying",
            trigger_keys=["snapshot"],
            org_id=org,
            success_after_use=4,
            failure_after_use=1,
        )
    )

    assert [lr.id for lr in await store.list_ineffective(min_uses=3)] == [chronic]

    # The org binds the write, as it binds every scoped write on this store:
    # an id whose row lives under another scope updates nothing.
    assert await store.mark_anti_pattern(healthy, 0.6, org_id="") is False

    assert await store.mark_anti_pattern(chronic, 0.6, org_id=org) is True
    rows = {lr.id: lr for lr in await store.list_all(org)}
    assert rows[chronic].epistemic_type is EpistemicType.ANTI_PATTERN
    assert rows[chronic].confidence >= 0.6
    assert rows[healthy].epistemic_type is EpistemicType.EMPIRICAL


# --- trigger_keys decoding -------------------------------------------------


def test_trigger_keys_decode_from_every_shape_a_pool_can_hand_back() -> None:
    """The column is JSONB and asyncpg's codec for it is `str` both ways.

    So the decoder has to handle the text this store writes *and* the list a
    pool that registered its own JSON codec would hand back — the same store
    class runs against both, and `maistro.persistence._register_json_codecs`
    is exactly such a pool. Reading a text row with `list(...)` split the JSON
    into single characters, which is why this is a function with a test rather
    than a call site.
    """
    from maistro.persistence.pg_learnings import _dump_keys, _load_keys

    assert _load_keys(_dump_keys(["timeout", "retry"])) == ["timeout", "retry"]
    assert _load_keys(["timeout", "retry"]) == ["timeout", "retry"]
    assert _load_keys(b'["timeout"]') == ["timeout"]
    assert _load_keys([1, 2]) == ["1", "2"]


def test_a_malformed_trigger_keys_row_costs_that_row_and_no_others() -> None:
    """Returning `[]` rather than raising is the decision under test.

    A learning whose keys cannot be read is one learning without keys; raising
    would fail every query that happened to touch it, which turns one bad row
    into an outage of the whole store.
    """
    from maistro.persistence.pg_learnings import _load_keys

    assert _load_keys(None) == []
    assert _load_keys("not json at all") == []
    assert _load_keys('{"not": "an array"}') == []
    assert _load_keys(object()) == []


# --------------------------------------------------------------------------
# real-PostgreSQL legs: the similarity query's scope axes (#1156)
#
# The fakes above pin the SQL strings; only a real server proves that the
# vector cast, the `<=>` ordering and the scope predicate resolve together.
# The migrations suite (tests/migrations/test_memory_embeddings.py) drives
# this method's org and agent axes, but no covered producer ever passed
# `team_id` or `user_id` — the exact axes #1156 makes exact — so the
# diff-coverage gate scored the team/user branches of the changed query as
# untested code. These legs close that: every arc out of the changed
# conditionals runs against a real pgvector column, with out-of-scope rows
# deliberately the *better* vector match so a missing filter is visible in
# the result set rather than hidden by the ranking.
# --------------------------------------------------------------------------


def _e1() -> list[float]:
    """The unit vector along axis 0; its negation is the opposite direction."""
    return [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)


def _hit_texts(hits: list[Learning]) -> list[str]:
    return sorted(hit.learning for hit in hits)


@requires_postgres
async def test_find_similar_scope_axes_bind_exactly_against_a_real_server(
    pg_pool: Any,
) -> None:
    store = PgLearningStore(pg_pool, exposure_mode=MemoryExposureMode.AGENT_MANAGED)
    org = "org-embed-scope"
    vector = _e1()
    rows = [
        make_learning(
            learning="in every scope",
            trigger_keys=["k-a"],
            org_id=org,
            team_id="team-red",
            user_id="u1",
            agent_id="scribe",
        ),
        make_learning(
            learning="other team",
            trigger_keys=["k-b"],
            org_id=org,
            team_id="team-blue",
            user_id="u1",
            agent_id="scribe",
        ),
        make_learning(
            learning="other user",
            trigger_keys=["k-c"],
            org_id=org,
            team_id="team-red",
            user_id="u2",
            agent_id="scribe",
        ),
        make_learning(
            learning="other agent",
            trigger_keys=["k-d"],
            org_id=org,
            team_id="team-red",
            user_id="u1",
            agent_id="wright",
        ),
        make_learning(
            learning="shared pool",
            trigger_keys=["k-e"],
            org_id=org,
            team_id="team-red",
            user_id="u1",
            agent_id="",
        ),
        make_learning(
            learning="other org",
            trigger_keys=["k-f"],
            org_id="org-elsewhere",
            team_id="team-red",
            user_id="u1",
            agent_id="scribe",
        ),
    ]
    for learning in rows:
        learning_id = await store.store(learning)
        await store.set_embedding(learning_id, vector)
    # Same team/user/agent as `in every scope`, but never embedded: the
    # `embedding IS NOT NULL` predicate must keep it out of every result.
    await store.store(
        make_learning(
            learning="never embedded",
            trigger_keys=["k-g"],
            org_id=org,
            team_id="team-red",
            user_id="u1",
            agent_id="scribe",
        )
    )

    assert _hit_texts(await store.find_similar(vector, org_id=org, team_id="team-red")) == [
        "in every scope",
        "other agent",
        "other user",
        "shared pool",
    ]
    assert _hit_texts(await store.find_similar(vector, org_id=org, user_id="u1")) == [
        "in every scope",
        "other agent",
        "other team",
        "shared pool",
    ]
    # `agent_id` stays the one widening axis: an agent-scoped read still sees
    # the org shared pool (the same rule the SQL twins and the memory store
    # share via `learning_scope.AGENT_EMPTY_WIDENS`).
    assert _hit_texts(await store.find_similar(vector, org_id=org, agent_id="scribe")) == [
        "in every scope",
        "other team",
        "other user",
        "shared pool",
    ]
    assert _hit_texts(
        await store.find_similar(
            vector, org_id=org, team_id="team-red", user_id="u1", agent_id="scribe"
        )
    ) == ["in every scope", "shared pool"]
    assert _hit_texts(await store.find_similar(vector, org_id=org)) == [
        "in every scope",
        "other agent",
        "other team",
        "other user",
        "shared pool",
    ]
    assert _hit_texts(await store.find_similar(vector, org_id="org-elsewhere")) == [
        "other org",
    ]


@requires_postgres
async def test_find_similar_orders_by_cosine_distance_nearest_first(
    pg_pool: Any,
) -> None:
    store = PgLearningStore(pg_pool, exposure_mode=MemoryExposureMode.AGENT_MANAGED)
    org = "org-embed-rank"
    far = await store.store(make_learning(learning="far", trigger_keys=["k-rank-far"], org_id=org))
    near = await store.store(
        make_learning(learning="near", trigger_keys=["k-rank-near"], org_id=org)
    )
    query = _e1()
    await store.set_embedding(far, [-1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1))
    await store.set_embedding(near, query)

    hits = await store.find_similar(query, org_id=org)

    assert [hit.learning for hit in hits] == ["near", "far"]


@requires_postgres
async def test_find_similar_refuses_a_width_the_column_cannot_hold(
    pg_pool: Any,
) -> None:
    store = PgLearningStore(pg_pool, exposure_mode=MemoryExposureMode.AGENT_MANAGED)

    with pytest.raises(ValueError, match=f"vector\\({EMBEDDING_DIMENSIONS}\\)"):
        await store.find_similar([0.1, 0.2], org_id="org-x")


@requires_postgres
async def test_set_embedding_refuses_a_width_the_column_cannot_hold(
    pg_pool: Any,
) -> None:
    store = PgLearningStore(pg_pool, exposure_mode=MemoryExposureMode.AGENT_MANAGED)
    learning_id = await store.store(make_learning())

    with pytest.raises(ValueError, match=f"vector\\({EMBEDDING_DIMENSIONS}\\)"):
        await store.set_embedding(learning_id, [0.1, 0.2])


@requires_postgres
async def test_text_of_reads_the_text_that_actually_persisted(pg_pool: Any) -> None:
    """`store` deduplicates, so a caller embedding after a write must read the
    surviving row — provenance for the vector, per `DurableHybridLearningStore`."""
    store = PgLearningStore(pg_pool, exposure_mode=MemoryExposureMode.AGENT_MANAGED)
    learning_id = await store.store(make_learning(learning="surviving text"))

    assert await store.text_of(learning_id) == "surviving text"
    assert await store.text_of(10**9) == ""
