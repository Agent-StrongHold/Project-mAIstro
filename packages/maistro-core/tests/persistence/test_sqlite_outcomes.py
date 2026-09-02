"""Coverage for maistro.persistence.sqlite_outcomes.SqliteOutcomeStore against a real
in-memory sqlite3 DB (via aiosqlite)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import aiosqlite
import pytest

from maistro.persistence.sqlite_outcomes import SqliteOutcomeStore
from maistro.types.memory import Outcome


@pytest.fixture
async def store() -> AsyncIterator[SqliteOutcomeStore]:
    conn = await aiosqlite.connect(":memory:")
    s = SqliteOutcomeStore(conn)
    await s.ensure_schema()
    yield s
    await conn.close()


def make_outcome(**kwargs: object) -> Outcome:
    defaults: dict[str, object] = {
        "request_id": "r1",
        "task_type": "chat",
        "model_used": "gpt-4",
        "provider": "openai",
        "success": True,
        "user_id": "u1",
        "input_tokens": 10,
        "output_tokens": 5,
        "charged_microchips": 1,
    }
    defaults.update(kwargs)
    return Outcome(**defaults)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_record_returns_positive_id(store: SqliteOutcomeStore) -> None:
    oid = await store.record(make_outcome())
    assert oid == 1


@pytest.mark.asyncio
async def test_record_and_list_outcomes_roundtrip(store: SqliteOutcomeStore) -> None:
    await store.record(make_outcome(request_id="r1"))
    outcomes = await store.list_outcomes()
    assert len(outcomes) == 1
    assert outcomes[0].request_id == "r1"
    assert outcomes[0].success is True
    assert outcomes[0].agent_id is None


@pytest.mark.asyncio
async def test_list_outcomes_filters_by_task_type(store: SqliteOutcomeStore) -> None:
    await store.record(make_outcome(task_type="chat"))
    await store.record(make_outcome(task_type="code"))
    outcomes = await store.list_outcomes(task_type="code")
    assert len(outcomes) == 1
    assert outcomes[0].task_type == "code"


@pytest.mark.asyncio
async def test_list_outcomes_respects_limit(store: SqliteOutcomeStore) -> None:
    for i in range(5):
        await store.record(make_outcome(request_id=str(i)))
    outcomes = await store.list_outcomes(limit=2)
    assert len(outcomes) == 2


@pytest.mark.asyncio
async def test_get_task_completion_rate_computes_totals_and_by_model(
    store: SqliteOutcomeStore,
) -> None:
    await store.record(make_outcome(task_type="chat", model_used="gpt-4", success=True))
    await store.record(make_outcome(task_type="chat", model_used="gpt-4", success=False))
    await store.record(make_outcome(task_type="chat", model_used="claude", success=True))
    result = await store.get_task_completion_rate(task_type="chat")
    assert result["total"] == 3
    assert result["succeeded"] == 2
    assert result["failed"] == 1
    assert result["rate"] == pytest.approx(2 / 3)
    assert result["by_model"]["gpt-4"] == {"total": 2, "succeeded": 1, "rate": 0.5}
    assert result["by_model"]["claude"] == {"total": 1, "succeeded": 1, "rate": 1.0}
    assert result["task_type"] == "chat"


@pytest.mark.asyncio
async def test_get_task_completion_rate_no_rows_returns_zero_rate(
    store: SqliteOutcomeStore,
) -> None:
    result = await store.get_task_completion_rate(task_type="missing")
    assert result == {
        "total": 0,
        "succeeded": 0,
        "failed": 0,
        "rate": 0.0,
        "by_model": {},
        "days": 7,
        "task_type": "missing",
    }


@pytest.mark.asyncio
async def test_get_task_completion_rate_no_task_type_filter_labels_all(
    store: SqliteOutcomeStore,
) -> None:
    result = await store.get_task_completion_rate()
    assert result["task_type"] == "all"


@pytest.mark.asyncio
async def test_get_usage_breakdown_groups_by_user_id(store: SqliteOutcomeStore) -> None:
    await store.record(make_outcome(user_id="u1", input_tokens=10, output_tokens=5))
    await store.record(make_outcome(user_id="u1", input_tokens=20, output_tokens=0))
    await store.record(make_outcome(user_id="u2", input_tokens=1, output_tokens=1))
    rows = await store.get_usage_breakdown(group_by="user_id")
    by_group = {r["group"]: r for r in rows}
    assert by_group["u1"]["total_tokens"] == 35
    assert by_group["u1"]["request_count"] == 2
    assert by_group["u2"]["total_tokens"] == 2


@pytest.mark.asyncio
async def test_get_usage_breakdown_invalid_group_by_falls_back_to_user_id(
    store: SqliteOutcomeStore,
) -> None:
    await store.record(make_outcome(user_id="u1"))
    rows = await store.get_usage_breakdown(group_by="not_a_real_column")
    assert rows[0]["group"] == "u1"


@pytest.mark.asyncio
async def test_get_usage_breakdown_empty_group_defaults_to_unknown(
    store: SqliteOutcomeStore,
) -> None:
    await store.record(make_outcome(user_id=""))
    rows = await store.get_usage_breakdown(group_by="user_id")
    assert rows[0]["group"] == "(unknown)"


@pytest.mark.asyncio
async def test_get_usage_breakdown_days_zero_skips_date_filter(
    store: SqliteOutcomeStore,
) -> None:
    old = make_outcome(user_id="u1", created_at=datetime.now(UTC) - timedelta(days=999))
    await store.record(old)
    rows = await store.get_usage_breakdown(group_by="user_id", days=0)
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_get_daily_timeseries_with_group(store: SqliteOutcomeStore) -> None:
    await store.record(make_outcome(user_id="u1", input_tokens=10, output_tokens=5))
    rows = await store.get_daily_timeseries(group_by="user_id")
    assert len(rows) == 1
    assert rows[0]["group"] == "u1"
    assert rows[0]["total_tokens"] == 15


@pytest.mark.asyncio
async def test_get_daily_timeseries_invalid_group_omits_grouping(
    store: SqliteOutcomeStore,
) -> None:
    await store.record(make_outcome(user_id="u1"))
    rows = await store.get_daily_timeseries(group_by="not_a_real_column")
    assert rows[0]["group"] is None


@pytest.mark.asyncio
async def test_get_daily_timeseries_empty_group_by_omits_grouping(
    store: SqliteOutcomeStore,
) -> None:
    await store.record(make_outcome(user_id="u1"))
    rows = await store.get_daily_timeseries()
    assert rows[0]["group"] is None


@pytest.mark.asyncio
async def test_get_experience_context_no_failures_returns_empty_string(
    store: SqliteOutcomeStore,
) -> None:
    await store.record(make_outcome(task_type="chat", success=True))
    ctx = await store.get_experience_context("chat")
    assert ctx == ""


@pytest.mark.asyncio
async def test_get_experience_context_formats_recent_failures(
    store: SqliteOutcomeStore,
) -> None:
    await store.record(
        make_outcome(task_type="chat", success=False, error_type="timeout", model_used="gpt-4")
    )
    ctx = await store.get_experience_context("chat")
    assert ctx == "Recent failures:\n- timeout: model=gpt-4"


@pytest.mark.asyncio
async def test_get_experience_context_respects_limit(store: SqliteOutcomeStore) -> None:
    for i in range(3):
        await store.record(make_outcome(task_type="chat", success=False, error_type=f"err{i}"))
    ctx = await store.get_experience_context("chat", limit=2)
    assert ctx.count("\n") == 2


# ---------------------------------------------------------------------------
# Scope (#844): every read took org_id/project_id and bound them into nothing,
# so a SQLite-backed deployment answered a scoped read with every tenant's
# rows while the PostgreSQL twin answered with one tenant's.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_outcomes_scopes_by_org(store: SqliteOutcomeStore) -> None:
    await store.record(make_outcome(org_id="org-a", error_type="from-a"))
    await store.record(make_outcome(org_id="org-b", error_type="from-b"))

    found = await store.list_outcomes(org_id="org-a")

    assert [o.error_type for o in found] == ["from-a"]


@pytest.mark.asyncio
async def test_get_task_completion_rate_scopes_by_org(store: SqliteOutcomeStore) -> None:
    await store.record(make_outcome(org_id="org-a", success=False))
    await store.record(make_outcome(org_id="org-a", success=True))
    await store.record(make_outcome(org_id="org-b", success=False, model_used="other"))

    scoped = await store.get_task_completion_rate(org_id="org-a")
    unscoped = await store.get_task_completion_rate()

    assert scoped["total"] == 2
    assert "other" not in scoped["by_model"]
    assert unscoped["total"] == 3, "no org named still means all of them"


@pytest.mark.asyncio
async def test_get_usage_breakdown_scopes_by_org(store: SqliteOutcomeStore) -> None:
    await store.record(make_outcome(org_id="org-a", user_id="ua", input_tokens=10))
    await store.record(make_outcome(org_id="org-b", user_id="ub", input_tokens=99))

    rows = await store.get_usage_breakdown(group_by="user_id", org_id="org-a")

    assert [r["group"] for r in rows] == ["ua"]


@pytest.mark.asyncio
async def test_get_usage_breakdown_scopes_by_org_when_days_zero_opens_the_where(
    store: SqliteOutcomeStore,
) -> None:
    """`days <= 0` means "all time", not "all orgs" — the scope predicate has
    to open the WHERE clause when there is no cutoff to extend."""
    await store.record(make_outcome(org_id="org-a", user_id="ua"))
    await store.record(make_outcome(org_id="org-b", user_id="ub"))

    rows = await store.get_usage_breakdown(group_by="user_id", org_id="org-a", days=0)

    assert [r["group"] for r in rows] == ["ua"]


@pytest.mark.asyncio
async def test_get_daily_timeseries_scopes_by_org(store: SqliteOutcomeStore) -> None:
    await store.record(make_outcome(org_id="org-a", user_id="ua", input_tokens=10))
    await store.record(make_outcome(org_id="org-b", user_id="ub", input_tokens=99))

    rows = await store.get_daily_timeseries(group_by="user_id", org_id="org-a")

    assert [r["group"] for r in rows] == ["ua"]
    assert rows[0]["total_tokens"] == 15


@pytest.mark.asyncio
async def test_get_experience_context_scopes_by_org_and_project(
    store: SqliteOutcomeStore,
) -> None:
    """The sharp end of the defect: this text is injected verbatim into an
    agent's system prompt, so an unscoped read presented one tenant's failure
    as another's experience."""
    await store.record(
        make_outcome(
            task_type="chat", success=False, error_type="from-a-p1", org_id="org-a", project_id="p1"
        )
    )
    await store.record(
        make_outcome(
            task_type="chat", success=False, error_type="from-a-p2", org_id="org-a", project_id="p2"
        )
    )
    await store.record(
        make_outcome(
            task_type="chat", success=False, error_type="from-b-p1", org_id="org-b", project_id="p1"
        )
    )

    org_and_project = await store.get_experience_context("chat", org_id="org-a", project_id="p1")
    org_only = await store.get_experience_context("chat", org_id="org-a")

    assert "from-a-p1" in org_and_project
    assert "from-a-p2" not in org_and_project
    assert "from-b-p1" not in org_and_project
    # Both axes compose with AND: org-a alone sees both its projects.
    assert "from-a-p2" in org_only
    assert "from-b-p1" not in org_only


@pytest.mark.asyncio
async def test_list_thumbs_scopes_by_org(store: SqliteOutcomeStore) -> None:
    await store.record(
        make_outcome(org_id="org-a", thumb="down", thumb_comment="from-a", dag_id="d1")
    )
    await store.record(
        make_outcome(org_id="org-b", thumb="down", thumb_comment="from-b", dag_id="d1")
    )

    found = await store.list_thumbs(dag_id="d1", org_id="org-a")

    assert [o.thumb_comment for o in found] == ["from-a"]


@pytest.mark.asyncio
async def test_the_scope_predicate_is_in_the_query_not_a_post_filter(
    store: SqliteOutcomeStore,
) -> None:
    """A post-filter after a global fetch would spend the LIMIT on other
    tenants' rows: the one org-a row is older than five org-b rows, so
    fetch-then-filter would return nothing and the scoped query returns it."""
    for i in range(5):
        await store.record(make_outcome(org_id="org-b", error_type=f"newer-b-{i}"))
    await store.record(make_outcome(org_id="org-a", error_type="older-a"))

    found = await store.list_outcomes(org_id="org-a", limit=1)

    assert [o.error_type for o in found] == ["older-a"]


@pytest.mark.asyncio
async def test_a_scope_no_row_matches_returns_no_rows_not_every_row(
    store: SqliteOutcomeStore,
) -> None:
    """No implicit `default` scope: a scope that matches nothing returns
    nothing, rather than falling back to unfiltered visibility."""
    await store.record(make_outcome(org_id="org-a"))

    assert await store.list_outcomes(org_id="org-nobody") == []


@pytest.mark.asyncio
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
    store: SqliteOutcomeStore, read: str, scope_kwargs: dict[str, None]
) -> None:
    """`None` is a scope that failed to resolve, not one deliberately left
    unscoped — treating it as `''` would widen visibility exactly when scope
    resolution failed, so the store raises instead of guessing."""
    method = getattr(store, read)
    args = ("chat",) if read == "get_experience_context" else ()
    with pytest.raises(ValueError, match="ambiguous"):
        await method(*args, **scope_kwargs)


@pytest.mark.asyncio
async def test_the_scoped_read_walks_the_scope_index(store: SqliteOutcomeStore) -> None:
    """The composite backing the scoped pattern in production, mirroring
    PostgreSQL's `ix_outcomes_scope_task_time` from migration 010: without it
    every scoped read degrades to a full scan of the outcomes table."""
    cursor = await store._conn.execute(
        "EXPLAIN QUERY PLAN SELECT * FROM outcomes "
        "WHERE org_id = ? AND project_id = ? AND task_type = ? AND created_at >= ?",
        ("org-a", "p1", "chat", "2000-01-01"),
    )
    plan = " ".join(str(row[3]) for row in await cursor.fetchall())

    assert "SCAN" not in plan
    assert "idx_outcomes_scope_task_time" in plan


@pytest.mark.asyncio
async def test_a_legacy_database_gains_the_scope_index(store: SqliteOutcomeStore) -> None:
    """`ensure_schema` runs `CREATE INDEX IF NOT EXISTS`, so the index arrives
    on an existing file rather than only on fresh ones."""
    cursor = await store._conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'outcomes'"
    )
    indexes = [row[0] for row in await cursor.fetchall()]
    assert "idx_outcomes_scope_task_time" in indexes
