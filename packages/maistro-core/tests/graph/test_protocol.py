"""Tests for the graph execution protocol: phases, strategy, node, run."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from maistro.graph.executor import run_graph
from maistro.graph.node import IterationBudget, NodeRun
from maistro.graph.phases import TERMINAL_GRAPH_PHASES, TERMINAL_NODE_PHASES, GraphPhase, NodePhase
from maistro.graph.run import GraphRun, evaluate_condition
from maistro.graph.strategy import (
    STRATEGY_REGISTRY,
    CoderStrategy,
    PlannerStrategy,
    get_strategy,
)
from maistro.graph.types import (
    AgentRole,
    CodeOutput,
    GraphBlackboard,
    GraphConfig,
    GraphEdge,
    GraphTask,
    HyperagentOutput,
    PlanOutput,
    ReviewOutput,
    ScoutOutput,
)


def _make_plan_json(summary: str = "plan", n_subtasks: int = 1) -> str:
    subtasks = [
        {"title": f"t{i}", "description": f"d{i}", "file_paths": []} for i in range(n_subtasks)
    ]
    return json.dumps({"summary": summary, "subtasks": subtasks, "estimated_files": []})


def _make_code_json(files: list[str] | None = None, tests: bool = True) -> str:
    return json.dumps(
        {"files_changed": files or ["main.py"], "description": "impl", "tests_added": tests}
    )


def _make_review_json(approved: bool = True, score: float = 8.0) -> str:
    return json.dumps({"approved": approved, "score": score, "issues": [], "suggestions": []})


class _RecordingLlm:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.call_count = 0
        self.calls: list[list[dict]] = []

    async def __call__(self, messages: list[dict], **kwargs: Any) -> str:
        self.call_count += 1
        self.calls.append(messages)
        if self.call_count > len(self.responses):
            return self.responses[-1]
        return self.responses[self.call_count - 1]


class _FailingLlm:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error if error is not None else RuntimeError("boom")
        self.call_count = 0

    async def __call__(self, messages: list[dict], **kwargs: Any) -> str:
        self.call_count += 1
        raise self.error


class TestPhases:
    def test_node_phase_values(self):
        assert NodePhase.PENDING == "pending"
        assert NodePhase.SUCCEEDED == "succeeded"
        assert NodePhase.FAILED == "failed"
        assert NodePhase.CANCELLED == "cancelled"

    def test_graph_phase_values(self):
        assert GraphPhase.IDLE == "idle"
        assert GraphPhase.RUNNING == "running"
        assert GraphPhase.COMPLETED == "completed"
        assert GraphPhase.FAILED == "failed"

    def test_terminal_node_phases(self):
        assert NodePhase.SUCCEEDED in TERMINAL_NODE_PHASES
        assert NodePhase.FAILED in TERMINAL_NODE_PHASES
        assert NodePhase.PENDING not in TERMINAL_NODE_PHASES

    def test_terminal_graph_phases(self):
        assert GraphPhase.COMPLETED in TERMINAL_GRAPH_PHASES
        assert GraphPhase.FAILED in TERMINAL_GRAPH_PHASES
        assert GraphPhase.IDLE not in TERMINAL_GRAPH_PHASES


class TestIterationBudget:
    def test_consume_within_budget(self):
        budget = IterationBudget(5)
        assert budget.consume() is True
        assert budget.remaining == 4

    def test_consume_exhausts_budget(self):
        budget = IterationBudget(2)
        budget.consume()
        budget.consume()
        assert budget.exhausted is True
        assert budget.consume() is False

    def test_consume_multi(self):
        budget = IterationBudget(10)
        assert budget.consume(5) is True
        assert budget.remaining == 5

    def test_consume_over_budget(self):
        budget = IterationBudget(3)
        assert budget.consume(5) is False


class TestStrategyRegistry:
    def test_all_roles_registered(self):
        for role in AgentRole:
            assert role in STRATEGY_REGISTRY, f"Missing strategy for {role}"

    def test_get_strategy_returns_valid(self):
        for role in AgentRole:
            s = get_strategy(role)
            assert s.role == role
            assert s.output_type is not None

    def test_planner_output_type(self):
        assert get_strategy(AgentRole.PLANNER).output_type == PlanOutput

    def test_coder_output_type(self):
        assert get_strategy(AgentRole.CODER).output_type == CodeOutput

    def test_reviewer_output_type(self):
        assert get_strategy(AgentRole.REVIEWER).output_type == ReviewOutput

    def test_scout_output_type(self):
        assert get_strategy(AgentRole.SCOUT).output_type == ScoutOutput


class TestPlannerStrategy:
    def test_build_prompt(self):
        s = PlannerStrategy()
        task = GraphTask(description="Fix bug", workspace="/tmp", constraints=["no external deps"])
        bb = GraphBlackboard(task_objective="Fix bug", workspace="/tmp")
        prompt = s.build_user_prompt(task, bb, None, None, None)
        assert "Fix bug" in prompt
        assert "no external deps" in prompt

    def test_score_output(self):
        s = PlannerStrategy()
        plan = PlanOutput(
            summary="s", subtasks=[{"title": "t", "description": "d", "file_paths": []}]
        )
        assert s.score_output(plan) == 1.0


class TestCoderStrategy:
    def test_build_prompt_with_plan(self):
        s = CoderStrategy()
        task = GraphTask(description="Implement X", workspace="/tmp")
        bb = GraphBlackboard(task_objective="Implement X", workspace="/tmp")
        plan = PlanOutput(
            summary="do X",
            subtasks=[{"title": "step1", "description": "code it", "file_paths": []}],
        )
        prompt = s.build_user_prompt(task, bb, plan, None, None)
        assert "do X" in prompt
        assert "step1" in prompt

    def test_build_prompt_without_plan(self):
        s = CoderStrategy()
        task = GraphTask(description="Implement X", workspace="/tmp")
        bb = GraphBlackboard(task_objective="X", workspace="/tmp")
        prompt = s.build_user_prompt(task, bb, None, None, None)
        assert "Implement X" in prompt


class TestNodeRun:
    @pytest.mark.asyncio
    async def test_succeeds(self):
        llm = _RecordingLlm([_make_plan_json("test plan")])
        nr = NodeRun(
            run_id="r1",
            role=AgentRole.PLANNER,
            strategy=PlannerStrategy(),
            system_prompt="sys",
            user_prompt="usr",
        )
        await nr.execute(llm)
        assert nr.phase == NodePhase.SUCCEEDED
        assert nr.parsed_output is not None
        assert nr.raw_response is not None
        assert nr.started_at is not None
        assert nr.completed_at is not None
        assert nr.duration_s is not None
        assert nr.duration_s >= 0

    @pytest.mark.asyncio
    async def test_records_input(self):
        llm = _RecordingLlm([_make_plan_json()])
        nr = NodeRun(
            run_id="r1",
            role=AgentRole.PLANNER,
            strategy=PlannerStrategy(),
            system_prompt="my system prompt",
            user_prompt="my user prompt",
        )
        await nr.execute(llm)
        assert nr.system_prompt == "my system prompt"
        assert nr.user_prompt == "my user prompt"
        assert nr.blackboard_snapshot is None

    @pytest.mark.asyncio
    async def test_records_raw_response(self):
        raw = _make_plan_json("hello world")
        llm = _RecordingLlm([raw])
        nr = NodeRun(
            run_id="r1",
            role=AgentRole.PLANNER,
            strategy=PlannerStrategy(),
            system_prompt="sys",
            user_prompt="usr",
        )
        await nr.execute(llm)
        assert nr.raw_response == raw

    @pytest.mark.asyncio
    async def test_fails_on_bad_json(self):
        llm = _RecordingLlm(["not json at all"] * 5)
        nr = NodeRun(
            run_id="r1",
            role=AgentRole.PLANNER,
            strategy=PlannerStrategy(),
            system_prompt="sys",
            user_prompt="usr",
            max_retries=3,
        )
        await nr.execute(llm)
        assert nr.phase == NodePhase.FAILED
        assert nr.parse_error is not None

    @pytest.mark.asyncio
    async def test_retry_on_transient_error(self):
        llm = _FailingLlm(ConnectionError("Connection reset by peer"))
        nr = NodeRun(
            run_id="r1",
            role=AgentRole.PLANNER,
            strategy=PlannerStrategy(),
            system_prompt="sys",
            user_prompt="usr",
            max_retries=3,
        )
        from maistro.resilience.backoff import BackoffConfig

        await nr.execute(llm, backoff_config=BackoffConfig(base_delay=0.01, max_delay=0.05))
        assert nr.phase == NodePhase.FAILED
        assert nr.retry_count > 0
        assert len(nr.error_classifications) > 0

    @pytest.mark.asyncio
    async def test_phase_log_records_transitions(self):
        llm = _RecordingLlm([_make_plan_json()])
        nr = NodeRun(
            run_id="r1",
            role=AgentRole.PLANNER,
            strategy=PlannerStrategy(),
            system_prompt="sys",
            user_prompt="usr",
        )
        await nr.execute(llm)
        old_phases = [p for p, _ in nr.phase_log]
        assert NodePhase.PENDING in old_phases
        assert NodePhase.RUNNING in old_phases
        assert nr.phase == NodePhase.SUCCEEDED

    @pytest.mark.asyncio
    async def test_beam_search(self):
        responses = [
            _make_plan_json("weak", 1),
            _make_plan_json("strong", 5),
            _make_plan_json("medium", 3),
        ]
        llm = _RecordingLlm(responses)
        nr = NodeRun(
            run_id="r1",
            role=AgentRole.PLANNER,
            strategy=PlannerStrategy(),
            system_prompt="sys",
            user_prompt="usr",
            beam_width=3,
        )
        await nr.execute(llm)
        assert nr.phase == NodePhase.SUCCEEDED
        assert len(nr.beam_candidates) == 3
        assert nr.beam_selected >= 0
        assert nr.parsed_output is not None
        assert isinstance(nr.parsed_output, PlanOutput)
        assert nr.parsed_output.summary == "strong"

    @pytest.mark.asyncio
    async def test_beam_all_parse_failures_finishes_failed(self):
        llm = _RecordingLlm(["not json", "still not json", "also not json"])
        nr = NodeRun(
            run_id="r1",
            role=AgentRole.PLANNER,
            strategy=PlannerStrategy(),
            system_prompt="sys",
            user_prompt="usr",
            beam_width=3,
        )

        await nr.execute(llm)

        assert nr.phase == NodePhase.FAILED
        assert nr.parse_error == "all beam candidates failed to parse"
        assert len(nr.beam_candidates) == 3
        assert all(candidate.parse_error == "failed to parse" for candidate in nr.beam_candidates)
        assert nr.to_result().success is False

    @pytest.mark.asyncio
    async def test_beam_mixed_parse_failures_selects_best_valid_candidate(self):
        llm = _RecordingLlm(["not json", _make_plan_json("strong", 5), _make_plan_json("weak", 1)])
        nr = NodeRun(
            run_id="r1",
            role=AgentRole.PLANNER,
            strategy=PlannerStrategy(),
            system_prompt="sys",
            user_prompt="usr",
            beam_width=3,
        )

        await nr.execute(llm)

        assert nr.phase == NodePhase.SUCCEEDED
        assert nr.beam_selected == 1
        assert isinstance(nr.parsed_output, PlanOutput)
        assert nr.parsed_output.summary == "strong"
        assert nr.beam_candidates[0].parse_error == "failed to parse"

    @pytest.mark.asyncio
    async def test_beam_all_provider_errors_finishes_failed_with_candidate_errors(self):
        llm = _FailingLlm(ConnectionError("beam provider down"))
        nr = NodeRun(
            run_id="r1",
            role=AgentRole.PLANNER,
            strategy=PlannerStrategy(),
            system_prompt="sys",
            user_prompt="usr",
            beam_width=3,
        )

        await nr.execute(llm)

        assert nr.phase == NodePhase.FAILED
        assert llm.call_count == 3
        assert len(nr.beam_candidates) == 3
        assert all(candidate.error is not None for candidate in nr.beam_candidates)
        assert "beam provider down" in nr.to_result().output

    @pytest.mark.asyncio
    async def test_beam_scorer_failure_finishes_failed_with_candidate_errors(self):
        class _ScoringBoomPlanner(PlannerStrategy):
            def score_output(self, output: Any) -> float:
                raise RuntimeError("score blew up")

        llm = _RecordingLlm([_make_plan_json("a"), _make_plan_json("b")])
        nr = NodeRun(
            run_id="r1",
            role=AgentRole.PLANNER,
            strategy=_ScoringBoomPlanner(),
            system_prompt="sys",
            user_prompt="usr",
            beam_width=2,
        )

        await nr.execute(llm)

        assert nr.phase == NodePhase.FAILED
        assert len(nr.beam_candidates) == 2
        assert all(candidate.error is not None for candidate in nr.beam_candidates)
        assert "score blew up" in nr.to_result().output

    @pytest.mark.asyncio
    async def test_iteration_budget_consumed(self):
        llm = _RecordingLlm([_make_plan_json()])
        budget = IterationBudget(10)
        nr = NodeRun(
            run_id="r1",
            role=AgentRole.PLANNER,
            strategy=PlannerStrategy(),
            system_prompt="sys",
            user_prompt="usr",
        )
        await nr.execute(llm, iteration_budget=budget)
        assert budget.consumed >= 1

    @pytest.mark.asyncio
    async def test_single_budget_exhausted_fails_without_calling_llm(self):
        llm = _RecordingLlm([_make_plan_json("should-not-run")])
        nr = NodeRun(
            run_id="r1",
            role=AgentRole.PLANNER,
            strategy=PlannerStrategy(),
            system_prompt="sys",
            user_prompt="usr",
        )

        await nr.execute(llm, iteration_budget=IterationBudget(0))

        assert nr.phase == NodePhase.FAILED
        assert llm.call_count == 0
        assert nr.to_result().success is False
        assert "Iteration budget exhausted" in nr.to_result().output

    @pytest.mark.asyncio
    async def test_single_open_circuit_fails_without_calling_llm(self):
        from maistro.agents.circuit_breaker import CircuitBreaker

        llm = _RecordingLlm([_make_plan_json("should-not-run")])
        nr = NodeRun(
            run_id="r1",
            role=AgentRole.PLANNER,
            strategy=PlannerStrategy(),
            system_prompt="sys",
            user_prompt="usr",
        )
        nr.circuit = CircuitBreaker(failure_threshold=1, recovery_timeout=999.0, name="unit")
        nr.circuit.record_failure()

        await nr.execute(llm)

        assert nr.phase == NodePhase.FAILED
        assert llm.call_count == 0
        assert "Circuit breaker open for node" in nr.to_result().output

    @pytest.mark.asyncio
    async def test_single_cancellation_before_attempt_is_terminal_cancelled(self):
        llm = _RecordingLlm([_make_plan_json("should-not-run")])
        nr = NodeRun(
            run_id="r1",
            role=AgentRole.PLANNER,
            strategy=PlannerStrategy(),
            system_prompt="sys",
            user_prompt="usr",
        )
        nr.cancel()

        await nr.execute(llm)

        assert nr.phase == NodePhase.CANCELLED
        assert llm.call_count == 0
        assert nr.completed_at is not None
        assert nr.duration_s is not None

    @pytest.mark.asyncio
    async def test_single_timeout_fails_with_timeout_classification(self):
        from maistro.resilience.classifier import ErrorCategory

        never_finishes = asyncio.Event()

        async def _slow(messages: list[dict], **kwargs: Any) -> str:
            await never_finishes.wait()
            return _make_plan_json("too-late")

        nr = NodeRun(
            run_id="r1",
            role=AgentRole.PLANNER,
            strategy=PlannerStrategy(),
            system_prompt="sys",
            user_prompt="usr",
            max_retries=1,
        )

        await nr.execute(_slow, timeout=0.001)

        assert nr.phase == NodePhase.FAILED
        assert nr.classified_error is not None
        assert nr.classified_error.category == ErrorCategory.TIMEOUT
        assert nr.retry_count == 0

    @pytest.mark.asyncio
    async def test_single_retryable_provider_failure_attempt_accounting(self):
        from maistro.resilience.backoff import BackoffConfig

        llm = _FailingLlm(ConnectionError("Connection reset by peer"))
        nr = NodeRun(
            run_id="r1",
            role=AgentRole.PLANNER,
            strategy=PlannerStrategy(),
            system_prompt="sys",
            user_prompt="usr",
            max_retries=2,
        )

        await nr.execute(llm, backoff_config=BackoffConfig(base_delay=0.0, max_delay=0.0))

        assert nr.phase == NodePhase.FAILED
        assert llm.call_count == 2
        assert nr.retry_count == 1
        assert len(nr.error_classifications) == 2

    @pytest.mark.asyncio
    async def test_to_result_success(self):
        llm = _RecordingLlm([_make_plan_json("ok")])
        nr = NodeRun(
            run_id="r1",
            role=AgentRole.PLANNER,
            strategy=PlannerStrategy(),
            system_prompt="sys",
            user_prompt="usr",
        )
        await nr.execute(llm)
        result = nr.to_result()
        assert result.success is True
        assert result.role == AgentRole.PLANNER

    @pytest.mark.asyncio
    async def test_never_raises(self):
        llm = _FailingLlm(RuntimeError("catastrophic"))
        nr = NodeRun(
            run_id="r1",
            role=AgentRole.PLANNER,
            strategy=PlannerStrategy(),
            system_prompt="sys",
            user_prompt="usr",
            max_retries=1,
        )
        from maistro.resilience.backoff import BackoffConfig

        await nr.execute(llm, backoff_config=BackoffConfig(base_delay=0.0, max_delay=0.0))
        assert nr.phase == NodePhase.FAILED


class _UsageResult:
    """LLM result object that reports token usage (OpenAI-style)."""

    def __init__(self, text: str, prompt_tokens: int, completion_tokens: int) -> None:
        self.text = text
        self.usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        }


class _UsageReportingLlm:
    """LLM client that returns usage-bearing result objects."""

    def __init__(self, responses: list[_UsageResult]) -> None:
        self.responses = list(responses)
        self.call_count = 0

    async def __call__(self, messages: list[dict], **kwargs: Any) -> Any:
        self.call_count += 1
        idx = min(self.call_count - 1, len(self.responses) - 1)
        return self.responses[idx]


class TestNodeFailureEventDelivery:
    @pytest.mark.asyncio
    async def test_node_failed_event_delivered_to_subscriber(self):
        """node_failed must be reliably delivered (awaited), not fire-and-forget."""
        received: list[Any] = []

        async def emit(event: Any) -> None:
            received.append(event)

        llm = _FailingLlm(RuntimeError("catastrophic"))
        nr = NodeRun(
            run_id="r1",
            role=AgentRole.PLANNER,
            strategy=PlannerStrategy(),
            system_prompt="sys",
            user_prompt="usr",
            max_retries=1,
        )
        nr._emit_event = emit
        from maistro.resilience.backoff import BackoffConfig

        await nr.execute(llm, backoff_config=BackoffConfig(base_delay=0.0, max_delay=0.0))

        assert nr.phase == NodePhase.FAILED
        # By the time execute() returns, the failure event must already be delivered.
        types = [e.type for e in received]
        assert "node_failed" in types, f"node_failed not delivered; got {types}"
        failed = next(e for e in received if e.type == "node_failed")
        assert failed.run_id == "r1"
        assert failed.role == AgentRole.PLANNER.value

    @pytest.mark.asyncio
    async def test_node_failed_emit_error_does_not_propagate(self):
        """A failing subscriber must not break the node lifecycle."""

        async def emit(event: Any) -> None:
            if event.type == "node_failed":
                raise RuntimeError("subscriber blew up")

        llm = _FailingLlm(RuntimeError("catastrophic"))
        nr = NodeRun(
            run_id="r1",
            role=AgentRole.PLANNER,
            strategy=PlannerStrategy(),
            system_prompt="sys",
            user_prompt="usr",
            max_retries=1,
        )
        nr._emit_event = emit
        from maistro.resilience.backoff import BackoffConfig

        await nr.execute(llm, backoff_config=BackoffConfig(base_delay=0.0, max_delay=0.0))
        assert nr.phase == NodePhase.FAILED


class TestNodeTokenAccounting:
    @pytest.mark.asyncio
    async def test_single_path_records_token_usage(self):
        llm = _UsageReportingLlm([_UsageResult(_make_plan_json("ok"), 120, 45)])
        nr = NodeRun(
            run_id="r1",
            role=AgentRole.PLANNER,
            strategy=PlannerStrategy(),
            system_prompt="sys",
            user_prompt="usr",
        )
        await nr.execute(llm)
        assert nr.phase == NodePhase.SUCCEEDED
        assert nr.tokens_in == 120
        assert nr.tokens_out == 45

    @pytest.mark.asyncio
    async def test_single_path_plain_str_keeps_zero_tokens(self):
        """Backwards compatible: a str-returning client reports zero usage."""
        llm = _RecordingLlm([_make_plan_json("ok")])
        nr = NodeRun(
            run_id="r1",
            role=AgentRole.PLANNER,
            strategy=PlannerStrategy(),
            system_prompt="sys",
            user_prompt="usr",
        )
        await nr.execute(llm)
        assert nr.phase == NodePhase.SUCCEEDED
        assert nr.tokens_in == 0
        assert nr.tokens_out == 0

    @pytest.mark.asyncio
    async def test_beam_path_records_token_usage(self):
        llm = _UsageReportingLlm(
            [
                _UsageResult(_make_plan_json("weak", 1), 100, 10),
                _UsageResult(_make_plan_json("strong", 5), 100, 20),
                _UsageResult(_make_plan_json("medium", 3), 100, 30),
            ]
        )
        nr = NodeRun(
            run_id="r1",
            role=AgentRole.PLANNER,
            strategy=PlannerStrategy(),
            system_prompt="sys",
            user_prompt="usr",
            beam_width=3,
        )
        await nr.execute(llm)
        assert nr.phase == NodePhase.SUCCEEDED
        # Beam accounting sums usage across all candidates.
        assert nr.tokens_in == 300
        assert nr.tokens_out == 60
        assert sum(c.tokens_used for c in nr.beam_candidates) == 360


class TestGraphRun:
    @pytest.mark.asyncio
    async def test_happy_path_planner_coder_reviewer(self):
        llm = _RecordingLlm(
            [
                _make_plan_json("test plan"),
                _make_code_json(),
                _make_review_json(True, 9.0),
            ]
        )
        task = GraphTask(
            description="Build feature",
            workspace="/tmp",
            graph_config=GraphConfig(
                nodes=[AgentRole.PLANNER, AgentRole.CODER, AgentRole.REVIEWER],
                edges=[
                    GraphEdge(from_role=AgentRole.PLANNER, to_role=AgentRole.CODER),
                    GraphEdge(from_role=AgentRole.CODER, to_role=AgentRole.REVIEWER),
                ],
            ),
        )
        run = GraphRun(task=task, config=task.graph_config)
        result = await run.start(llm)
        assert result.success is True
        assert run.phase == GraphPhase.COMPLETED
        assert len(run.node_runs) == 3
        assert all(nr.phase == NodePhase.SUCCEEDED for nr in run.node_runs)

    @pytest.mark.asyncio
    async def test_phase_transitions(self):
        llm = _RecordingLlm([_make_plan_json()])
        task = GraphTask(
            description="task",
            workspace="/tmp",
            graph_config=GraphConfig(nodes=[AgentRole.PLANNER]),
        )
        run = GraphRun(task=task, config=task.graph_config)
        await run.start(llm)
        old_phases = [p for p, _ in run.phase_log]
        assert GraphPhase.IDLE in old_phases
        assert GraphPhase.RUNNING in old_phases
        assert run.phase == GraphPhase.COMPLETED

    @pytest.mark.asyncio
    async def test_never_raises_on_error(self):
        llm = _FailingLlm(RuntimeError("total failure"))
        task = GraphTask(
            description="task",
            workspace="/tmp",
            graph_config=GraphConfig(nodes=[AgentRole.PLANNER]),
        )
        run = GraphRun(task=task, config=task.graph_config)
        from maistro.resilience.backoff import BackoffConfig

        result = await run.start(
            llm,
            max_retries=1,
            backoff_config=BackoffConfig(base_delay=0.0, max_delay=0.0),
        )
        assert result is not None
        assert result.success is False
        assert run.phase == GraphPhase.FAILED

    @pytest.mark.asyncio
    async def test_node_failure_recording(self):
        llm = _FailingLlm(RuntimeError("model error"))
        task = GraphTask(
            description="task",
            workspace="/tmp",
            graph_config=GraphConfig(nodes=[AgentRole.PLANNER]),
        )
        run = GraphRun(task=task, config=task.graph_config)
        from maistro.resilience.backoff import BackoffConfig

        await run.start(
            llm,
            max_retries=1,
            backoff_config=BackoffConfig(base_delay=0.0, max_delay=0.0),
        )
        assert len(run.node_runs) == 1
        nr = run.node_runs[0]
        assert nr.phase == NodePhase.FAILED
        assert nr.classified_error is not None
        assert nr.raw_response is None

    @pytest.mark.asyncio
    async def test_per_node_telemetry(self):
        llm = _RecordingLlm(
            [
                _make_plan_json("p"),
                _make_code_json(),
            ]
        )
        task = GraphTask(
            description="task",
            workspace="/tmp",
            graph_config=GraphConfig(
                nodes=[AgentRole.PLANNER, AgentRole.CODER],
                edges=[GraphEdge(from_role=AgentRole.PLANNER, to_role=AgentRole.CODER)],
            ),
        )
        run = GraphRun(task=task, config=task.graph_config)
        await run.start(llm)

        planner_runs = run.node_runs_for_role(AgentRole.PLANNER)
        assert len(planner_runs) == 1
        assert planner_runs[0].started_at is not None
        assert planner_runs[0].duration_s is not None
        assert planner_runs[0].system_prompt != ""
        assert planner_runs[0].user_prompt != ""
        assert planner_runs[0].raw_response is not None

        coder_runs = run.node_runs_for_role(AgentRole.CODER)
        assert len(coder_runs) == 1
        assert coder_runs[0].parsed_output is not None

    @pytest.mark.asyncio
    async def test_event_callbacks(self):
        events: list = []
        llm = _RecordingLlm([_make_plan_json()])

        async def capture(event: Any) -> None:
            events.append(event)

        task = GraphTask(
            description="task",
            workspace="/tmp",
            graph_config=GraphConfig(nodes=[AgentRole.PLANNER]),
        )
        run = GraphRun(task=task, config=task.graph_config, event_callbacks=[capture])
        await run.start(llm)

        event_types = [e.type for e in events]
        assert "graph_started" in event_types
        assert "node_started" in event_types
        assert "node_completed" in event_types
        assert "graph_completed" in event_types

    @pytest.mark.asyncio
    async def test_total_tokens(self):
        llm = _RecordingLlm([_make_plan_json()])
        task = GraphTask(
            description="task",
            workspace="/tmp",
            graph_config=GraphConfig(nodes=[AgentRole.PLANNER]),
        )
        run = GraphRun(task=task, config=task.graph_config)
        await run.start(llm)
        assert run.total_tokens() >= 0

    @pytest.mark.asyncio
    async def test_success_rate(self):
        llm = _RecordingLlm([_make_plan_json()])
        task = GraphTask(
            description="task",
            workspace="/tmp",
            graph_config=GraphConfig(nodes=[AgentRole.PLANNER]),
        )
        run = GraphRun(task=task, config=task.graph_config)
        await run.start(llm)
        assert run.success_rate() == 1.0


class TestRunGraphBackwardCompat:
    @pytest.mark.asyncio
    async def test_existing_signature(self):
        llm = _RecordingLlm([_make_plan_json()])
        task = GraphTask(
            description="task",
            workspace="/tmp",
            graph_config=GraphConfig(nodes=[AgentRole.PLANNER]),
        )
        result = await run_graph(task, llm, model="test-model")
        assert result is not None
        assert isinstance(result, HyperagentOutput)

    @pytest.mark.asyncio
    async def test_parallel_generations(self):
        llm = _RecordingLlm(
            [
                _make_plan_json("weak", 1),
                _make_plan_json("strong", 5),
                _make_plan_json("ok", 2),
            ]
        )
        task = GraphTask(
            description="task",
            workspace="/tmp",
            graph_config=GraphConfig(nodes=[AgentRole.PLANNER]),
        )
        result = await run_graph(task, llm, parallel_generations=3)
        assert result is not None
        assert result.success is True


class TestEvaluateCondition:
    def test_equality(self):
        assert evaluate_condition(
            "review.score == 8.0", None, None, ReviewOutput(approved=True, score=8.0)
        )

    def test_greater_than(self):
        assert evaluate_condition(
            "review.score > 5.0", None, None, ReviewOutput(approved=True, score=8.0)
        )

    def test_unknown_path(self):
        assert evaluate_condition("foo.bar == 1", None, None, None) is False
