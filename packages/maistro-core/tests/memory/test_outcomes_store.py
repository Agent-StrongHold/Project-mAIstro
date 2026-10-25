"""Tests for maistro.memory.outcomes — InMemoryOutcomeStore (ADR-017)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from maistro.memory.outcomes import InMemoryOutcomeStore
from maistro.memory.types import Outcome


def _outcome(**kwargs: object) -> Outcome:
    defaults: dict[str, object] = {}
    defaults.update(kwargs)
    return Outcome(**defaults)  # type: ignore[arg-type]


class TestRecord:
    @pytest.mark.asyncio
    async def test_record_assigns_incrementing_ids(self) -> None:
        store = InMemoryOutcomeStore()
        first_id = await store.record(_outcome())
        second_id = await store.record(_outcome())
        assert first_id == 1
        assert second_id == 2

    @pytest.mark.asyncio
    async def test_record_evicts_oldest_when_at_capacity(self) -> None:
        store = InMemoryOutcomeStore(max_outcomes=2)
        await store.record(_outcome(task_type="first"))
        await store.record(_outcome(task_type="second"))
        await store.record(_outcome(task_type="third"))
        outcomes = await store.list_outcomes(days=9999, limit=10)
        assert [o.task_type for o in outcomes] == ["second", "third"]


class TestGetTaskCompletionRate:
    @pytest.mark.asyncio
    async def test_empty_store_returns_zero_rate(self) -> None:
        store = InMemoryOutcomeStore()
        result = await store.get_task_completion_rate()
        assert result["total"] == 0
        assert result["rate"] == 0.0
        assert result["task_type"] == "all"

    @pytest.mark.asyncio
    async def test_filters_by_task_type_and_aggregates_by_model(self) -> None:
        store = InMemoryOutcomeStore()
        await store.record(_outcome(task_type="code", model_used="gpt", success=True))
        await store.record(_outcome(task_type="code", model_used="gpt", success=False))
        await store.record(_outcome(task_type="chat", model_used="claude", success=True))

        result = await store.get_task_completion_rate(task_type="code")
        assert result["total"] == 2
        assert result["succeeded"] == 1
        assert result["failed"] == 1
        assert result["task_type"] == "code"
        assert result["by_model"]["gpt"]["rate"] == 0.5

    @pytest.mark.asyncio
    async def test_excludes_outcomes_outside_cutoff_window(self) -> None:
        store = InMemoryOutcomeStore()
        old = _outcome(created_at=datetime.now(UTC) - timedelta(days=10))
        await store.record(old)
        result = await store.get_task_completion_rate(days=7)
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_org_id_filters_results(self) -> None:
        store = InMemoryOutcomeStore()
        await store.record(_outcome(org_id="org-a"))
        await store.record(_outcome(org_id="org-b"))
        result = await store.get_task_completion_rate(org_id="org-a")
        assert result["total"] == 1


class TestGetExperienceContext:
    @pytest.mark.asyncio
    async def test_no_matches_returns_empty_string(self) -> None:
        store = InMemoryOutcomeStore()
        result = await store.get_experience_context("code")
        assert result == ""

    @pytest.mark.asyncio
    async def test_hard_failures_render_as_markdown(self) -> None:
        store = InMemoryOutcomeStore()
        await store.record(
            _outcome(task_type="code", success=False, error_type="TimeoutError", model_used="gpt")
        )
        result = await store.get_experience_context("code")
        assert "## Recent Failure Patterns" in result
        assert "TimeoutError" in result
        assert "gpt" in result

    @pytest.mark.asyncio
    async def test_unknown_error_type_defaults_label(self) -> None:
        store = InMemoryOutcomeStore()
        await store.record(_outcome(task_type="code", success=False, error_type=""))
        result = await store.get_experience_context("code")
        assert "unknown" in result

    @pytest.mark.asyncio
    async def test_thumb_down_outcomes_render_as_markdown(self) -> None:
        store = InMemoryOutcomeStore()
        await store.record(
            _outcome(
                task_type="code",
                success=True,
                thumb="down",
                thumb_comment="too verbose",
                node_id="coder",
            )
        )
        result = await store.get_experience_context("code")
        assert "## User Thumbs-Down Patterns" in result
        assert "node=coder" in result
        assert "too verbose" in result

    @pytest.mark.asyncio
    async def test_thumb_down_without_comment_omits_tail(self) -> None:
        store = InMemoryOutcomeStore()
        await store.record(_outcome(task_type="code", success=True, thumb="down", node_id=""))
        result = await store.get_experience_context("code")
        assert "node=(unknown)" in result
        assert "—" not in result

    @pytest.mark.asyncio
    async def test_both_failures_and_thumb_downs_render_with_blank_line_between(self) -> None:
        store = InMemoryOutcomeStore()
        await store.record(_outcome(task_type="code", success=False, error_type="E"))
        await store.record(_outcome(task_type="code", success=True, thumb="down"))
        result = await store.get_experience_context("code")
        lines = result.split("\n")
        assert "## Recent Failure Patterns" in lines
        assert "## User Thumbs-Down Patterns" in lines
        assert "" in lines

    @pytest.mark.asyncio
    async def test_tool_name_filter_excludes_non_matching(self) -> None:
        store = InMemoryOutcomeStore()
        await store.record(
            _outcome(
                task_type="code",
                success=False,
                tool_calls=[{"name": "git"}],
            )
        )
        result = await store.get_experience_context("code", tool_name="bash")
        assert result == ""

    @pytest.mark.asyncio
    async def test_tool_name_filter_includes_matching(self) -> None:
        store = InMemoryOutcomeStore()
        await store.record(
            _outcome(
                task_type="code",
                success=False,
                error_type="E",
                tool_calls=[{"name": "git"}],
            )
        )
        result = await store.get_experience_context("code", tool_name="git")
        assert result != ""

    @pytest.mark.asyncio
    async def test_org_id_filter_excludes_non_matching(self) -> None:
        store = InMemoryOutcomeStore()
        await store.record(_outcome(task_type="code", success=False, org_id="org-a"))
        result = await store.get_experience_context("code", org_id="org-b")
        assert result == ""

    @pytest.mark.asyncio
    async def test_project_id_filter_excludes_non_matching(self) -> None:
        store = InMemoryOutcomeStore()
        await store.record(_outcome(task_type="code", success=False, project_id="proj-a"))
        result = await store.get_experience_context("code", project_id="proj-b")
        assert result == ""

    @pytest.mark.asyncio
    async def test_project_id_filter_includes_matching(self) -> None:
        store = InMemoryOutcomeStore()
        await store.record(
            _outcome(task_type="code", success=False, error_type="E", project_id="proj-a")
        )
        result = await store.get_experience_context("code", project_id="proj-a")
        assert result != ""

    @pytest.mark.asyncio
    async def test_excludes_outside_cutoff_window(self) -> None:
        store = InMemoryOutcomeStore()
        old = _outcome(
            task_type="code",
            success=False,
            created_at=datetime.now(UTC) - timedelta(days=10),
        )
        await store.record(old)
        result = await store.get_experience_context("code")
        assert result == ""

    @pytest.mark.asyncio
    async def test_non_matching_task_type_excluded(self) -> None:
        store = InMemoryOutcomeStore()
        await store.record(_outcome(task_type="chat", success=False))
        result = await store.get_experience_context("code")
        assert result == ""

    @pytest.mark.asyncio
    async def test_limit_truncates_to_most_recent(self) -> None:
        store = InMemoryOutcomeStore()
        for i in range(3):
            await store.record(_outcome(task_type="code", success=False, error_type=f"Err{i}"))
        result = await store.get_experience_context("code", limit=1)
        assert "Err2" in result
        assert "Err0" not in result


class TestGetUsageBreakdown:
    @pytest.mark.asyncio
    async def test_groups_by_default_user_id(self) -> None:
        store = InMemoryOutcomeStore()
        await store.record(_outcome(user_id="u1", input_tokens=10, output_tokens=5, success=True))
        await store.record(_outcome(user_id="u1", input_tokens=20, output_tokens=10, success=False))
        result = await store.get_usage_breakdown()
        assert len(result) == 1
        group = result[0]
        assert group["group"] == "u1"
        assert group["input_tokens"] == 30
        assert group["output_tokens"] == 15
        assert group["total_tokens"] == 45
        assert group["request_count"] == 2
        assert group["success_count"] == 1
        assert group["avg_response_ms"] >= 0.0

    @pytest.mark.asyncio
    async def test_unknown_group_key_falls_back_to_placeholder(self) -> None:
        store = InMemoryOutcomeStore()
        await store.record(_outcome(user_id=""))
        result = await store.get_usage_breakdown(group_by="user_id")
        assert result[0]["group"] == "(unknown)"

    @pytest.mark.asyncio
    async def test_sorted_descending_by_total_tokens(self) -> None:
        store = InMemoryOutcomeStore()
        await store.record(_outcome(user_id="small", input_tokens=1, output_tokens=1))
        await store.record(_outcome(user_id="big", input_tokens=100, output_tokens=100))
        result = await store.get_usage_breakdown()
        assert [g["group"] for g in result] == ["big", "small"]

    @pytest.mark.asyncio
    async def test_org_id_filters_results(self) -> None:
        store = InMemoryOutcomeStore()
        await store.record(_outcome(org_id="org-a", user_id="u1"))
        await store.record(_outcome(org_id="org-b", user_id="u2"))
        result = await store.get_usage_breakdown(org_id="org-a")
        assert len(result) == 1
        assert result[0]["group"] == "u1"

    @pytest.mark.asyncio
    async def test_excludes_outside_cutoff_window(self) -> None:
        store = InMemoryOutcomeStore()
        await store.record(
            _outcome(user_id="u1", created_at=datetime.now(UTC) - timedelta(days=10))
        )
        result = await store.get_usage_breakdown(days=7)
        assert result == []

    @pytest.mark.asyncio
    async def test_group_by_arbitrary_field(self) -> None:
        store = InMemoryOutcomeStore()
        await store.record(_outcome(task_type="code", input_tokens=5))
        result = await store.get_usage_breakdown(group_by="task_type")
        assert result[0]["group"] == "code"


class TestGetDailyTimeseries:
    @pytest.mark.asyncio
    async def test_buckets_by_day_without_group(self) -> None:
        store = InMemoryOutcomeStore()
        await store.record(_outcome(input_tokens=10, output_tokens=5))
        result = await store.get_daily_timeseries()
        assert len(result) == 1
        assert result[0]["group"] is None
        assert result[0]["total_tokens"] == 15
        assert result[0]["request_count"] == 1

    @pytest.mark.asyncio
    async def test_buckets_by_day_and_group(self) -> None:
        store = InMemoryOutcomeStore()
        await store.record(_outcome(user_id="u1", input_tokens=10))
        await store.record(_outcome(user_id="u2", input_tokens=20))
        result = await store.get_daily_timeseries(group_by="user_id")
        groups = {b["group"] for b in result}
        assert groups == {"u1", "u2"}

    @pytest.mark.asyncio
    async def test_results_sorted_by_date(self) -> None:
        store = InMemoryOutcomeStore()
        await store.record(_outcome(created_at=datetime.now(UTC) - timedelta(days=2)))
        await store.record(_outcome(created_at=datetime.now(UTC)))
        result = await store.get_daily_timeseries(days=7)
        dates = [b["date"] for b in result]
        assert dates == sorted(dates)

    @pytest.mark.asyncio
    async def test_org_id_filters_results(self) -> None:
        store = InMemoryOutcomeStore()
        await store.record(_outcome(org_id="org-a"))
        await store.record(_outcome(org_id="org-b"))
        result = await store.get_daily_timeseries(org_id="org-a")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_excludes_outside_cutoff_window(self) -> None:
        store = InMemoryOutcomeStore()
        await store.record(_outcome(created_at=datetime.now(UTC) - timedelta(days=10)))
        result = await store.get_daily_timeseries(days=7)
        assert result == []


class TestListOutcomes:
    @pytest.mark.asyncio
    async def test_filters_by_task_type(self) -> None:
        store = InMemoryOutcomeStore()
        await store.record(_outcome(task_type="code"))
        await store.record(_outcome(task_type="chat"))
        result = await store.list_outcomes(task_type="code")
        assert len(result) == 1
        assert result[0].task_type == "code"

    @pytest.mark.asyncio
    async def test_limit_truncates_to_most_recent(self) -> None:
        store = InMemoryOutcomeStore()
        for i in range(5):
            await store.record(_outcome(task_type=f"t{i}"))
        result = await store.list_outcomes(limit=2)
        assert [o.task_type for o in result] == ["t3", "t4"]

    @pytest.mark.asyncio
    async def test_org_id_filters_results(self) -> None:
        store = InMemoryOutcomeStore()
        await store.record(_outcome(org_id="org-a"))
        await store.record(_outcome(org_id="org-b"))
        result = await store.list_outcomes(org_id="org-a")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_excludes_outside_cutoff_window(self) -> None:
        store = InMemoryOutcomeStore()
        await store.record(_outcome(created_at=datetime.now(UTC) - timedelta(days=10)))
        result = await store.list_outcomes(days=7)
        assert result == []


class TestOrgMatches:
    def test_no_caller_org_always_matches(self) -> None:
        assert InMemoryOutcomeStore._org_matches("org-a", "") is True

    def test_matching_orgs(self) -> None:
        assert InMemoryOutcomeStore._org_matches("org-a", "org-a") is True

    def test_non_matching_orgs(self) -> None:
        assert InMemoryOutcomeStore._org_matches("org-a", "org-b") is False
