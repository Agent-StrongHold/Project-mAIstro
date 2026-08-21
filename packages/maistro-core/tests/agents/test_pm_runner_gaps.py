"""Edge-case coverage for agents.pm_runner — error/fallback paths not
exercised by test_pm_runner.py (stub dispatch) or test_pm_runner_v0.py
(happy-path LLM/Jira/browser routing)."""

from __future__ import annotations

import pytest

from maistro.agents import pm_runner
from maistro.agents.pm_runner import (
    _extract_atlassian_pats,
    _get_experience_context,
    _parse_pm_output,
    _resolve_capability,
    _resolve_role,
    _run_browser_driven,
    _run_jira_driven,
)
from maistro.graph.types import AgentRole
from maistro.tasks.models import TaskCreate

# --- _get_experience_context --------------------------------------------------


@pytest.mark.asyncio
async def test_experience_context_swallows_store_exception(monkeypatch):
    class BoomStore:
        async def get_experience_context(self, *, task_type=""):
            raise RuntimeError("store unavailable")

    pm_runner.set_pm_outcome_store(BoomStore())
    try:
        ctx = await _get_experience_context(AgentRole.INTAKE)
        assert ctx == ""
    finally:
        pm_runner.set_pm_outcome_store(None)


# --- _emit_pm_event ------------------------------------------------------------


@pytest.mark.asyncio
async def test_emit_pm_event_swallows_bus_exception(monkeypatch):
    class BoomBus:
        attempts = 0

        async def emit(self, event):
            self.attempts += 1
            raise RuntimeError("bus unavailable")

    bus = BoomBus()
    pm_runner.set_pm_event_bus(bus)
    try:
        await pm_runner._emit_pm_event("pm_node_started", {"role": "intake"})

        assert bus.attempts == 1
    finally:
        pm_runner.set_pm_event_bus(None)


# --- _resolve_capability -------------------------------------------------------


class TestResolveCapability:
    def test_explicit_capability_wins(self) -> None:
        task = TaskCreate(description="anything", capability="create_initiative")
        assert _resolve_capability(task) == "create_initiative"

    def test_regex_extracts_from_description(self) -> None:
        task = TaskCreate(description="[Intake Agent] create_initiative: Q3 rollout")
        assert _resolve_capability(task) == "create_initiative"

    def test_no_match_returns_unknown(self) -> None:
        task = TaskCreate(description="no bracketed capability marker here")
        assert _resolve_capability(task) == "unknown"


# --- _extract_atlassian_pats ----------------------------------------------------


class TestExtractAtlassianPats:
    def test_program_not_a_dict_returns_none_none(self) -> None:
        assert _extract_atlassian_pats({"program": "not-a-dict"}) == (None, None)

    def test_payload_missing_program_returns_none_none(self) -> None:
        assert _extract_atlassian_pats({}) == (None, None)

    def test_pats_not_a_dict_returns_none_none(self) -> None:
        assert _extract_atlassian_pats({"program": {"atlassian_pats": "nope"}}) == (None, None)

    def test_extracts_both_pats(self) -> None:
        payload = {"program": {"atlassian_pats": {"jira": "j", "confluence": "c"}}}
        assert _extract_atlassian_pats(payload) == ("j", "c")


# --- _run_browser_driven --------------------------------------------------------


@pytest.mark.asyncio
async def test_browser_driven_falls_back_to_description_for_query(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_search_web(self, query, *, max_results=3):
        captured["query"] = query
        from maistro.tools.browser import SearchResult

        return SearchResult(query=query, summary="s", citations=(), duration_ms=1, source="x")

    async def fake_aclose(self):
        return None

    async def fake_llm_call(*args, **kwargs):
        return '{"capability":"web_search_background","summary":"ok","result":{},"source":"llm"}'

    monkeypatch.setattr(pm_runner.BrowserClient, "search_web", fake_search_web)
    monkeypatch.setattr(pm_runner.BrowserClient, "aclose", fake_aclose)
    monkeypatch.setattr(pm_runner, "maistro_llm_call", fake_llm_call)

    await _run_browser_driven(
        AgentRole.RESEARCH, "web_search_background", {"description": "fallback query text"}
    )
    assert captured["query"] == "fallback query text"


@pytest.mark.asyncio
async def test_browser_driven_llm_failure_falls_back_to_raw_search(monkeypatch):
    from maistro.tools.browser import Citation, SearchResult

    async def fake_search_web(self, query, *, max_results=3):
        return SearchResult(
            query=query,
            summary="s",
            citations=(Citation(title="t", url="u", snippet="sn"),),
            duration_ms=1,
            source="x",
        )

    async def fake_aclose(self):
        return None

    async def fake_llm_call(*args, **kwargs):
        raise RuntimeError("llm gateway down")

    monkeypatch.setattr(pm_runner.BrowserClient, "search_web", fake_search_web)
    monkeypatch.setattr(pm_runner.BrowserClient, "aclose", fake_aclose)
    monkeypatch.setattr(pm_runner, "maistro_llm_call", fake_llm_call)

    out = await _run_browser_driven(AgentRole.RESEARCH, "web_search_background", {"query": "q"})
    assert out.source == "no_data"
    assert "LLM synthesis failed" in out.summary
    assert "llm gateway down" in out.summary


# --- _run_jira_driven ------------------------------------------------------------


@pytest.mark.asyncio
async def test_jira_driven_fetch_program_state_uses_my_issues(monkeypatch):
    from maistro.tools.atlassian import JiraSearchResult

    called_with: dict[str, object] = {}

    async def fake_get_my_issues(self, *, max_results, jira_pat):
        called_with["max_results"] = max_results
        return JiraSearchResult(issues=(), total=0, jql="assignee = currentUser()")

    async def fake_llm_call(*args, **kwargs):
        return '{"capability":"fetch_program_state","summary":"ok","result":{},"source":"llm"}'

    monkeypatch.setattr(pm_runner.AtlassianMCPClient, "jira_get_my_issues", fake_get_my_issues)
    monkeypatch.setattr(pm_runner, "maistro_llm_call", fake_llm_call)

    out = await _run_jira_driven(
        AgentRole.DELIVERY,
        "fetch_program_state",
        {"program": {"atlassian_pats": {"jira": "pat"}}},
    )
    assert called_with["max_results"] == 50
    assert out.source == "llm"


@pytest.mark.asyncio
async def test_jira_driven_unknown_capability_returns_no_data(monkeypatch) -> None:
    out = await _run_jira_driven(
        AgentRole.DELIVERY,
        "some_unmapped_jira_capability",
        {"program": {"atlassian_pats": {"jira": "pat"}}},
    )
    assert out.source == "no_data"


@pytest.mark.asyncio
async def test_jira_driven_llm_failure_falls_back_to_raw_issue_count(monkeypatch):
    from maistro.tools.atlassian import JiraSearchResult

    async def fake_get_my_issues(self, *, max_results, jira_pat):
        return JiraSearchResult(issues=(), total=3, jql="assignee = currentUser()")

    async def fake_llm_call(*args, **kwargs):
        raise RuntimeError("llm down")

    monkeypatch.setattr(pm_runner.AtlassianMCPClient, "jira_get_my_issues", fake_get_my_issues)
    monkeypatch.setattr(pm_runner, "maistro_llm_call", fake_llm_call)

    out = await _run_jira_driven(
        AgentRole.DELIVERY, "poll_jira", {"program": {"atlassian_pats": {"jira": "pat"}}}
    )
    assert out.source == "no_data"
    assert "LLM synthesis failed" in out.summary
    assert out.result["jira_data"]["total"] == 3


# --- _parse_pm_output ------------------------------------------------------------


class TestParsePmOutput:
    def test_non_dict_json_falls_back_to_str_summary(self) -> None:
        out = _parse_pm_output("[1, 2, 3]", "create_initiative")
        assert out.summary == "[1, 2, 3]"
        assert out.result == {"raw": "[1, 2, 3]"}

    def test_validation_failure_falls_back_to_raw_dict(self) -> None:
        # `summary` set to a type pydantic can't coerce into str triggers
        # model_validate to raise, hitting the except Exception fallback.
        raw = '{"capability": "x", "summary": {"nested": "not-a-string"}, "source": "llm"}'
        out = _parse_pm_output(raw, "create_initiative")
        assert out.capability == "create_initiative"
        assert "nested" in out.summary


# --- _resolve_role ---------------------------------------------------------------


class TestResolveRole:
    def test_unknown_agent_id_falls_back_to_capability_lookup(self) -> None:
        from maistro.graph.pm_domain import PM_PRIMARY_CAPABILITY

        role, primary_capability = next(iter(PM_PRIMARY_CAPABILITY.items()))
        resolved = _resolve_role("totally-unknown-agent", primary_capability)
        assert resolved == role

    def test_unknown_agent_and_capability_returns_none(self) -> None:
        assert _resolve_role("totally-unknown-agent", "no-such-capability-anywhere") is None


# --- run_pm_task: role resolution failure + llm exception propagation -----------


@pytest.mark.asyncio
async def test_run_pm_task_unresolvable_role_returns_no_data(monkeypatch) -> None:
    monkeypatch.delenv("MAISTRO_PM_USE_STUBS", raising=False)
    task = TaskCreate(
        description="anything",
        agent_id="totally-unknown-agent",
        capability="no-such-capability-anywhere",
    )
    result = await pm_runner.run_pm_task(task)
    assert result.success is True
    assert "source=no_data" in result.final_answer


@pytest.mark.asyncio
async def test_run_pm_task_llm_failure_records_outcome_emits_failed_and_raises(monkeypatch):
    monkeypatch.delenv("MAISTRO_PM_USE_STUBS", raising=False)

    events: list[tuple[str, dict]] = []
    recorded: list = []

    class FakeBus:
        async def emit(self, event):
            events.append((event.event_type, event.payload))

    class FakeOutcomeStore:
        async def get_experience_context(self, *, task_type=""):
            return ""

        async def record(self, outcome):
            recorded.append(outcome)

    async def fake_llm_call(*args, **kwargs):
        raise RuntimeError("gateway unreachable")

    monkeypatch.setattr(pm_runner, "maistro_llm_call", fake_llm_call)
    pm_runner.set_pm_event_bus(FakeBus())
    pm_runner.set_pm_outcome_store(FakeOutcomeStore())
    try:
        task = TaskCreate(
            description="Launch a new agent platform",
            agent_id="intake",
            capability="create_initiative",
        )
        with pytest.raises(RuntimeError, match="gateway unreachable"):
            await pm_runner.run_pm_task(task)

        assert any(t == "pm_node_failed" for t, _ in events)
        failed_payload = next(p for t, p in events if t == "pm_node_failed")
        assert failed_payload["error"] == "gateway unreachable"
        assert len(recorded) == 1
        assert recorded[0].success is False
        assert recorded[0].error_type == "RuntimeError"
    finally:
        pm_runner.set_pm_event_bus(None)
        pm_runner.set_pm_outcome_store(None)
