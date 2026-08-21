"""Day 2 PM runner — real LLM call path tests.

Covers the rewrite of `pm_runner.run_pm_task()` from stub-only dispatch
to LLM-gateway-backed Claude calls. Live LLM test gated by
`RUN_LIVE_LLM=1` so default CI doesn't burn tokens; the offline tests
monkeypatch `maistro_llm_call` and exercise schema/contract paths.
"""

from __future__ import annotations

import json
import os

import pytest

from maistro.agents import pm_runner
from maistro.agents.types import ConductorOutput
from maistro.tasks.models import TaskCreate


def _task(
    *,
    agent_id: str = "intake",
    capability: str = "create_initiative",
    description: str = "Launch a new agent platform",
    confirmed: bool = False,
) -> TaskCreate:
    return TaskCreate(
        description=description,
        agent_id=agent_id,
        capability=capability,
        program_context={
            "program_name": "MAISTRO v0",
            "goals": ["ship in 7 days"],
            "confirmed": confirmed,
        },
    )


@pytest.mark.asyncio
async def test_runner_calls_llm_for_non_gated_capability(monkeypatch):
    """Non-gated capabilities (e.g. create_initiative) must invoke maistro_llm_call."""
    captured: dict[str, object] = {}

    async def fake_llm_call(
        messages, *, model=None, temperature=None, json_mode=True, timeout=120.0
    ):
        captured["messages"] = messages
        captured["model"] = model
        return json.dumps(
            {
                "capability": "create_initiative",
                "summary": "Drafted initiative for the MAISTRO v0 launch program — 6 goals identified.",
                "result": {
                    "title": "MAISTRO v0 launch",
                    "goals": ["ship in 7 days"],
                    "draft_status": "needs_confirm",
                },
                "source": "llm",
            }
        )

    monkeypatch.setattr(pm_runner, "maistro_llm_call", fake_llm_call)
    monkeypatch.delenv("MAISTRO_PM_USE_STUBS", raising=False)

    result = await pm_runner.run_pm_task(_task())
    assert isinstance(result, ConductorOutput)
    assert result.success
    # The LLM call must have been routed (2 messages: system + user).
    msgs = captured.get("messages")
    assert msgs is not None and len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert "Intake Agent" in msgs[0]["content"]
    assert msgs[1]["role"] == "user"
    assert "create_initiative" in msgs[1]["content"]
    # Final answer must include the LLM summary, not a stub marker.
    assert "Drafted initiative" in result.final_answer
    assert "POC stub completed" not in result.final_answer


@pytest.mark.asyncio
async def test_runner_short_circuits_no_data_capabilities(monkeypatch):
    """Capabilities still in _NO_DATA_WITHOUT_TOOLS (Airtable, fetch_program_metrics,
    etc) must not invoke the LLM and must return source='no_data'."""
    called = False

    async def fake_llm_call(*args, **kwargs):
        nonlocal called
        called = True
        return "{}"

    monkeypatch.setattr(pm_runner, "maistro_llm_call", fake_llm_call)
    monkeypatch.delenv("MAISTRO_PM_USE_STUBS", raising=False)

    result = await pm_runner.run_pm_task(
        _task(
            agent_id="program_manager", capability="poll_airtable", description="Sync from Airtable"
        )
    )
    assert called is False, "poll_airtable must not invoke the LLM in v0 (Airtable not wired)"
    assert "source=no_data" in result.final_answer


@pytest.mark.asyncio
async def test_jira_capability_without_pat_returns_no_data_with_link(monkeypatch):
    """poll_jira without a Jira PAT in program_context must return
    source='no_data' AND surface the PAT generation URL so the user can fix it."""

    async def fake_llm_call(*args, **kwargs):
        return "{}"

    async def fake_mcp_call(*args, **kwargs):
        raise AssertionError("MCP must not be called when there's no PAT")

    monkeypatch.setattr(pm_runner, "maistro_llm_call", fake_llm_call)
    monkeypatch.setattr(pm_runner.AtlassianMCPClient, "jira_get_my_issues", fake_mcp_call)
    monkeypatch.delenv("MAISTRO_PM_USE_STUBS", raising=False)

    task = _task(
        agent_id="delivery", capability="poll_jira", description="Fetch open issues for Alice"
    )
    result = await pm_runner.run_pm_task(task)
    assert "source=no_data" in result.final_answer
    # Must surface the PAT URL so 2FA-retry flow works
    assert "jira.example.com" in result.final_answer
    assert "PATs" in result.final_answer or "PAT" in result.final_answer


@pytest.mark.asyncio
async def test_jira_capability_with_pat_calls_mcp_then_llm(monkeypatch):
    """poll_jira with a PAT must: (1) call AtlassianMCPClient with the PAT,
    (2) feed the resulting issues into the LLM, (3) return a PMRoleOutput
    with source='llm' and jira_data preserved."""
    from maistro.tools.atlassian import JiraIssue, JiraSearchResult

    mcp_called_with: dict[str, object] = {}
    llm_called_with: dict[str, object] = {}

    async def fake_mcp_get_my_issues(self, *, max_results, jira_pat):
        mcp_called_with["max_results"] = max_results
        mcp_called_with["jira_pat"] = jira_pat
        return JiraSearchResult(
            issues=(
                JiraIssue(
                    key="PROJ-1",
                    summary="Ship pm-fleet v0",
                    status="In Progress",
                    assignee="alice",
                    issuetype="Story",
                ),
                JiraIssue(
                    key="PROJ-2",
                    summary="Wire Atlassian MCP",
                    status="Open",
                    assignee="alice",
                    issuetype="Task",
                ),
            ),
            total=2,
            jql="assignee = currentUser()",
        )

    async def fake_llm_call(
        messages, *, model=None, temperature=None, json_mode=True, timeout=120.0
    ):
        llm_called_with["messages"] = messages
        return (
            '{"capability":"poll_jira",'
            '"summary":"Alice has 2 open issues — both v0 critical-path.",'
            '"result":{"summary_count":2,"top_issue":"PROJ-1"},'
            '"source":"llm"}'
        )

    monkeypatch.setattr(
        pm_runner.AtlassianMCPClient,
        "jira_get_my_issues",
        fake_mcp_get_my_issues,
    )
    monkeypatch.setattr(pm_runner, "maistro_llm_call", fake_llm_call)
    monkeypatch.delenv("MAISTRO_PM_USE_STUBS", raising=False)

    task = TaskCreate(
        description="Fetch open Jira issues",
        agent_id="delivery",
        capability="poll_jira",
        program_context={
            "program_name": "MAISTRO v0",
            "atlassian_pats": {"jira": "fake-jira-pat-abc123"},
            "confirmed": False,
        },
    )
    result = await pm_runner.run_pm_task(task)

    # MCP was called with the right PAT
    assert mcp_called_with["jira_pat"] == "fake-jira-pat-abc123"
    # LLM saw the Jira data in its prompt
    user_msg = llm_called_with["messages"][1]["content"]
    assert "jira_data" in user_msg
    assert "PROJ-1" in user_msg
    # Output has source=llm + Alice's summary preserved
    assert "source=llm" in result.final_answer
    assert "Alice has 2 open issues" in result.final_answer


@pytest.mark.asyncio
async def test_detect_blockers_uses_blockers_jql(monkeypatch):
    """detect_blockers must call jira_search_issues with the unresolved-blockers JQL,
    not jira_get_my_issues."""
    from maistro.tools.atlassian import JiraSearchResult

    search_call: dict[str, object] = {}

    async def fake_search(self, jql, *, max_results, jira_pat):
        search_call["jql"] = jql
        search_call["max_results"] = max_results
        return JiraSearchResult(issues=(), total=0, jql=jql)

    async def fake_llm_call(*args, **kwargs):
        return (
            '{"capability":"detect_blockers","summary":"No blockers found.",'
            '"result":{"blockers":[]},"source":"llm"}'
        )

    monkeypatch.setattr(
        pm_runner.AtlassianMCPClient,
        "jira_search_issues",
        fake_search,
    )
    monkeypatch.setattr(pm_runner, "maistro_llm_call", fake_llm_call)
    monkeypatch.delenv("MAISTRO_PM_USE_STUBS", raising=False)

    task = TaskCreate(
        description="Identify blockers",
        agent_id="delivery",
        capability="detect_blockers",
        program_context={"atlassian_pats": {"jira": "fake-pat"}, "confirmed": False},
    )
    await pm_runner.run_pm_task(task)
    assert "Unresolved" in search_call["jql"]
    assert "Blocked" in search_call["jql"]


@pytest.mark.asyncio
async def test_jira_mcp_transport_error_returns_no_data_with_hint(monkeypatch):
    """When mcp-atlassian is unreachable or returns an error, we must
    return source='no_data' with an actionable hint, not crash."""

    async def fake_mcp_raises(self, *, max_results, jira_pat):
        from maistro.tools.atlassian import AtlassianMCPError

        raise AtlassianMCPError("connection refused on http://atlassian-mcp:8000")

    async def fake_llm_call(*args, **kwargs):
        raise AssertionError("LLM must not be called when MCP fails")

    monkeypatch.setattr(
        pm_runner.AtlassianMCPClient,
        "jira_get_my_issues",
        fake_mcp_raises,
    )
    monkeypatch.setattr(pm_runner, "maistro_llm_call", fake_llm_call)
    monkeypatch.delenv("MAISTRO_PM_USE_STUBS", raising=False)

    task = TaskCreate(
        description="Fetch open issues",
        agent_id="delivery",
        capability="poll_jira",
        program_context={"atlassian_pats": {"jira": "fake-pat"}, "confirmed": False},
    )
    result = await pm_runner.run_pm_task(task)
    assert "source=no_data" in result.final_answer
    assert "Atlassian MCP error" in result.final_answer
    answer_lower = result.final_answer.lower()
    assert "retry" in answer_lower or "pat" in answer_lower


@pytest.mark.asyncio
async def test_gated_capability_generates_draft_without_raising(monkeypatch):
    """v0: gated capabilities produce drafts in pm_runner (with
    draft_status='needs_confirm' embedded in the LLM output). The actual
    write gate lives in Hive's confirm handler, not here."""

    async def _unused_llm_call(*args, **kwargs):
        return '{"capability":"create_initiative","summary":"x","result":{"draft_status":"needs_confirm"},"source":"llm"}'

    # `create_jira_ticket` is in _NO_DATA_WITHOUT_TOOLS so it short-circuits
    # before LLM in v0; we test create_initiative instead since it's gated
    # but not in the no-data set.
    monkeypatch.setattr(pm_runner, "maistro_llm_call", _unused_llm_call)

    # Use a proper async stub via monkeypatch + an actual async fn:
    async def fake_llm_call(*args, **kwargs):
        return (
            '{"capability":"create_initiative","summary":"Drafted initiative",'
            '"result":{"draft_status":"needs_confirm"},"source":"llm"}'
        )

    monkeypatch.setattr(pm_runner, "maistro_llm_call", fake_llm_call)
    monkeypatch.delenv("MAISTRO_PM_USE_STUBS", raising=False)

    # create_initiative is gated AND not in _NO_DATA_WITHOUT_TOOLS — exercise the gate path.
    result = await pm_runner.run_pm_task(
        _task(agent_id="intake", capability="create_initiative", confirmed=False)
    )
    assert result.success
    # The output is a draft — the LLM was called, output includes draft_status.
    assert "needs_confirm" in result.final_answer
    # Write capabilities that are also no-data (create_jira_ticket) still short-circuit.
    result_no_data = await pm_runner.run_pm_task(
        _task(agent_id="delivery", capability="create_jira_ticket", confirmed=False)
    )
    assert "source=no_data" in result_no_data.final_answer


@pytest.mark.asyncio
async def test_stub_rollback_mode_uses_legacy_handlers(monkeypatch):
    """MAISTRO_PM_USE_STUBS=true reverts to the legacy stub dispatch."""
    monkeypatch.setenv("MAISTRO_PM_USE_STUBS", "true")
    called = False

    async def fake_llm_call(*args, **kwargs):
        nonlocal called
        called = True
        return "{}"

    monkeypatch.setattr(pm_runner, "maistro_llm_call", fake_llm_call)

    result = await pm_runner.run_pm_task(_task())
    assert called is False, "rollback mode must not hit the LLM"
    assert result.success
    assert "stub-rollback" in result.final_answer


@pytest.mark.asyncio
async def test_malformed_llm_response_doesnt_crash(monkeypatch):
    """If the gateway returns non-JSON or wrong shape, we still return a
    valid ConductorOutput rather than 500ing the user."""

    async def fake_llm_call(*args, **kwargs):
        return "This is not JSON — the gateway returned plain text."

    monkeypatch.setattr(pm_runner, "maistro_llm_call", fake_llm_call)
    monkeypatch.delenv("MAISTRO_PM_USE_STUBS", raising=False)

    result = await pm_runner.run_pm_task(_task())
    assert result.success
    # The raw text gets surfaced in the summary so the operator can debug.
    assert "This is not JSON" in result.final_answer


@pytest.mark.asyncio
async def test_web_search_calls_browser_then_llm(monkeypatch):
    """RESEARCH agent's web_search_background must drive a real BrowserClient
    call FIRST, then feed the search result into the LLM for synthesis."""
    from maistro.tools.browser import Citation, SearchResult

    browser_called_with: dict[str, object] = {}
    llm_messages: dict[str, object] = {}

    async def fake_search_web(self, query, *, max_results=3):
        browser_called_with["query"] = query
        browser_called_with["max_results"] = max_results
        return SearchResult(
            query=query,
            summary="maistro is the company's agent platform; Claude is the LLM backbone.",
            citations=(
                Citation(
                    title="maistro docs",
                    url="https://example.com/docs",
                    snippet="maistro documentation overview",
                ),
                Citation(
                    title="Claude API",
                    url="https://docs.anthropic.com",
                    snippet="Anthropic API reference",
                ),
            ),
            duration_ms=8200,
            source="browser-use",
        )

    async def fake_aclose(self):
        return None

    async def fake_llm_call(
        messages, *, model=None, temperature=None, json_mode=True, timeout=120.0
    ):
        llm_messages["messages"] = messages
        return (
            '{"capability":"web_search_background",'
            '"summary":"Background: 2 reputable sources on maistro + Claude agent platforms.",'
            '"result":{"queries":["maistro platform"],"hypotheses":["Claude is core"]},'
            '"source":"llm"}'
        )

    monkeypatch.setattr(pm_runner.BrowserClient, "search_web", fake_search_web)
    monkeypatch.setattr(pm_runner.BrowserClient, "aclose", fake_aclose)
    monkeypatch.setattr(pm_runner, "maistro_llm_call", fake_llm_call)
    monkeypatch.delenv("MAISTRO_PM_USE_STUBS", raising=False)

    task = TaskCreate(
        description="Background on agent platforms",
        agent_id="research",
        capability="web_search_background",
        program_context={
            "program_name": "MAISTRO v0",
            "goals": ["self-improving agent fleet"],
            "confirmed": False,
        },
    )
    result = await pm_runner.run_pm_task(task)

    # Browser was called with a query derived from program_name + first goal
    assert "MAISTRO v0" in str(browser_called_with["query"])
    # LLM saw the search results in its prompt
    user_msg = llm_messages["messages"][1]["content"]
    assert "web_search" in user_msg
    assert "example.com/docs" in user_msg
    # Output source = llm; the synthesized summary is in the answer
    assert "source=llm" in result.final_answer
    assert "2 reputable sources" in result.final_answer


@pytest.mark.asyncio
async def test_web_search_fallback_when_browser_unavailable(monkeypatch):
    """When browser-use can't run (e.g. no Chromium in this env), pm_runner
    must return source='no_data' with a clear message — never invent web
    findings."""
    from maistro.tools.browser import BrowserToolError

    async def fake_search_web(self, query, *, max_results=3):
        raise BrowserToolError(
            "browser-use not installed in this environment. Image bakes it in via Dockerfile."
        )

    async def fake_aclose(self):
        return None

    async def fake_llm_call(*args, **kwargs):
        raise AssertionError("LLM must not be called when browser fails")

    monkeypatch.setattr(pm_runner.BrowserClient, "search_web", fake_search_web)
    monkeypatch.setattr(pm_runner.BrowserClient, "aclose", fake_aclose)
    monkeypatch.setattr(pm_runner, "maistro_llm_call", fake_llm_call)
    monkeypatch.delenv("MAISTRO_PM_USE_STUBS", raising=False)

    task = TaskCreate(
        description="Research the topic",
        agent_id="research",
        capability="web_search_background",
        program_context={"program_name": "MAISTRO v0", "confirmed": False},
    )
    result = await pm_runner.run_pm_task(task)
    assert "source=no_data" in result.final_answer
    assert "Web search unavailable" in result.final_answer
    assert "browser-use not installed" in result.final_answer


@pytest.mark.asyncio
async def test_experience_context_injected_when_outcome_store_wired(monkeypatch):
    """v0 self-improvement loop: when an outcome_store is wired (via
    set_pm_outcome_store), the next LLM call's system prompt must include
    the 'Recent Failure Patterns' section from outcome_store.get_experience_context."""
    captured: dict[str, object] = {}

    class FakeOutcomeStore:
        async def get_experience_context(self, *, task_type=""):
            return (
                f"## Recent Failure Patterns\n- timeout (model: claude-sonnet-4-6) for {task_type}"
            )

    async def fake_llm_call(
        messages, *, model=None, temperature=None, json_mode=True, timeout=120.0
    ):
        captured["messages"] = messages
        return (
            '{"capability":"create_initiative","summary":"Drafted with learned context.",'
            '"result":{"draft_status":"needs_confirm"},"source":"llm"}'
        )

    monkeypatch.setattr(pm_runner, "maistro_llm_call", fake_llm_call)
    monkeypatch.delenv("MAISTRO_PM_USE_STUBS", raising=False)
    pm_runner.set_pm_outcome_store(FakeOutcomeStore())
    try:
        result = await pm_runner.run_pm_task(_task())
        system_msg = captured["messages"][0]["content"]
        # The experience_context must have been APPENDED to the persona prompt.
        assert "Recent Failure Patterns" in system_msg
        assert "timeout" in system_msg
        # The persona prompt itself must still be present.
        assert "Intake Agent" in system_msg
        assert result.success
    finally:
        pm_runner.set_pm_outcome_store(None)


@pytest.mark.asyncio
async def test_node_lifecycle_events_emitted_when_bus_wired(monkeypatch):
    """When an event_bus is wired, pm_runner emits pm_node_started +
    pm_node_completed (or pm_node_failed) on every invocation."""
    events: list[tuple[str, dict]] = []

    class FakeBus:
        async def emit(self, event):
            events.append((event.event_type, event.payload))

    async def fake_llm_call(*args, **kwargs):
        return '{"capability":"create_initiative","summary":"ok","result":{},"source":"llm"}'

    monkeypatch.setattr(pm_runner, "maistro_llm_call", fake_llm_call)
    monkeypatch.delenv("MAISTRO_PM_USE_STUBS", raising=False)
    pm_runner.set_pm_event_bus(FakeBus())
    try:
        await pm_runner.run_pm_task(_task())
        event_types = [e[0] for e in events]
        assert "pm_node_started" in event_types
        assert "pm_node_completed" in event_types
        # The completed event carries source + duration for the eval-judge.
        completed_payload = next(p for t, p in events if t == "pm_node_completed")
        assert completed_payload["source"] == "llm"
        assert completed_payload["duration_ms"] >= 0
    finally:
        pm_runner.set_pm_event_bus(None)


@pytest.mark.asyncio
async def test_outcome_recorded_on_success_when_store_wired(monkeypatch):
    """outcome_store.record() called on every successful PM-runner invocation
    so the next run's experience_context sees it."""
    recorded: list = []

    class FakeOutcomeStore:
        async def get_experience_context(self, *, task_type=""):
            return ""

        async def record(self, outcome):
            recorded.append(outcome)
            return 1

    async def fake_llm_call(*args, **kwargs):
        return '{"capability":"create_initiative","summary":"ok","result":{},"source":"llm"}'

    monkeypatch.setattr(pm_runner, "maistro_llm_call", fake_llm_call)
    monkeypatch.delenv("MAISTRO_PM_USE_STUBS", raising=False)
    pm_runner.set_pm_outcome_store(FakeOutcomeStore())
    try:
        await pm_runner.run_pm_task(_task())
        assert len(recorded) == 1, "outcome_store.record should be called once per task"
        outcome = recorded[0]
        assert outcome.task_type == "intake"
        assert outcome.success is True
    finally:
        pm_runner.set_pm_outcome_store(None)


# Live LLM test — only runs with RUN_LIVE_LLM=1 + valid .env settings.
@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_LLM") != "1",
    reason="Live LLM gateway call; set RUN_LIVE_LLM=1 + LITELLM_URL + LITELLM_MASTER_KEY"
    " + DEFAULT_MODEL to enable.",
)
async def test_intake_create_initiative_live_through_llm_gateway():
    """End-to-end: hit the real LLM gateway via maistro_llm_call, parse a
    real Claude response into PMRoleOutput, wrap in ConductorOutput.
    Asserts the response is substantive (no stub markers, len > 80)."""
    task = _task(description="Build a self-improving DAG-shaped PM hyperagent for MAISTRO v0")
    result = await pm_runner.run_pm_task(task)
    assert isinstance(result, ConductorOutput)
    assert result.success
    assert "source=llm" in result.final_answer
    assert "source=stub" not in result.final_answer
    # Substantive output — not a one-liner from a misconfigured model.
    assert len(result.final_answer) > 200, (
        f"Live response unexpectedly short: {result.final_answer!r}"
    )
