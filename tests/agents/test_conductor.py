"""Tests for conductor agent — uses dry-run mode to avoid LLM calls."""

from __future__ import annotations

import pytest

from maistro.agents.conductor import run_task
from maistro.tasks.models import TaskCreate


@pytest.fixture(autouse=True)
def _dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run all conductor tests in dry-run mode."""
    monkeypatch.setenv("MAISTRO_DRY_RUN", "1")


class TestConductorDryRun:
    async def test_returns_structured_output(self) -> None:
        task = TaskCreate(description="Add hello world endpoint")
        result = await run_task(task)
        assert result.success is True
        assert result.plan is not None
        assert len(result.plan.subtasks) > 0
        assert "DRY RUN" in result.final_answer

    async def test_respects_workspace(self) -> None:
        task = TaskCreate(
            description="Fix bug",
            workspace="/repos/test-repo",
        )
        result = await run_task(task)
        assert result.success is True

    async def test_handles_constraints(self) -> None:
        task = TaskCreate(
            description="Implement auth",
            constraints=["Use bcrypt", "Add tests"],
        )
        result = await run_task(task)
        assert result.success is True
