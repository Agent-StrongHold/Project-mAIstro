"""Tests for agent type definitions and structured outputs.

Evidence: The agent type system defines the contract between conductor
and sub-agents. These Pydantic models enforce type safety at the
agent communication boundary.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from maistro.agents.types import (
    CodeOutput,
    ConductorOutput,
    PlanOutput,
    ReviewOutput,
    SubTask,
)


class TestPlanOutput:
    def test_valid_plan(self) -> None:
        plan = PlanOutput(
            summary="Add user login",
            subtasks=[
                SubTask(
                    title="Create login route",
                    description="POST /login",
                    file_paths=["src/api/login.py"],
                ),
                SubTask(title="Add tests", description="Test login flow"),
            ],
        )
        assert len(plan.subtasks) == 2
        assert plan.subtasks[0].file_paths == ["src/api/login.py"]

    def test_empty_subtasks_allowed(self) -> None:
        plan = PlanOutput(summary="Analysis only", subtasks=[])
        assert plan.subtasks == []


class TestReviewOutput:
    def test_approved_review(self) -> None:
        review = ReviewOutput(approved=True, score=8.5, issues=[], suggestions=["Add docstring"])
        assert review.approved
        assert review.score == 8.5

    def test_score_bounds(self) -> None:
        """Evidence: Score must be 0-10 range."""
        with pytest.raises(ValidationError):
            ReviewOutput(approved=True, score=11.0)
        with pytest.raises(ValidationError):
            ReviewOutput(approved=False, score=-1.0)


class TestConductorOutput:
    def test_full_pipeline_output(self) -> None:
        output = ConductorOutput(
            plan=PlanOutput(summary="test", subtasks=[]),
            code=CodeOutput(files_changed=["a.py"], description="Added code"),
            review=ReviewOutput(approved=True, score=9.0),
            final_answer="Task completed",
            success=True,
        )
        assert output.success
        assert output.plan is not None
        assert output.code is not None
        assert output.review is not None
