"""Tests for maistro.graph.strategy — per-role NodeStrategy implementations."""

from __future__ import annotations

import pytest

from maistro.graph.strategy import (
    STRATEGY_REGISTRY,
    CoderStrategy,
    ConductorStrategy,
    PlannerStrategy,
    PMStrategy,
    ReviewerStrategy,
    ScoutStrategy,
    get_strategy,
)
from maistro.graph.types import (
    AgentRole,
    CodeOutput,
    GraphBlackboard,
    GraphTask,
    OptimizationSignal,
    PlanOutput,
    PMRoleOutput,
    ReviewOutput,
    ScoutOutput,
    SubTask,
)


def _task(**kwargs: object) -> GraphTask:
    return GraphTask(description="do the thing", workspace="/ws", **kwargs)  # type: ignore[arg-type]


def _board(**kwargs: object) -> GraphBlackboard:
    return GraphBlackboard(task_objective="obj", workspace="/ws", **kwargs)  # type: ignore[arg-type]


class TestPlannerStrategy:
    def test_build_user_prompt_with_constraints(self) -> None:
        strategy = PlannerStrategy()
        task = _task(constraints=["no breaking changes"])
        prompt = strategy.build_user_prompt(task, _board(), None, None, None)
        assert "no breaking changes" in prompt
        assert "do the thing" in prompt

    def test_build_user_prompt_without_constraints(self) -> None:
        strategy = PlannerStrategy()
        prompt = strategy.build_user_prompt(_task(), _board(), None, None, None)
        assert "None" in prompt

    def test_score_output_counts_subtasks(self) -> None:
        strategy = PlannerStrategy()
        plan = PlanOutput(summary="s", subtasks=[SubTask(title="t", description="d")])
        assert strategy.score_output(plan) == 1.0

    def test_score_output_non_matching_type_returns_zero(self) -> None:
        strategy = PlannerStrategy()
        assert strategy.score_output(CodeOutput()) == 0.0

    def test_update_blackboard_is_noop(self) -> None:
        strategy = PlannerStrategy()
        board = _board()
        assert strategy.update_blackboard(PlanOutput(summary="s"), board) is board


class TestCoderStrategy:
    def test_build_user_prompt_with_plan(self) -> None:
        strategy = CoderStrategy()
        plan = PlanOutput(
            summary="plan summary",
            subtasks=[SubTask(title="t1", description="d1")],
        )
        prompt = strategy.build_user_prompt(_task(), _board(), plan, None, None)
        assert "plan summary" in prompt
        assert "1. t1: d1" in prompt

    def test_build_user_prompt_without_plan(self) -> None:
        strategy = CoderStrategy()
        prompt = strategy.build_user_prompt(_task(), _board(), None, None, None)
        assert "Plan:" not in prompt
        assert "do the thing" in prompt

    def test_score_output_files_and_tests(self) -> None:
        strategy = CoderStrategy()
        code = CodeOutput(files_changed=["a.py", "b.py"], tests_added=True)
        assert strategy.score_output(code) == 4.0

    def test_score_output_no_tests_added(self) -> None:
        strategy = CoderStrategy()
        code = CodeOutput(files_changed=["a.py"], tests_added=False)
        assert strategy.score_output(code) == 1.0

    def test_score_output_non_matching_type_returns_zero(self) -> None:
        strategy = CoderStrategy()
        assert strategy.score_output(PlanOutput(summary="s")) == 0.0

    def test_update_blackboard_is_noop(self) -> None:
        strategy = CoderStrategy()
        board = _board()
        assert strategy.update_blackboard(CodeOutput(), board) is board


class TestReviewerStrategy:
    def test_build_user_prompt_no_code(self) -> None:
        strategy = ReviewerStrategy()
        prompt = strategy.build_user_prompt(_task(), _board(), None, None, None)
        assert "No code output available" in prompt

    def test_build_user_prompt_with_code_and_plan(self) -> None:
        strategy = ReviewerStrategy()
        plan = PlanOutput(summary="plan summary")
        code = CodeOutput(files_changed=["a.py"], description="desc", tests_added=True)
        prompt = strategy.build_user_prompt(_task(), _board(), plan, code, None)
        assert "plan summary" in prompt
        assert "a.py" in prompt
        assert "desc" in prompt
        assert "Tests added: True" in prompt

    def test_build_user_prompt_with_code_no_plan_and_no_files(self) -> None:
        strategy = ReviewerStrategy()
        code = CodeOutput(files_changed=[], description="desc")
        prompt = strategy.build_user_prompt(_task(), _board(), None, code, None)
        assert "Plan summary: N/A" in prompt
        assert "Files changed: none" in prompt

    def test_score_output_returns_score(self) -> None:
        strategy = ReviewerStrategy()
        review = ReviewOutput(approved=True, score=7.5)
        assert strategy.score_output(review) == 7.5

    def test_score_output_non_matching_type_returns_zero(self) -> None:
        strategy = ReviewerStrategy()
        assert strategy.score_output(CodeOutput()) == 0.0

    def test_update_blackboard_is_noop(self) -> None:
        strategy = ReviewerStrategy()
        board = _board()
        assert strategy.update_blackboard(ReviewOutput(approved=True), board) is board


class TestScoutStrategy:
    def test_build_user_prompt_without_history(self) -> None:
        strategy = ScoutStrategy()
        board = _board(iteration=0)
        prompt = strategy.build_user_prompt(_task(), board, None, None, None)
        assert "Optimization history" not in prompt
        assert "Iteration: 0" in prompt

    def test_build_user_prompt_with_history_and_avg_score(self) -> None:
        strategy = ScoutStrategy()
        signal = OptimizationSignal(
            node_metrics=[],
            weakest_node="coder",
            total_runs=3,
            avg_review_score=6.2,
        )
        board = _board(iteration=2, optimization_history=[signal])
        prompt = strategy.build_user_prompt(_task(), board, None, None, None)
        assert "weakest node was coder" in prompt
        assert "avg review 6.2/10" in prompt

    def test_build_user_prompt_with_history_no_avg_score(self) -> None:
        strategy = ScoutStrategy()
        signal = OptimizationSignal(node_metrics=[], weakest_node="coder", total_runs=1)
        board = _board(optimization_history=[signal])
        prompt = strategy.build_user_prompt(_task(), board, None, None, None)
        assert "weakest node was coder. " in prompt
        assert "avg review" not in prompt

    def test_build_user_prompt_history_entry_without_weakest_node(self) -> None:
        strategy = ScoutStrategy()
        board = _board(optimization_history=[{"unrelated": "data"}])
        prompt = strategy.build_user_prompt(_task(), board, None, None, None)
        assert "Optimization history" not in prompt

    def test_score_output_counts_relevant_files(self) -> None:
        strategy = ScoutStrategy()
        output = ScoutOutput(relevant_files=["a.py", "b.py"], patterns="", summary="s")
        assert strategy.score_output(output) == 2.0

    def test_score_output_non_matching_type_returns_zero(self) -> None:
        strategy = ScoutStrategy()
        assert strategy.score_output(CodeOutput()) == 0.0

    def test_update_blackboard_sets_scout_context(self) -> None:
        strategy = ScoutStrategy()
        board = _board()
        output = ScoutOutput(
            relevant_files=["a.py"],
            patterns="pattern",
            dependency_map={"a.py": ["b.py"]},
            similar_implementations=["c.py"],
            summary="findings",
        )
        new_board = strategy.update_blackboard(output, board)
        assert new_board.scout_context is not None
        assert new_board.scout_context.relevant_files == ["a.py"]
        assert new_board.scout_context.raw_findings == "findings"

    def test_update_blackboard_non_matching_type_is_noop(self) -> None:
        strategy = ScoutStrategy()
        board = _board()
        assert strategy.update_blackboard(CodeOutput(), board) is board


class TestConductorStrategy:
    def test_build_user_prompt(self) -> None:
        strategy = ConductorStrategy()
        prompt = strategy.build_user_prompt(_task(), _board(), None, None, None)
        assert "do the thing" in prompt
        assert "/ws" in prompt

    def test_score_output_always_zero(self) -> None:
        strategy = ConductorStrategy()
        assert strategy.score_output(PlanOutput(summary="s")) == 0.0

    def test_update_blackboard_is_noop(self) -> None:
        strategy = ConductorStrategy()
        board = _board()
        assert strategy.update_blackboard(PlanOutput(summary="s"), board) is board


class TestPMStrategy:
    def test_build_user_prompt_with_constraints(self) -> None:
        strategy = PMStrategy(AgentRole.RESEARCH)
        task = _task(constraints=["budget limit"])
        prompt = strategy.build_user_prompt(task, _board(), None, None, None)
        assert "budget limit" in prompt

    def test_build_user_prompt_without_constraints(self) -> None:
        strategy = PMStrategy(AgentRole.RESEARCH)
        prompt = strategy.build_user_prompt(_task(), _board(), None, None, None)
        assert "None" in prompt

    def test_score_output_llm_source_scales_with_summary_length(self) -> None:
        strategy = PMStrategy(AgentRole.RESEARCH)
        output = PMRoleOutput(capability="poll_jira", summary="x" * 40, source="llm")
        assert strategy.score_output(output) == 0.5

    def test_score_output_caps_at_five(self) -> None:
        strategy = PMStrategy(AgentRole.RESEARCH)
        output = PMRoleOutput(capability="poll_jira", summary="x" * 1000, source="llm")
        assert strategy.score_output(output) == 5.0

    def test_score_output_non_llm_source_returns_zero(self) -> None:
        strategy = PMStrategy(AgentRole.RESEARCH)
        output = PMRoleOutput(capability="poll_jira", summary="x" * 40, source="no_data")
        assert strategy.score_output(output) == 0.0

    def test_score_output_non_matching_type_returns_zero(self) -> None:
        strategy = PMStrategy(AgentRole.RESEARCH)
        assert strategy.score_output(CodeOutput()) == 0.0

    def test_update_blackboard_sets_annotation_for_role(self) -> None:
        strategy = PMStrategy(AgentRole.DELIVERY)
        board = _board()
        output = PMRoleOutput(capability="poll_jira", summary="status update")
        new_board = strategy.update_blackboard(output, board)
        assert new_board.node_annotations["delivery"] == "status update"

    def test_update_blackboard_non_matching_type_is_noop(self) -> None:
        strategy = PMStrategy(AgentRole.DELIVERY)
        board = _board()
        assert strategy.update_blackboard(CodeOutput(), board) is board


class TestStrategyRegistry:
    def test_all_roles_have_strategies(self) -> None:
        for role in AgentRole:
            assert role in STRATEGY_REGISTRY


class TestGetStrategy:
    def test_get_strategy_by_enum(self) -> None:
        assert isinstance(get_strategy(AgentRole.PLANNER), PlannerStrategy)

    def test_get_strategy_by_string(self) -> None:
        assert isinstance(get_strategy("coder"), CoderStrategy)

    def test_get_strategy_unknown_string_raises(self) -> None:
        with pytest.raises(ValueError, match="No strategy registered"):
            get_strategy("not_a_real_role")
