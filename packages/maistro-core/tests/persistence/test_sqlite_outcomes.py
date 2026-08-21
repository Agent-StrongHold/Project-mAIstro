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
