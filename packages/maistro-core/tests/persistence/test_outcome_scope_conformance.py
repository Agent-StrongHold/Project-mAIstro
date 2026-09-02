"""Two tenants, two projects, both durable backends: a scoped read cannot cross scope (#844).

`SqliteOutcomeStore` accepted `org_id`/`project_id` on every read and bound
them into nothing, so the same call that answered "one tenant's outcomes" on
PostgreSQL answered "every tenant's" on SQLite — and the outcomes are the
evidence path behind prompts and rankings, so the text, the feedback, the
tool-call data and the #64/#709 provenance of one tenant could be presented
as another's.

Parametrized over both durable backends because "the same scope answers the
same way" is the entire claim — authorization strength that differs by backend
silently is the defect (#364). The PG legs skip without `MAISTRO_TEST_PG_DSN`
(CI's postgres job runs them against a real, migrated server).

**Mutation resistance** (#364's definition of done): every test seeds distinct
per-scope markers — `fail-org-a-p1`, `comment-org-b-p2`, `run-org-a-p1`, … —
and asserts the other scopes' markers never appear. Remove or weaken the scope
predicate in either store and the foreign markers arrive; the suite fails. A
test that could survive the predicate's removal would be a test proving
nothing, which is what the markers are for.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from maistro.persistence.pg_outcomes import PgOutcomeStore
from maistro.persistence.sqlite_outcomes import SqliteOutcomeStore
from maistro.types.memory import Outcome

pytestmark = [pytest.mark.contract("behavioral")]

_ORGS = ("org-a", "org-b")
_PROJECTS = ("p1", "p2")


@pytest.fixture(params=["sqlite", "postgres"])
async def outcome_store(request: pytest.FixtureRequest, pg_pool: Any) -> AsyncIterator[Any]:
    """A seeded two-tenant/two-project store, on either durable backend.

    Both backends get the same seed — same markers, same shapes — so a test
    body can assert one thing and be true of both, and drift between them is
    a failure here rather than a silent difference in authorization strength.
    """
    store: Any
    if request.param == "sqlite":
        aiosqlite = pytest.importorskip("aiosqlite")
        conn = await aiosqlite.connect(":memory:")
        store = SqliteOutcomeStore(conn)
        await store.ensure_schema()
        try:
            await _seed(store)
            yield store
        finally:
            await conn.close()
        return
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    store = PgOutcomeStore(pg_pool)
    await _seed(store)
    yield store


def _failure(org: str, project: str) -> Outcome:
    """A failure whose every tenant-bearing field carries the (org, project) marker."""
    tag = f"{org}-{project}"
    return Outcome(
        request_id=f"req-{tag}",
        session_id=f"sess-{tag}",
        task_type="code",
        model_used=f"model-{org}",
        provider="prov",
        tool_calls=[{"name": f"tool-{org}"}],
        success=False,
        error_type=f"fail-{tag}",
        response_time_ms=100,
        org_id=org,
        user_id=f"user-{org}",
        input_tokens=10,
        output_tokens=5,
        project_id=project,
        dag_id=f"dag-{tag}",
        dag_run_id=f"dagrun-{tag}",
        node_id=f"node-{tag}",
        run_id=f"run-{tag}",
        node_run_id=f"noderun-{tag}",
        attempt_id=f"attempt-{tag}",
    )


def _feedback(org: str, project: str) -> Outcome:
    """A thumbs-down carrying the same markers through its feedback text."""
    row = _failure(org, project)
    row.success = True
    row.error_type = ""
    row.thumb = "down"
    row.thumb_comment = f"comment-{org}-{project}"
    return row


async def _seed(store: Any) -> None:
    for org in _ORGS:
        for project in _PROJECTS:
            await store.record(_failure(org, project))
            await store.record(_feedback(org, project))


def _text_of(outcome: Outcome) -> str:
    """Every string field a scoped read could leak through, joined for substring checks."""
    fields = (
        outcome.request_id,
        outcome.session_id,
        outcome.error_type,
        outcome.thumb_comment,
        outcome.dag_id,
        outcome.dag_run_id,
        outcome.node_id,
        outcome.run_id,
        outcome.node_run_id,
        outcome.attempt_id,
        outcome.model_used,
        outcome.user_id,
        outcome.provider,
    )
    return " ".join(fields)


class TestAScopedReadCannotCrossScope:
    async def test_list_outcomes_returns_only_the_named_orgs_rows(self, outcome_store: Any) -> None:
        found = await outcome_store.list_outcomes(org_id="org-a")

        assert len(found) == 4, "two projects x (one failure, one feedback)"
        assert all(o.org_id == "org-a" for o in found)
        assert all("org-b" not in _text_of(o) for o in found)

    async def test_list_outcomes_returns_only_the_named_orgs_projects_rows(
        self, outcome_store: Any
    ) -> None:
        found = await outcome_store.list_outcomes(org_id="org-a")

        # Both projects of the named org are in scope; the marker check is the
        # other direction — a project axis narrows further (below), it never
        # admits another org.
        assert {o.project_id for o in found} == {"p1", "p2"}

    async def test_the_experience_narrative_composes_org_and_project_with_and(
        self, outcome_store: Any
    ) -> None:
        """The prompt-injected text: one tenant, one project, nothing else.

        `fail-org-a-p2` is the same org but the other project; `fail-org-b-p1`
        is the other org in the same project. A scope predicate that filters
        after the fetch, or on one axis only, surfaces one of them.
        """
        narrative = await outcome_store.get_experience_context(
            "code", org_id="org-a", project_id="p1"
        )

        assert "fail-org-a-p1" in narrative
        assert "fail-org-a-p2" not in narrative
        assert "fail-org-b-p1" not in narrative
        assert "fail-org-b-p2" not in narrative

    async def test_cross_scope_feedback_is_not_returned(self, outcome_store: Any) -> None:
        found = await outcome_store.list_thumbs(org_id="org-b")

        # Sorted, not positional: both thumbs land in the same clock tick, so
        # their relative order under `created_at DESC` is an unspecified tie
        # and the claim under test is which scope's feedback came back.
        comments = sorted(o.thumb_comment for o in found)
        assert comments == ["comment-org-b-p1", "comment-org-b-p2"]
        assert all("org-a" not in c for c in comments)

    async def test_cross_scope_tool_call_data_is_not_returned(self, outcome_store: Any) -> None:
        found = await outcome_store.list_outcomes(org_id="org-a")

        for outcome in found:
            assert all("org-b" not in str(call.get("name", "")) for call in outcome.tool_calls)

    async def test_provenance_stays_inside_the_authorized_scope(self, outcome_store: Any) -> None:
        """The #64/#709 fields name the execution that produced an outcome, so
        they are as sensitive as the outcome text itself: a Run id is an
        address into another tenant's execution history."""
        found = await outcome_store.list_outcomes(org_id="org-a")

        for outcome in found:
            assert outcome.run_id.startswith("run-org-a")
            assert outcome.node_run_id.startswith("noderun-org-a")
            assert outcome.attempt_id.startswith("attempt-org-a")
            assert outcome.session_id.startswith("sess-org-a")

    async def test_the_aggregates_cannot_cross_the_org_boundary(self, outcome_store: Any) -> None:
        rate = await outcome_store.get_task_completion_rate(org_id="org-a")
        usage = await outcome_store.get_usage_breakdown(group_by="user_id", org_id="org-a")
        series = await outcome_store.get_daily_timeseries(group_by="user_id", org_id="org-a")

        assert rate["total"] == 4
        assert rate["succeeded"] == 2
        assert set(rate["by_model"]) == {"model-org-a"}
        assert [row["group"] for row in usage] == ["user-org-a"]
        assert usage[0]["request_count"] == 4
        assert [row["group"] for row in series] == ["user-org-a"]
        assert series[0]["request_count"] == 4

    async def test_the_usage_breakdown_stays_scoped_without_a_time_window(
        self, outcome_store: Any
    ) -> None:
        """`days=0` means "all time", not "all orgs" — the scope predicate has
        to open the WHERE clause when there is no cutoff to extend."""
        usage = await outcome_store.get_usage_breakdown(group_by="user_id", org_id="org-a", days=0)

        assert [row["group"] for row in usage] == ["user-org-a"]


class TestTheCompositionRule:
    """One documented rule, shared by both backends (`outcome_scope`):
    an axis left empty is not filtered, present axes compose with AND, and a
    scope that failed to resolve fails closed rather than widening."""

    async def test_an_unscoped_read_is_the_documented_global_one(self, outcome_store: Any) -> None:
        found = await outcome_store.list_outcomes()

        assert len(found) == 8

    async def test_a_scope_no_row_matches_returns_no_rows_not_every_row(
        self, outcome_store: Any
    ) -> None:
        """No implicit `default` scope: a scope that matches nothing answers
        nothing, rather than falling back to unfiltered visibility."""
        assert await outcome_store.list_outcomes(org_id="org-nobody") == []
        assert await outcome_store.list_thumbs(org_id="org-nobody") == []
        narrative = await outcome_store.get_experience_context("code", org_id="org-nobody")
        assert narrative == ""

    @pytest.mark.parametrize(
        ("read", "scope_kwargs"),
        [
            ("get_task_completion_rate", {"org_id": None}),
            ("get_usage_breakdown", {"org_id": None}),
            ("get_daily_timeseries", {"org_id": None}),
            ("get_experience_context", {"org_id": None}),
            ("get_experience_context", {"project_id": None}),
            ("list_outcomes", {"org_id": None}),
            ("list_thumbs", {"org_id": None}),
        ],
    )
    async def test_an_ambiguous_scope_fails_closed(
        self, outcome_store: Any, read: str, scope_kwargs: dict[str, None]
    ) -> None:
        """`None` is a scope that failed to resolve, not one deliberately left
        unscoped; it used to fall through a truthiness check and read
        globally on both backends."""
        method = getattr(outcome_store, read)
        args = ("code",) if read == "get_experience_context" else ()
        with pytest.raises(ValueError, match="ambiguous"):
            await method(*args, **scope_kwargs)


class TestTheScopedPatternIsIndexBacked:
    """Query plans have to support the scoped access pattern, not just return
    the right rows: an unindexed scope predicate makes every scoped read a
    full scan, which is how a security fix becomes a production outage."""

    async def test_the_scoped_read_walks_an_index(self, outcome_store: Any) -> None:
        if isinstance(outcome_store, SqliteOutcomeStore):
            cursor = await outcome_store._conn.execute(
                "EXPLAIN QUERY PLAN SELECT * FROM outcomes "
                "WHERE org_id = ? AND project_id = ? AND task_type = ? AND created_at >= ?",
                ("org-a", "p1", "code", "2000-01-01"),
            )
            plan = " ".join(str(row[3]) for row in await cursor.fetchall())
            assert "SCAN" not in plan
            assert "idx_outcomes_scope_task_time" in plan
            return

        pool = outcome_store._pool
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT indexdef FROM pg_indexes WHERE tablename = 'outcomes' AND indexname = $1",
                "ix_outcomes_scope_task_time",
            )
        assert row is not None, "migration 010's scoped access composite is missing"
        for column in ("org_id", "project_id", "task_type", "created_at"):
            assert column in row["indexdef"]
