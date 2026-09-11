"""Algorithm-only coverage for retired graph strategy/node helpers.

These tests do not execute a physical Graph or claim lifecycle authority. The
canonical durable Graph suites own Run/NodeRun/Attempt execution evidence.
"""

from __future__ import annotations

import json
from typing import Any

from maistro.graph.node import IterationBudget
from maistro.graph.phases import TERMINAL_GRAPH_PHASES, TERMINAL_NODE_PHASES, GraphPhase, NodePhase
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
    GraphTask,
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
