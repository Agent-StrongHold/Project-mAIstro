"""Coverage for maistro.persistence.pg_outcomes.PgOutcomeStore (was 0%).

Uses the same FakePool/FakeConnection asyncpg test double as
test_pg_learnings.py, recording exact SQL + params and returning canned rows.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from maistro.persistence.pg_outcomes import PgOutcomeStore
from maistro.types.memory import Outcome


class FakeRecord(dict):
    """Mimics asyncpg.Record: supports both ``row["x"]`` and ``row.get("x")``."""


class Call:
    def __init__(self, method: str, query: str, args: tuple[Any, ...]) -> None:
        self.method = method
        self.query = query
        self.args = args


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[Call] = []
        self._fetch_results: list[list[FakeRecord]] = []
        self._fetchrow_results: list[FakeRecord | None] = []

    def queue_fetch(self, rows: list[dict[str, Any]]) -> None:
        self._fetch_results.append([FakeRecord(r) for r in rows])

    def queue_fetchrow(self, row: dict[str, Any] | None) -> None:
        self._fetchrow_results.append(FakeRecord(row) if row is not None else None)

    async def fetch(self, query: str, *args: Any) -> list[FakeRecord]:
        self.calls.append(Call("fetch", query, args))
        return self._fetch_results.pop(0) if self._fetch_results else []

    async def fetchrow(self, query: str, *args: Any) -> FakeRecord | None:
        self.calls.append(Call("fetchrow", query, args))
        return self._fetchrow_results.pop(0) if self._fetchrow_results else None

    async def execute(self, query: str, *args: Any) -> str:
        self.calls.append(Call("execute", query, args))
        return "OK"


class FakePool:
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
def store(conn: FakeConnection) -> PgOutcomeStore:
    return PgOutcomeStore(FakePool(conn))


def make_outcome(**overrides: Any) -> Outcome:
    defaults: dict[str, Any] = {
        "request_id": "req-1",
        "task_type": "coding",
        "model_used": "claude-opus",
        "provider": "anthropic",
        "tool_calls": [{"name": "bash"}],
        "success": True,
        "error_type": "",
        "response_time_ms": 1200,
        "org_id": "org-a",
        "team_id": "team-a",
        "user_id": "u1",
        "agent_id": "scribe",
        "input_tokens": 100,
        "output_tokens": 50,
        "charged_microchips": 10,
        "pricing_version": "v1",
    }
    defaults.update(overrides)
    return Outcome(**defaults)


# --------------------------------------------------------------------------
# record()
# --------------------------------------------------------------------------


async def test_record_inserts_with_all_fields_and_returns_id(
    store: PgOutcomeStore, conn: FakeConnection
) -> None:
    conn.queue_fetchrow({"id": 55})

    new_id = await store.record(make_outcome())

    assert new_id == 55
    call = conn.calls[0]
    assert call.method == "fetchrow"
    assert "INSERT INTO outcomes" in call.query
    assert "RETURNING id" in call.query
    # This tuple used to pin `"[{'name': 'bash'}]"` -- the Python repr, with
    # single quotes, which PostgreSQL rejects as JSONB. The test asserted the
    # defect rather than catching it, because a FakeConnection accepts any
    # string. `json.dumps` is what the column actually takes.
    #
    # `org_id` was missing from the INSERT entirely, and is NOT NULL in
    # migration 001 with no DDL default, so every insert was a
    # NotNullViolation -- and a default would only have traded that for a row
    # that silently lost the org scope `ix_outcomes_org_task` keys on (#122).
    assert call.args == (
        "req-1",
        "coding",
        "claude-opus",
        "anthropic",
        '[{"name": "bash"}]',
        True,
        "",
        1200,
        "org-a",
        "team-a",
        "u1",
        "scribe",
        100,
        50,
        10,
        "v1",
    )


async def test_record_defaults_missing_agent_id_to_empty_string(
    store: PgOutcomeStore, conn: FakeConnection
) -> None:
    conn.queue_fetchrow({"id": 1})

    await store.record(make_outcome(agent_id=None))

    call = conn.calls[0]
    assert call.args[11] == ""  # agent_id position (org_id shifted it by one)


async def test_record_returns_zero_when_no_row(store: PgOutcomeStore, conn: FakeConnection) -> None:
    conn.queue_fetchrow(None)

    new_id = await store.record(make_outcome())

    assert new_id == 0


# --------------------------------------------------------------------------
# get_task_completion_rate()
# --------------------------------------------------------------------------


async def test_get_task_completion_rate_filters_by_task_type_when_given(
    store: PgOutcomeStore, conn: FakeConnection
) -> None:
    conn.queue_fetch(
        [
            {"success": True, "model_used": "claude"},
            {"success": False, "model_used": "claude"},
            {"success": True, "model_used": "gpt"},
        ]
    )

    result = await store.get_task_completion_rate(task_type="coding", days=3)

    call = conn.calls[0]
    assert "AND task_type = $2" in call.query
    assert call.args[0] is not None  # cutoff datetime
    assert call.args[1] == "coding"

    assert result["total"] == 3
    assert result["succeeded"] == 2
    assert result["failed"] == 1
    assert result["rate"] == pytest.approx(2 / 3)
    assert result["task_type"] == "coding"
    assert result["days"] == 3
    assert result["by_model"]["claude"] == {"total": 2, "succeeded": 1, "rate": 0.5}
    assert result["by_model"]["gpt"] == {"total": 1, "succeeded": 1, "rate": 1.0}


async def test_get_task_completion_rate_omits_filter_when_task_type_absent(
    store: PgOutcomeStore, conn: FakeConnection
) -> None:
    conn.queue_fetch([])

    result = await store.get_task_completion_rate()

    call = conn.calls[0]
    assert "task_type" not in call.query
    assert len(call.args) == 1
    assert result["task_type"] == "all"
    assert result["total"] == 0
    assert result["rate"] == 0.0
    assert result["by_model"] == {}


async def test_get_task_completion_rate_zero_total_rate_is_zero(
    store: PgOutcomeStore, conn: FakeConnection
) -> None:
    conn.queue_fetch([])

    result = await store.get_task_completion_rate(days=1)

    assert result["rate"] == 0.0
    assert result["failed"] == 0


# --------------------------------------------------------------------------
# get_usage_breakdown()
# --------------------------------------------------------------------------


async def test_get_usage_breakdown_uses_allowed_group_by_column(
    store: PgOutcomeStore, conn: FakeConnection
) -> None:
    conn.queue_fetch(
        [
            {
                "grp": "team-a",
                "input_tokens": 100,
                "output_tokens": 50,
                "total_tokens": 150,
                "total_microchips": 10,
                "request_count": 2,
                "success_count": 1,
                "avg_response_ms": 500.5,
            }
        ]
    )

    results = await store.get_usage_breakdown(group_by="team_id", days=7)

    call = conn.calls[0]
    assert "team_id AS grp" in call.query
    assert "GROUP BY team_id" in call.query
    assert "WHERE created_at >= $1" in call.query
    assert len(call.args) == 1

    assert results == [
        {
            "group": "team-a",
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
            "total_microchips": 10,
            "request_count": 2,
            "success_count": 1,
            "avg_response_ms": 500.5,
        }
    ]


async def test_get_usage_breakdown_falls_back_to_user_id_for_disallowed_column(
    store: PgOutcomeStore, conn: FakeConnection
) -> None:
    conn.queue_fetch([])

    await store.get_usage_breakdown(group_by="DROP TABLE outcomes; --")

    call = conn.calls[0]
    assert "user_id AS grp" in call.query
    assert "GROUP BY user_id" in call.query
    assert "DROP TABLE" not in call.query


async def test_get_usage_breakdown_no_days_filter_when_days_zero(
    store: PgOutcomeStore, conn: FakeConnection
) -> None:
    conn.queue_fetch([])

    await store.get_usage_breakdown(group_by="model_used", days=0)

    call = conn.calls[0]
    assert "WHERE" not in call.query
    assert call.args == ()


async def test_get_usage_breakdown_handles_null_group_and_avg(
    store: PgOutcomeStore, conn: FakeConnection
) -> None:
    conn.queue_fetch(
        [
            {
                "grp": None,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "total_microchips": 0,
                "request_count": 0,
                "success_count": 0,
                "avg_response_ms": None,
            }
        ]
    )

    [result] = await store.get_usage_breakdown(group_by="provider")

    assert result["group"] == "(unknown)"
    assert result["avg_response_ms"] == 0.0


# --------------------------------------------------------------------------
# get_daily_timeseries()
# --------------------------------------------------------------------------


async def test_get_daily_timeseries_with_group_by(
    store: PgOutcomeStore, conn: FakeConnection
) -> None:
    conn.queue_fetch(
        [
            {
                "day": "2026-06-01",
                "grp": "agent-x",
                "input_tokens": 10,
                "output_tokens": 5,
                "total_tokens": 15,
                "total_microchips": 1,
                "request_count": 1,
            }
        ]
    )

    results = await store.get_daily_timeseries(group_by="agent_id", days=5)

    call = conn.calls[0]
    assert "agent_id AS grp" in call.query
    assert "GROUP BY day, agent_id" in call.query
    assert results[0]["date"] == "2026-06-01"
    assert results[0]["group"] == "agent-x"


async def test_get_daily_timeseries_without_group_by(
    store: PgOutcomeStore, conn: FakeConnection
) -> None:
    conn.queue_fetch(
        [
            {
                "day": "2026-06-01",
                "input_tokens": 10,
                "output_tokens": 5,
                "total_tokens": 15,
                "total_microchips": 1,
                "request_count": 1,
            }
        ]
    )

    results = await store.get_daily_timeseries()

    call = conn.calls[0]
    assert "GROUP BY day" in call.query
    assert "grp" not in call.query
    assert results[0]["group"] is None


async def test_get_daily_timeseries_ignores_disallowed_group_by(
    store: PgOutcomeStore, conn: FakeConnection
) -> None:
    conn.queue_fetch([])

    await store.get_daily_timeseries(group_by="not_a_real_column")

    call = conn.calls[0]
    assert "GROUP BY day" in call.query
    assert "not_a_real_column" not in call.query


# --------------------------------------------------------------------------
# get_experience_context()
# --------------------------------------------------------------------------


async def test_get_experience_context_returns_empty_string_when_no_failures(
    store: PgOutcomeStore, conn: FakeConnection
) -> None:
    conn.queue_fetch([])

    result = await store.get_experience_context("coding")

    assert result == ""


async def test_get_experience_context_formats_failure_lines(
    store: PgOutcomeStore, conn: FakeConnection
) -> None:
    conn.queue_fetch(
        [
            {"error_type": "timeout", "model_used": "claude"},
            {"error_type": "rate_limit", "model_used": "gpt"},
        ]
    )

    result = await store.get_experience_context("coding", tool_name="bash", limit=2)

    call = conn.calls[0]
    assert call.query.strip().startswith("SELECT * FROM outcomes")
    assert "success = false" in call.query
    assert call.args[0] == "coding"
    assert call.args[2] == 2

    assert result == ("Recent failures:\n- timeout: model=claude\n- rate_limit: model=gpt")


# --------------------------------------------------------------------------
# list_outcomes()
# --------------------------------------------------------------------------


async def test_list_outcomes_filters_by_task_type_and_appends_limit_placeholder(
    store: PgOutcomeStore, conn: FakeConnection
) -> None:
    conn.queue_fetch([])

    await store.list_outcomes(task_type="coding", days=3, limit=10)

    call = conn.calls[0]
    assert "AND task_type = $2" in call.query
    assert "LIMIT $3" in call.query
    assert call.args[1] == "coding"
    assert call.args[2] == 10


async def test_list_outcomes_without_task_type_uses_limit_placeholder_2(
    store: PgOutcomeStore, conn: FakeConnection
) -> None:
    conn.queue_fetch([])

    await store.list_outcomes(days=3, limit=10)

    call = conn.calls[0]
    assert "task_type" not in call.query
    assert "LIMIT $2" in call.query
    assert call.args[1] == 10


async def test_list_outcomes_maps_rows_to_outcome_dataclasses(
    store: PgOutcomeStore, conn: FakeConnection
) -> None:
    created = datetime(2026, 6, 1, tzinfo=UTC)
    conn.queue_fetch(
        [
            {
                "id": 3,
                "request_id": "req-3",
                "task_type": "coding",
                "model_used": "claude",
                "success": False,
                "error_type": "timeout",
                "response_time_ms": 999,
                "team_id": "team-a",
                "user_id": "u3",
                "agent_id": "",
                "input_tokens": 20,
                "output_tokens": 30,
                "charged_microchips": 5,
                "pricing_version": "v2",
                "created_at": created,
            }
        ]
    )

    [outcome] = await store.list_outcomes()

    assert outcome.id == 3
    assert outcome.request_id == "req-3"
    assert outcome.task_type == "coding"
    assert outcome.model_used == "claude"
    assert outcome.success is False
    assert outcome.error_type == "timeout"
    assert outcome.response_time_ms == 999
    assert outcome.team_id == "team-a"
    assert outcome.user_id == "u3"
    assert outcome.agent_id is None  # "" coerced to None
    assert outcome.input_tokens == 20
    assert outcome.output_tokens == 30
    assert outcome.charged_microchips == 5
    assert outcome.pricing_version == "v2"
    assert outcome.created_at == created
