"""Tests for maistro.graph.node — async node execution engine."""

from __future__ import annotations

import asyncio

from maistro.graph.events import GraphEvent
from maistro.graph.node import (
    BeamCandidate,
    IterationBudget,
    NodeRun,
    _blackboard_prefix,
    _build_system_prompt,
    _coerce_int,
    _normalize_llm_result,
    _read_usage,
    _strip_json_block,
    _to_agent_role,
)
from maistro.graph.phases import NodePhase
from maistro.graph.strategy import PlannerStrategy
from maistro.graph.types import (
    AgentRole,
    GraphBlackboard,
    NodeConfig,
    PlanOutput,
    ScoutContext,
    ToolEvaluation,
)
from maistro.resilience.backoff import BackoffConfig

# --- module-level helpers ----------------------------------------------------


class TestStripJsonBlock:
    def test_extracts_fenced_json(self) -> None:
        assert _strip_json_block('```json\n{"a": 1}\n```') == '{"a": 1}'

    def test_no_fence_returns_stripped_text(self) -> None:
        assert _strip_json_block('  {"a": 1}  ') == '{"a": 1}'


class TestCoerceInt:
    def test_valid_int_string(self) -> None:
        assert _coerce_int("5") == 5

    def test_negative_clamped_to_zero(self) -> None:
        assert _coerce_int(-5) == 0

    def test_non_numeric_returns_zero(self) -> None:
        assert _coerce_int("not-a-number") == 0

    def test_none_returns_zero(self) -> None:
        assert _coerce_int(None) == 0


class TestReadUsage:
    def test_none_usage_returns_zero_zero(self) -> None:
        assert _read_usage(None) == (0, 0)

    def test_dict_usage_openai_shape(self) -> None:
        assert _read_usage({"prompt_tokens": 10, "completion_tokens": 20}) == (10, 20)

    def test_dict_usage_anthropic_shape(self) -> None:
        assert _read_usage({"input_tokens": 3, "output_tokens": 7}) == (3, 7)

    def test_dict_usage_missing_keys_returns_zero(self) -> None:
        assert _read_usage({"unrelated": 1}) == (0, 0)

    def test_object_usage_with_attributes(self) -> None:
        class Usage:
            tokens_in = 4
            tokens_out = 9

        assert _read_usage(Usage()) == (4, 9)

    def test_object_usage_missing_attributes_returns_zero(self) -> None:
        class Empty:
            pass

        assert _read_usage(Empty()) == (0, 0)


class TestNormalizeLlmResult:
    def test_plain_string(self) -> None:
        assert _normalize_llm_result("hello") == ("hello", 0, 0)

    def test_two_tuple_with_usage(self) -> None:
        result = ("hi", {"prompt_tokens": 1, "completion_tokens": 2})
        assert _normalize_llm_result(result) == ("hi", 1, 2)

    def test_dict_with_text_and_usage(self) -> None:
        result = {"text": "abc", "usage": {"input_tokens": 5, "output_tokens": 6}}
        assert _normalize_llm_result(result) == ("abc", 5, 6)

    def test_dict_with_content_fallback(self) -> None:
        result = {"content": "xyz"}
        assert _normalize_llm_result(result) == ("xyz", 0, 0)

    def test_object_with_text_attr(self) -> None:
        class Obj:
            text = "obj-text"
            usage = None

        assert _normalize_llm_result(Obj()) == ("obj-text", 0, 0)

    def test_object_with_content_attr_fallback(self) -> None:
        class Obj:
            text = None
            content = "obj-content"
            usage = None

        assert _normalize_llm_result(Obj()) == ("obj-content", 0, 0)


class TestToAgentRole:
    def test_already_agent_role_returns_unchanged(self) -> None:
        assert _to_agent_role(AgentRole.PLANNER) is AgentRole.PLANNER

    def test_valid_string_coerces(self) -> None:
        assert _to_agent_role("coder") is AgentRole.CODER

    def test_unknown_string_returns_none(self) -> None:
        assert _to_agent_role("totally-arbitrary-kind") is None


class TestBuildSystemPrompt:
    def test_uses_node_config_system_prompt_when_present(self) -> None:
        cfg = NodeConfig(role=AgentRole.PLANNER, system_prompt="custom prompt")
        prompt = _build_system_prompt(AgentRole.PLANNER, cfg)
        assert prompt.startswith("custom prompt")

    def test_falls_back_to_default_for_known_role(self) -> None:
        prompt = _build_system_prompt(AgentRole.PLANNER, None)
        assert "planner" in prompt.lower()

    def test_unknown_role_string_returns_empty_base(self) -> None:
        prompt = _build_system_prompt("arbitrary-kind", None)
        assert prompt == ""


class TestBlackboardPrefix:
    def test_none_blackboard_returns_empty_string(self) -> None:
        assert _blackboard_prefix(AgentRole.PLANNER, None) == ""

    def test_objective_only_returns_empty_string(self) -> None:
        bb = GraphBlackboard(task_objective="do thing", workspace="/ws")
        assert _blackboard_prefix(AgentRole.PLANNER, bb) == ""

    def test_scout_context_renders_relevant_files_and_patterns(self) -> None:
        bb = GraphBlackboard(
            task_objective="do thing",
            workspace="/ws",
            scout_context=ScoutContext(
                relevant_files=[f"f{i}.py" for i in range(15)],
                patterns="use repository pattern",
                similar_implementations=[f"impl{i}" for i in range(8)],
                raw_findings="found stuff",
            ),
        )
        prefix = _blackboard_prefix(AgentRole.PLANNER, bb)
        assert "Relevant files" in prefix
        assert "Patterns to follow" in prefix
        assert "Similar existing implementations" in prefix
        assert "Scout summary" in prefix

    def test_tool_evaluation_only_rendered_for_reviewer_role(self) -> None:
        te = ToolEvaluation(tests_passed=3, tests_failed=1, test_output="output here")
        bb = GraphBlackboard(task_objective="x", workspace="/ws", tool_evaluation=te)

        reviewer_prefix = _blackboard_prefix(AgentRole.REVIEWER, bb)
        assert "Sandbox Results" in reviewer_prefix

        planner_prefix = _blackboard_prefix(AgentRole.PLANNER, bb)
        assert "Sandbox Results" not in planner_prefix

    def test_node_annotation_rendered(self) -> None:
        bb = GraphBlackboard(
            task_objective="x",
            workspace="/ws",
            node_annotations={"planner": "focus on edge cases"},
        )
        prefix = _blackboard_prefix(AgentRole.PLANNER, bb)
        assert "Hyperagent Note for PLANNER" in prefix

    def test_iteration_greater_than_zero_rendered(self) -> None:
        bb = GraphBlackboard(
            task_objective="x",
            workspace="/ws",
            iteration=2,
            node_annotations={"planner": "note"},
        )
        prefix = _blackboard_prefix(AgentRole.PLANNER, bb)
        assert "Optimization Context" in prefix
        assert "Iteration 2" in prefix


# --- IterationBudget ----------------------------------------------------------


class TestIterationBudget:
    def test_consume_within_budget_returns_true(self) -> None:
        budget = IterationBudget(3)
        assert budget.consume() is True
        assert budget.consumed == 1
        assert budget.remaining == 2

    def test_consume_exceeding_budget_returns_false(self) -> None:
        budget = IterationBudget(1)
        assert budget.consume() is True
        assert budget.consume() is False
        assert budget.consumed == 1

    def test_exhausted_true_when_fully_consumed(self) -> None:
        budget = IterationBudget(1)
        budget.consume()
        assert budget.exhausted is True

    def test_max_iterations_property(self) -> None:
        budget = IterationBudget(7)
        assert budget.max_iterations == 7


# --- NodeRun.execute / _execute_single ---------------------------------------


def _planner_node(**overrides: object) -> NodeRun:
    defaults: dict[str, object] = {
        "run_id": "run-1",
        "role": AgentRole.PLANNER,
        "strategy": PlannerStrategy(),
        "system_prompt": "sys",
        "user_prompt": "usr",
        "max_retries": 3,
    }
    defaults.update(overrides)
    return NodeRun(**defaults)  # type: ignore[arg-type]


VALID_PLAN_JSON = '{"summary": "a plan", "subtasks": [{"title": "t", "description": "d"}]}'


async def _llm_returns(text: str) -> str:
    return text


class TestExecuteGuards:
    async def test_execute_noop_when_phase_not_pending(self) -> None:
        node = _planner_node()
        node.phase = NodePhase.SUCCEEDED
        await node.execute(lambda *a, **k: _llm_returns("x"))
        assert node.phase == NodePhase.SUCCEEDED

    async def test_strategy_resolved_via_get_strategy_when_none(self) -> None:
        node = _planner_node(strategy=None)

        async def llm_call(*args: object, **kwargs: object) -> str:
            return VALID_PLAN_JSON

        await node.execute(llm_call)
        assert node.strategy is not None
        assert node.phase == NodePhase.SUCCEEDED

    async def test_execute_emits_started_and_completed_events(self) -> None:
        events: list[GraphEvent] = []

        async def emit(event: GraphEvent) -> None:
            events.append(event)

        node = _planner_node()
        node._emit_event = emit

        async def llm_call(*args: object, **kwargs: object) -> str:
            return VALID_PLAN_JSON

        await node.execute(llm_call)
        kinds = [e.type for e in events]
        assert "node_started" in kinds
        assert "node_completed" in kinds
        assert node.duration_s is not None


class TestExecuteCancellation:
    async def test_cancelled_error_during_execute_marks_cancelled(self) -> None:
        events: list[GraphEvent] = []

        async def emit(event: GraphEvent) -> None:
            events.append(event)

        node = _planner_node()
        node._emit_event = emit

        async def llm_call(*args: object, **kwargs: object) -> str:
            raise asyncio.CancelledError()

        await node.execute(llm_call)
        assert node.phase == NodePhase.CANCELLED
        assert node.duration_s is not None
        assert any(e.type == "node_failed" for e in events)

    async def test_generic_exception_from_executor_finishes_failure(self) -> None:
        """A raw exception escaping _execute_single (not caught by its own
        per-attempt try/except) is handled by execute()'s outer guard."""
        node = _planner_node()

        async def boom(*args: object, **kwargs: object) -> None:
            raise RuntimeError("escaped the per-attempt try")

        node._execute_single = boom  # type: ignore[method-assign]

        await node.execute(lambda *a, **k: _llm_returns("unused"))
        assert node.phase == NodePhase.FAILED
        assert node.classified_error is not None

    async def test_cancel_requested_mid_loop_marks_cancelled(self) -> None:
        node = _planner_node(max_retries=3)
        call_count = 0

        async def llm_call(*args: object, **kwargs: object) -> str:
            nonlocal call_count
            call_count += 1
            node.cancel()
            raise TimeoutError("connection timed out, please retry")

        await node.execute(llm_call, backoff_config=BackoffConfig(base_delay=0.001, max_delay=0.01))
        assert node._cancel_requested is True
        assert node.phase == NodePhase.CANCELLED
        assert call_count == 1


class TestExecuteSingleFailureModes:
    async def test_circuit_breaker_open_finishes_failure(self) -> None:
        node = _planner_node()
        node.circuit.allow_request = lambda: False  # type: ignore[method-assign]

        async def llm_call(*args: object, **kwargs: object) -> str:
            return VALID_PLAN_JSON

        await node.execute(llm_call)
        assert node.phase == NodePhase.FAILED
        assert node.classified_error is not None

    async def test_iteration_budget_exhausted_finishes_failure(self) -> None:
        node = _planner_node()
        budget = IterationBudget(0)

        async def llm_call(*args: object, **kwargs: object) -> str:
            return VALID_PLAN_JSON

        await node.execute(llm_call, iteration_budget=budget)
        assert node.phase == NodePhase.FAILED

    async def test_parse_failure_retries_then_fails(self) -> None:
        node = _planner_node(max_retries=2)

        async def llm_call(*args: object, **kwargs: object) -> str:
            return "not json at all"

        await node.execute(llm_call)
        assert node.phase == NodePhase.FAILED
        assert node.parse_error is not None
        assert node.retry_count == 1

    async def test_parse_failure_then_success_on_retry(self) -> None:
        node = _planner_node(max_retries=2)
        attempts = 0

        async def llm_call(*args: object, **kwargs: object) -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return "garbage"
            return VALID_PLAN_JSON

        await node.execute(llm_call)
        assert node.phase == NodePhase.SUCCEEDED
        assert attempts == 2

    async def test_non_retryable_exception_finishes_failure_immediately(self) -> None:
        node = _planner_node(max_retries=3)
        attempts = 0

        async def llm_call(*args: object, **kwargs: object) -> str:
            nonlocal attempts
            attempts += 1
            raise ValueError("totally non-retryable and unrecognized")

        await node.execute(llm_call)
        assert node.phase == NodePhase.FAILED
        assert attempts == 1

    async def test_retryable_exception_retries_then_succeeds(self) -> None:
        node = _planner_node(max_retries=3)
        attempts = 0

        async def llm_call(*args: object, **kwargs: object) -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 2:
                raise TimeoutError("connection timed out, please retry")
            return VALID_PLAN_JSON

        await node.execute(llm_call, backoff_config=BackoffConfig(base_delay=0.001, max_delay=0.01))
        assert node.phase == NodePhase.SUCCEEDED
        assert attempts == 2
        assert node.retry_count == 1

    async def test_negative_backoff_delay_finishes_failure(self) -> None:
        node = _planner_node(max_retries=3)

        async def llm_call(*args: object, **kwargs: object) -> str:
            raise TimeoutError("connection timed out, please retry")

        import maistro.graph.node as node_module

        original = node_module.compute_backoff
        node_module.compute_backoff = lambda *a, **k: -1.0  # type: ignore[assignment]
        try:
            await node.execute(llm_call)
        finally:
            node_module.compute_backoff = original
        assert node.phase == NodePhase.FAILED

    async def test_retrying_emits_node_retrying_event(self) -> None:
        events: list[GraphEvent] = []

        async def emit(event: GraphEvent) -> None:
            events.append(event)

        node = _planner_node(max_retries=3)
        node._emit_event = emit
        attempts = 0

        async def llm_call(*args: object, **kwargs: object) -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 2:
                raise TimeoutError("connection timed out, please retry")
            return VALID_PLAN_JSON

        await node.execute(llm_call, backoff_config=BackoffConfig(base_delay=0.001, max_delay=0.01))
        assert any(e.type == "node_retrying" for e in events)

    async def test_retry_loop_exhausted_without_success_finishes_failure(self) -> None:
        node = _planner_node(max_retries=2)

        async def llm_call(*args: object, **kwargs: object) -> str:
            raise TimeoutError("connection timed out, please retry")

        await node.execute(llm_call, backoff_config=BackoffConfig(base_delay=0.001, max_delay=0.01))
        assert node.phase == NodePhase.FAILED
        assert node.classified_error is not None


class TestFinishFailureEmitSwallowsError:
    async def test_emit_exception_during_failure_is_swallowed(self) -> None:
        node = _planner_node()

        async def emit(event: GraphEvent) -> None:
            if event.type == "node_failed":
                raise RuntimeError("emit boom")

        node._emit_event = emit

        async def llm_call(*args: object, **kwargs: object) -> str:
            raise ValueError("non-retryable")

        await node.execute(llm_call)
        assert node.phase == NodePhase.FAILED


# --- Beam search --------------------------------------------------------------


class TestExecuteBeam:
    async def test_beam_selects_best_scoring_candidate(self) -> None:
        node = _planner_node(beam_width=3)
        plan_one = '{"summary": "s", "subtasks": [{"title": "t", "description": "d"}]}'
        plan_three = (
            '{"summary": "s", "subtasks": ['
            '{"title": "t1", "description": "d1"}, '
            '{"title": "t2", "description": "d2"}, '
            '{"title": "t3", "description": "d3"}]}'
        )

        call_index = 0

        async def llm_call(*args: object, **kwargs: object) -> str:
            nonlocal call_index
            call_index += 1
            return plan_three if call_index == 1 else plan_one

        await node.execute(llm_call)
        assert node.phase == NodePhase.SUCCEEDED
        assert len(node.beam_candidates) == 3
        assert node.beam_selected >= 0
        assert node.score == 3.0

    async def test_beam_attempt_exception_recorded_as_candidate_error(self) -> None:
        node = _planner_node(beam_width=2)
        call_index = 0

        async def llm_call(*args: object, **kwargs: object) -> str:
            nonlocal call_index
            call_index += 1
            if call_index == 1:
                raise RuntimeError("beam attempt failed")
            return VALID_PLAN_JSON

        await node.execute(llm_call)
        assert node.phase == NodePhase.SUCCEEDED
        errored = [c for c in node.beam_candidates if c.error is not None]
        assert len(errored) == 1

    async def test_beam_all_candidates_fail_finishes_failure(self) -> None:
        node = _planner_node(beam_width=2)

        async def llm_call(*args: object, **kwargs: object) -> str:
            raise RuntimeError("always fails")

        await node.execute(llm_call)
        assert node.phase == NodePhase.FAILED

    async def test_beam_attempt_iteration_budget_exhausted_counts_as_failure(self) -> None:
        node = _planner_node(beam_width=2)
        budget = IterationBudget(0)

        async def llm_call(*args: object, **kwargs: object) -> str:
            return VALID_PLAN_JSON

        await node.execute(llm_call, iteration_budget=budget)
        assert node.phase == NodePhase.FAILED

    async def test_beam_attempt_parse_failure_returns_candidate_with_parse_error(self) -> None:
        node = _planner_node(beam_width=2)

        async def llm_call(*args: object, **kwargs: object) -> str:
            return "not valid json"

        await node.execute(llm_call)
        # All candidates parse-failed with no exception, so the node fails
        # with a synthesized LLMProviderError rather than hanging in RUNNING.
        assert node.phase == NodePhase.FAILED
        assert all(c.parse_error for c in node.beam_candidates)

    async def test_beam_completed_event_includes_beam_metadata(self) -> None:
        events: list[GraphEvent] = []

        async def emit(event: GraphEvent) -> None:
            events.append(event)

        node = _planner_node(beam_width=2)
        node._emit_event = emit

        async def llm_call(*args: object, **kwargs: object) -> str:
            return VALID_PLAN_JSON

        await node.execute(llm_call)
        completed = next(e for e in events if e.type == "node_completed")
        assert completed.detail["beam_width"] == 2


# --- parse / strategy-none edge cases ----------------------------------------


class TestParseOutputRaw:
    def test_returns_none_when_strategy_is_none(self) -> None:
        node = _planner_node(strategy=None)
        assert node._parse_output_raw("{}") is None

    def test_parse_output_sets_parse_error_on_failure(self) -> None:
        node = _planner_node()
        result = node._parse_output("not json")
        assert result is None
        assert node.parse_error == "failed to parse LLM output"

    def test_parse_output_raw_returns_validated_model(self) -> None:
        node = _planner_node()
        result = node._parse_output_raw(VALID_PLAN_JSON)
        assert isinstance(result, PlanOutput)


# --- to_result -----------------------------------------------------------------


class TestToResult:
    async def test_success_result_contains_output(self) -> None:
        node = _planner_node()

        async def llm_call(*args: object, **kwargs: object) -> str:
            return VALID_PLAN_JSON

        await node.execute(llm_call)
        result = node.to_result()
        assert result.success is True
        assert "a plan" in result.output

    async def test_classified_error_result_contains_category(self) -> None:
        node = _planner_node()

        async def llm_call(*args: object, **kwargs: object) -> str:
            raise ValueError("non-retryable")

        await node.execute(llm_call)
        result = node.to_result()
        assert result.success is False
        assert "error:" in result.output

    def test_parse_error_only_result_branch(self) -> None:
        node = _planner_node()
        node.phase = NodePhase.FAILED
        node.parse_error = "boom parse"
        result = node.to_result()
        assert result.output == "parse_error: boom parse"

    def test_default_phase_only_result_branch(self) -> None:
        node = _planner_node()
        node.phase = NodePhase.FAILED
        result = node.to_result()
        assert result.output == "error: phase=failed"

    async def test_beam_result_includes_candidates_and_selected_index(self) -> None:
        node = _planner_node(beam_width=2)

        async def llm_call(*args: object, **kwargs: object) -> str:
            return VALID_PLAN_JSON

        await node.execute(llm_call)
        result = node.to_result()
        assert len(result.candidates) == 2
        assert result.selected_candidate >= 0


def test_beam_candidate_defaults() -> None:
    candidate = BeamCandidate(index=0, raw_response="raw")
    assert candidate.parsed_output is None
    assert candidate.score == 0.0
    assert candidate.error is None
