"""Coverage for maistro.graph.run — condition-language helpers and GraphRun
lifecycle (cancel, duration, success_rate, _emit error-swallowing, and the
start()/_execute() control flow including cancellation and exception paths)."""

from __future__ import annotations

import asyncio

import pytest

from maistro.graph.phases import GraphPhase, NodePhase
from maistro.graph.run import (
    GraphRun,
    _build_final_answer,
    _compare,
    _get_temperature,
    _next_nodes,
    _parse_rhs,
    _resolve_path,
    evaluate_condition,
)
from maistro.graph.types import (
    AgentRole,
    CodeOutput,
    GraphConfig,
    GraphEdge,
    GraphTask,
    NodeConfig,
    PlanOutput,
    ReviewOutput,
)

VALID_PLAN_JSON = (
    '{"summary": "do the thing", "subtasks": [{"title": "step", '
    '"description": "step", "role": "coder"}], "estimated_files": ["a.py"]}'
)


async def _llm_returns(text: str):
    async def _call(*args, **kwargs):
        return text

    return _call


# --- _get_temperature -----------------------------------------------------


class TestGetTemperature:
    def test_node_config_temperature_wins(self) -> None:
        cfg = NodeConfig(temperature=0.9)
        assert _get_temperature(AgentRole.PLANNER, cfg, default=0.1) == 0.9

    def test_falls_back_to_default_when_no_node_config(self) -> None:
        assert _get_temperature(AgentRole.PLANNER, None, default=0.3) == 0.3

    def test_falls_back_to_default_when_node_config_temperature_is_none(self) -> None:
        cfg = NodeConfig(temperature=None)
        assert _get_temperature(AgentRole.PLANNER, cfg, default=0.5) == 0.5


# --- _resolve_path ---------------------------------------------------------


class TestResolvePath:
    def test_no_dot_returns_missing(self) -> None:
        from maistro.graph.run import _MISSING

        assert _resolve_path("plan", None, None, None) is _MISSING

    def test_unknown_namespace_returns_missing(self) -> None:
        from maistro.graph.run import _MISSING

        assert _resolve_path("nope.attr", None, None, None) is _MISSING

    def test_resolves_attr_from_plan(self) -> None:
        plan = PlanOutput(summary="hi")
        assert _resolve_path("plan.summary", plan, None, None) == "hi"


# --- _parse_rhs --------------------------------------------------------------


class TestParseRhs:
    def test_true_literal(self) -> None:
        assert _parse_rhs("True") is True

    def test_false_literal(self) -> None:
        assert _parse_rhs("False") is False

    def test_none_literal(self) -> None:
        assert _parse_rhs("None") is None

    def test_float_literal(self) -> None:
        assert _parse_rhs("1.5") == 1.5

    def test_int_literal(self) -> None:
        assert _parse_rhs("7") == 7

    def test_quoted_string_strips_quotes(self) -> None:
        assert _parse_rhs("'hello'") == "hello"

    def test_unquoted_non_numeric_string_passes_through(self) -> None:
        assert _parse_rhs("approved") == "approved"


# --- _compare ----------------------------------------------------------------


class TestCompare:
    def test_is_equals(self) -> None:
        assert _compare(1, " is ", 1) is True

    def test_equals_operator(self) -> None:
        assert _compare(1, " == ", 1) is True

    def test_is_not(self) -> None:
        assert _compare(1, " is not ", 2) is True

    def test_not_equals_operator(self) -> None:
        assert _compare(1, " != ", 2) is True

    def test_less_than(self) -> None:
        assert _compare(1, " < ", 2) is True

    def test_greater_than(self) -> None:
        assert _compare(2, " > ", 1) is True

    def test_less_than_equal(self) -> None:
        assert _compare(2, " <= ", 2) is True

    def test_greater_than_equal(self) -> None:
        assert _compare(2, " >= ", 2) is True

    def test_type_error_returns_false(self) -> None:
        assert _compare("a", " < ", 2) is False

    def test_unrecognized_operator_falls_through_to_false(self) -> None:
        assert _compare(1, "", 2) is False


# --- evaluate_condition --------------------------------------------------------


class TestEvaluateCondition:
    def test_no_matching_operator_returns_false(self) -> None:
        assert evaluate_condition("no operator here", None, None, None) is False

    def test_missing_lhs_returns_false(self) -> None:
        assert evaluate_condition("nope.attr == 1", None, None, None) is False

    def test_matching_condition_returns_true(self) -> None:
        review = ReviewOutput(approved=True, score=9)
        assert evaluate_condition("review.approved == True", None, None, review) is True


# --- _next_nodes ---------------------------------------------------------------


class TestNextNodes:
    def test_edge_with_no_to_role_is_skipped(self) -> None:
        config = GraphConfig(
            nodes=[AgentRole.PLANNER],
            edges=[GraphEdge(from_role=AgentRole.PLANNER, to_role=None)],
        )
        assert _next_nodes(config, AgentRole.PLANNER, None, None, None) == []

    def test_unmet_condition_is_skipped(self) -> None:
        config = GraphConfig(
            nodes=[AgentRole.PLANNER],
            edges=[
                GraphEdge(
                    from_role=AgentRole.PLANNER,
                    to_role=AgentRole.CODER,
                    condition="plan.summary == 'nope'",
                )
            ],
        )
        plan = PlanOutput(summary="yes")
        assert _next_nodes(config, AgentRole.PLANNER, plan, None, None) == []

    def test_parallel_edges_are_all_included(self) -> None:
        config = GraphConfig(
            nodes=[AgentRole.PLANNER],
            edges=[
                GraphEdge(from_role=AgentRole.PLANNER, to_role=AgentRole.CODER, parallel=True),
                GraphEdge(from_role=AgentRole.PLANNER, to_role=AgentRole.REVIEWER, parallel=True),
            ],
        )
        result = _next_nodes(config, AgentRole.PLANNER, None, None, None)
        assert set(result) == {AgentRole.CODER, AgentRole.REVIEWER}


# --- GraphRun lifecycle helpers --------------------------------------------------


def _run() -> GraphRun:
    return GraphRun(task=GraphTask(description="task", workspace="/tmp"))


class TestCancel:
    def test_cancel_transitions_running_to_cancelling(self) -> None:
        run = _run()
        run.phase = GraphPhase.RUNNING
        run.cancel()
        assert run.phase == GraphPhase.CANCELLING
        assert run._cancel_requested is True

    def test_cancel_marks_active_node_runs_cancelled(self) -> None:
        from maistro.graph.node import NodeRun
        from maistro.graph.strategy import PlannerStrategy

        run = _run()
        run.phase = GraphPhase.RUNNING
        nr = NodeRun(
            run_id="r1",
            role=AgentRole.PLANNER,
            strategy=PlannerStrategy(),
            model="default",
            system_prompt="sp",
            user_prompt="up",
        )
        nr.phase = NodePhase.RUNNING
        run.node_runs.append(nr)
        run.cancel()
        assert nr._cancel_requested is True

    def test_cancel_when_not_running_skips_transition(self) -> None:
        run = _run()
        run.phase = GraphPhase.IDLE
        run.cancel()
        assert run.phase == GraphPhase.IDLE
        assert run._cancel_requested is True


class TestLatestNodeRun:
    def test_no_runs_returns_none(self) -> None:
        run = _run()
        assert run.latest_node_run(AgentRole.PLANNER) is None

    def test_returns_last_matching_run(self) -> None:
        from maistro.graph.node import NodeRun
        from maistro.graph.strategy import PlannerStrategy

        run = _run()
        first = NodeRun(
            run_id="r1",
            role=AgentRole.PLANNER,
            strategy=PlannerStrategy(),
            model="default",
            system_prompt="sp",
            user_prompt="up1",
        )
        second = NodeRun(
            run_id="r1",
            role=AgentRole.PLANNER,
            strategy=PlannerStrategy(),
            model="default",
            system_prompt="sp",
            user_prompt="up2",
        )
        run.node_runs.extend([first, second])
        assert run.latest_node_run(AgentRole.PLANNER) is second


class TestDurationS:
    def test_no_phase_log_returns_zero(self) -> None:
        run = _run()
        assert run.duration_s() == 0.0

    def test_terminal_phase_uses_last_logged_time(self) -> None:
        run = _run()
        run._transition(GraphPhase.RUNNING)
        run._transition(GraphPhase.COMPLETED)
        assert run.duration_s() >= 0.0

    def test_non_terminal_phase_uses_current_time(self) -> None:
        run = _run()
        run._transition(GraphPhase.RUNNING)
        assert run.duration_s() >= 0.0


class TestBuildFinalAnswer:
    def test_review_not_approved_lists_issues(self) -> None:
        review = ReviewOutput(approved=False, score=3.0, issues=["bug a", "bug b"])
        answer = _build_final_answer(review, None)
        assert "bug a" in answer and "bug b" in answer

    def test_no_review_falls_back_to_plan_summary(self) -> None:
        plan = PlanOutput(summary="the plan")
        assert _build_final_answer(None, plan) == "the plan"

    def test_no_review_or_plan_returns_empty(self) -> None:
        assert _build_final_answer(None, None) == ""


class TestTotalTokens:
    def test_sums_tokens_across_node_runs(self) -> None:
        from maistro.graph.node import NodeRun
        from maistro.graph.strategy import PlannerStrategy

        run = _run()
        nr = NodeRun(
            run_id="r1",
            role=AgentRole.PLANNER,
            strategy=PlannerStrategy(),
            model="default",
            system_prompt="sp",
            user_prompt="up",
        )
        nr.tokens_in = 10
        nr.tokens_out = 5
        run.node_runs.append(nr)
        assert run.total_tokens() == 15


class TestSuccessRate:
    def test_no_node_runs_returns_zero(self) -> None:
        run = _run()
        assert run.success_rate() == 0.0

    def test_computes_fraction_succeeded(self) -> None:
        from maistro.graph.node import NodeRun
        from maistro.graph.strategy import PlannerStrategy

        run = _run()
        succeeded = NodeRun(
            run_id="r1",
            role=AgentRole.PLANNER,
            strategy=PlannerStrategy(),
            model="default",
            system_prompt="sp",
            user_prompt="up",
        )
        succeeded.phase = NodePhase.SUCCEEDED
        failed = NodeRun(
            run_id="r1",
            role=AgentRole.CODER,
            strategy=PlannerStrategy(),
            model="default",
            system_prompt="sp",
            user_prompt="up",
        )
        failed.phase = NodePhase.FAILED
        run.node_runs.extend([succeeded, failed])
        assert run.success_rate() == 0.5


# --- _emit ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emit_swallows_callback_exception() -> None:
    from maistro.graph.events import graph_started

    run = _run()
    attempts = 0

    async def boom(event):
        nonlocal attempts
        attempts += 1
        raise RuntimeError("callback exploded")

    run.event_callbacks.append(boom)
    await run._emit(graph_started(run.run_id, nodes=[], entry="planner", model="m"))

    assert attempts == 1


# --- start() / _execute() control flow -------------------------------------------


@pytest.mark.asyncio
async def test_start_when_not_idle_returns_existing_result() -> None:
    run = _run()
    run.phase = GraphPhase.COMPLETED
    result = await run.start(await _llm_returns(VALID_PLAN_JSON))
    assert result is run.result or result.success is False


@pytest.mark.asyncio
async def test_start_propagates_classified_error_on_exception(monkeypatch) -> None:
    run = _run()
    run.config = GraphConfig(nodes=[AgentRole.PLANNER], entry=AgentRole.PLANNER)

    async def boom(*args, **kwargs):
        raise RuntimeError("execute blew up")

    monkeypatch.setattr(run, "_execute", boom)

    result = await run.start(await _llm_returns(VALID_PLAN_JSON))

    assert run.phase == GraphPhase.FAILED
    assert run.classified_error is not None
    assert result.success is False


@pytest.mark.asyncio
async def test_start_handles_cancelled_error(monkeypatch) -> None:
    run = _run()
    run.config = GraphConfig(nodes=[AgentRole.PLANNER], entry=AgentRole.PLANNER)

    async def cancelled(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(run, "_execute", cancelled)

    result = await run.start(await _llm_returns(VALID_PLAN_JSON))

    assert run.phase == GraphPhase.FAILED
    assert result.success is False


@pytest.mark.asyncio
async def test_execute_full_pipeline_completes_successfully() -> None:
    plan_json = VALID_PLAN_JSON
    code_json = '{"files_changed": ["a.py"], "description": "done", "tests_added": true}'
    review_json = '{"approved": true, "score": 9.0, "issues": [], "suggestions": []}'

    responses = {
        AgentRole.PLANNER: plan_json,
        AgentRole.CODER: code_json,
        AgentRole.REVIEWER: review_json,
    }

    async def llm_call(messages, *args, **kwargs):
        text = " ".join(str(m) for m in messages)
        if "developer" in text.lower():
            return responses[AgentRole.CODER]
        if "reviewer" in text.lower():
            return responses[AgentRole.REVIEWER]
        return responses[AgentRole.PLANNER]

    config = GraphConfig(
        nodes=[AgentRole.PLANNER, AgentRole.CODER, AgentRole.REVIEWER],
        entry=AgentRole.PLANNER,
        edges=[
            GraphEdge(from_role=AgentRole.PLANNER, to_role=AgentRole.CODER),
            GraphEdge(from_role=AgentRole.CODER, to_role=AgentRole.REVIEWER),
        ],
        max_cycles=5,
    )
    run = GraphRun(task=GraphTask(description="task", workspace="/tmp"), config=config)

    result = await run.start(llm_call)

    assert run.phase == GraphPhase.COMPLETED
    assert result.success is True
    assert isinstance(run.plan, PlanOutput)
    assert isinstance(run.code, CodeOutput)
    assert isinstance(run.review, ReviewOutput)


@pytest.mark.asyncio
async def test_start_cancelled_error_cancels_running_node_runs(monkeypatch) -> None:
    from maistro.graph.node import NodeRun
    from maistro.graph.strategy import PlannerStrategy

    run = _run()
    run.config = GraphConfig(nodes=[AgentRole.PLANNER], entry=AgentRole.PLANNER)
    nr = NodeRun(
        run_id=run.run_id,
        role=AgentRole.PLANNER,
        strategy=PlannerStrategy(),
        model="default",
        system_prompt="sp",
        user_prompt="up",
    )
    nr.phase = NodePhase.RUNNING
    run.node_runs.append(nr)

    async def cancelled(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(run, "_execute", cancelled)

    await run.start(await _llm_returns(VALID_PLAN_JSON))

    assert nr._cancel_requested is True
    assert run.phase == GraphPhase.FAILED


@pytest.mark.asyncio
async def test_execute_runs_scout_when_configured() -> None:
    scout_json = '{"relevant_files": ["a.py"], "patterns": "mvc", "summary": "scouted"}'

    async def llm_call(messages, *args, **kwargs):
        text = " ".join(str(m) for m in messages)
        if "workspace analyst" in text.lower():
            return scout_json
        return VALID_PLAN_JSON

    config = GraphConfig(
        nodes=[AgentRole.PLANNER],
        entry=AgentRole.PLANNER,
        run_scout=True,
        max_cycles=1,
    )
    run = GraphRun(task=GraphTask(description="task", workspace="/tmp"), config=config)

    await run.start(llm_call)

    scout_runs = [nr for nr in run.node_runs if nr.role == AgentRole.SCOUT]
    assert len(scout_runs) == 1


@pytest.mark.asyncio
async def test_execute_fails_when_node_never_succeeds() -> None:
    async def llm_call(*args, **kwargs):
        return "not valid json at all"

    config = GraphConfig(nodes=[AgentRole.PLANNER], entry=AgentRole.PLANNER, max_cycles=1)
    run = GraphRun(task=GraphTask(description="task", workspace="/tmp"), config=config)

    result = await run.start(llm_call)

    assert run.phase == GraphPhase.FAILED
    assert result.success is False


class TestUpdatePipelineState:
    def test_skips_node_run_with_no_parsed_output(self) -> None:
        from maistro.graph.node import NodeRun
        from maistro.graph.strategy import PlannerStrategy

        run = _run()
        nr = NodeRun(
            run_id="r1",
            role=AgentRole.PLANNER,
            strategy=PlannerStrategy(),
            model="default",
            system_prompt="sp",
            user_prompt="up",
        )
        nr.parsed_output = None
        run._update_pipeline_state([nr])
        assert run.plan is None


class TestRouteNext:
    def test_skips_non_succeeded_node_runs(self) -> None:
        from maistro.graph.node import NodeRun
        from maistro.graph.strategy import PlannerStrategy

        run = _run()
        config = GraphConfig(
            nodes=[AgentRole.PLANNER],
            edges=[GraphEdge(from_role=AgentRole.PLANNER, to_role=AgentRole.CODER)],
        )
        nr = NodeRun(
            run_id="r1",
            role=AgentRole.PLANNER,
            strategy=PlannerStrategy(),
            model="default",
            system_prompt="sp",
            user_prompt="up",
        )
        nr.phase = NodePhase.FAILED
        assert run._route_next([nr], config, 0) == []


@pytest.mark.asyncio
async def test_execute_marks_failed_when_cancel_requested_mid_run() -> None:
    config = GraphConfig(nodes=[AgentRole.PLANNER], entry=AgentRole.PLANNER, max_cycles=5)
    run = GraphRun(task=GraphTask(description="task", workspace="/tmp"), config=config)
    run._cancel_requested = True

    result = await run.start(await _llm_returns(VALID_PLAN_JSON))

    assert run.phase == GraphPhase.FAILED
    assert result.success is False
