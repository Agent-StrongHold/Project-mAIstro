"""Canonical execution proof for the shipped Builders ReAct turn."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from maistro.builders.interactive import (
    BuildersExecutionSpine,
    CanonicalInteractiveTurnExecutor,
)
from maistro.graph.durable_runs import (
    CanonicalDurableRunStore,
    InMemoryGraphContinuationStore,
)
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.store import InMemoryRunStore

pytestmark = pytest.mark.contract("behavioral")


@dataclass
class _Runner:
    result: dict[str, Any]

    def __post_init__(self) -> None:
        self.messages: list[list[dict[str, Any]]] = []

    async def execute_turn(self, *, messages: list[dict[str, Any]]) -> dict[str, Any]:
        self.messages.append(messages)
        return self.result


async def _executor() -> tuple[CanonicalInteractiveTurnExecutor, InMemoryRunStore]:
    projects = InMemoryProjectScopeStore()
    await projects.create_root("builders-cli")
    project = await projects.root_for_workspace("builders-cli")
    runs = InMemoryRunStore(project_store=projects)
    durable = CanonicalDurableRunStore(runs, InMemoryGraphContinuationStore())
    return (
        CanonicalInteractiveTurnExecutor(
            run_store=runs,
            durable_store=durable,
            workspace_id="builders-cli",
            project_id=project.project_id,
        ),
        runs,
    )


@pytest.mark.asyncio
async def test_react_turn_is_admitted_as_one_canonical_run_and_physical_attempt() -> None:
    executor, runs = await _executor()
    runner = _Runner({"content": "edited file", "stop_reason": "end_turn"})

    result = await executor.execute(
        session_id="session-1",
        repo="/tmp/repo",
        prompt="edit the file",
        messages=[{"role": "user", "content": "edit the file"}],
        runner=runner,
    )

    assert result.status is RunStatus.COMPLETED
    assert result.output == "edited file"
    assert len(runner.messages) == 1
    stored = await runs.get_run(result.run_id)
    assert stored is not None
    assert stored.workspace_id == "builders-cli"
    assert stored.project_id == stored.graph.project_id
    node_runs = await runs.list_node_runs(result.run_id)
    assert len(node_runs) == 1
    assert node_runs[0].node_id == "builders-stage:interactive-turn"
    attempts = await runs.list_attempts(node_runs[0].node_run_id)
    assert len(attempts) == 1
    assert attempts[0].status is AttemptStatus.COMPLETED


@pytest.mark.asyncio
async def test_cli_spine_retains_run_identity_across_reopen(tmp_path: Any) -> None:
    database_url = f"sqlite:///{tmp_path / 'builders.db'}"
    spine = await BuildersExecutionSpine.open(
        workspace_id="builders-cli",
        database_url=database_url,
    )
    try:
        runner = _Runner({"content": "persisted", "stop_reason": "end_turn"})
        result = await spine.executor().execute(
            session_id="session-1",
            repo="/tmp/repo",
            prompt="persist this turn",
            messages=[],
            runner=runner,
        )
    finally:
        await spine.close()

    reopened = await BuildersExecutionSpine.open(
        workspace_id="builders-cli",
        database_url=database_url,
    )
    try:
        stored = await reopened.run_store.get_run(result.run_id)
        assert stored is not None
        assert stored.status is RunStatus.COMPLETED
        assert stored.workspace_id == "builders-cli"
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_react_failure_cannot_project_success_without_canonical_evidence() -> None:
    executor, runs = await _executor()
    runner = _Runner({"content": "ignored", "stop_reason": "max_turns"})

    result = await executor.execute(
        session_id="session-1",
        repo="/tmp/repo",
        prompt="keep working",
        messages=[],
        runner=runner,
    )

    assert result.status is RunStatus.FAILED
    assert result.error == "interactive turn stopped: max_turns"
    stored = await runs.get_run(result.run_id)
    assert stored is not None
    assert stored.status is RunStatus.FAILED
    node_runs = await runs.list_node_runs(result.run_id)
    attempts = await runs.list_attempts(node_runs[0].node_run_id)
    # The physical call returned a structured failed NodeResult, so the
    # Attempt is complete evidence of a failed operation rather than a missing
    # Attempt; the canonical Run still cannot project success.
    assert attempts[0].status is AttemptStatus.COMPLETED
    assert attempts[0].result is not None
    assert attempts[0].result.status == "failed"
