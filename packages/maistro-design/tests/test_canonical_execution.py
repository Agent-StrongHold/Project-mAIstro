"""Design Studio operations converge on the canonical execution spine (#52)."""

from __future__ import annotations

from typing import Any

import pytest

from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.store import InMemoryRunStore, RunIntegrityError
from maistro_design.canonical_execution import DesignCanonicalExecution
from maistro_design.types import DiscoveryResult

pytestmark = pytest.mark.asyncio


async def _execution() -> tuple[DesignCanonicalExecution, InMemoryRunStore]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("workspace-design")
    runs = InMemoryRunStore(project_store=projects)
    return (
        DesignCanonicalExecution(
            runs,
            workspace_id=root.workspace_id,
            project_id=root.project_id,
        ),
        runs,
    )


async def test_design_operation_persists_run_noderun_and_attempt() -> None:
    canonical, runs = await _execution()
    discovery = DiscoveryResult(
        skill_slug="login-flow",
        responses={"auth_methods": "email"},
        design_system_slug="default",
    )
    run_id = await canonical.admit(discovery=discovery, actor_principal_id="principal-1")
    result = await canonical.execute(
        run_id,
        lambda: _value({"project_id": "design-project-1"}),
    )

    assert result == {"project_id": "design-project-1"}
    run = await runs.get_run(run_id)
    assert run is not None
    assert run.workspace_id == "workspace-design"
    assert run.project_id != "workspace-design"
    assert run.actor_principal_id == "principal-1"
    assert run.status is RunStatus.COMPLETED
    node_runs = await runs.list_node_runs(run.run_id)
    assert len(node_runs) == 1
    assert node_runs[0].status is RunStatus.COMPLETED
    attempts = await runs.list_attempts(node_runs[0].node_run_id)
    assert [attempt.status for attempt in attempts] == [AttemptStatus.COMPLETED]
    assert attempts[0].result == {"project_id": "design-project-1"}


async def test_adapter_rejects_a_run_outside_its_bound_scope() -> None:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("workspace-design")
    child = await projects.create(
        workspace_id=root.workspace_id,
        parent_project_id=root.project_id,
        name="other-scope",
    )
    runs = InMemoryRunStore(project_store=projects)
    bound = DesignCanonicalExecution(
        runs,
        workspace_id=root.workspace_id,
        project_id=root.project_id,
    )
    other = DesignCanonicalExecution(
        runs,
        workspace_id=child.workspace_id,
        project_id=child.project_id,
    )
    discovery = DiscoveryResult(
        skill_slug="login-flow",
        responses={"auth_methods": "email"},
        design_system_slug="default",
    )
    run_id = await other.admit(discovery=discovery, actor_principal_id="principal-1")

    async def _must_not_execute() -> Any:
        raise AssertionError("an out-of-scope operation must not reach the provider")

    with pytest.raises(RunIntegrityError, match="outside its bound"):
        await bound.execute(run_id, _must_not_execute)


async def test_design_failure_is_a_failed_attempt_and_failed_run() -> None:
    canonical, runs = await _execution()
    discovery = DiscoveryResult(
        skill_slug="login-flow",
        responses={"auth_methods": "email"},
        design_system_slug="default",
    )

    async def _fail() -> Any:
        raise RuntimeError("design provider unavailable")

    with pytest.raises(RuntimeError, match="design provider unavailable"):
        run_id = await canonical.admit(discovery=discovery, actor_principal_id="principal-1")
        await canonical.execute(run_id, _fail)

    run = await runs.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.FAILED
    node_run = (await runs.list_node_runs(run.run_id))[0]
    assert node_run.status is RunStatus.FAILED
    attempts = await runs.list_attempts(node_run.node_run_id)
    assert len(attempts) == 1
    assert attempts[0].status is AttemptStatus.FAILED
    assert attempts[0].error == "design provider unavailable"


async def _value(value: Any) -> Any:
    return value
