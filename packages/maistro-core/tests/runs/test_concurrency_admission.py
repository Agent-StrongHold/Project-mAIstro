from datetime import timedelta

import pytest

from maistro.graph import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import AttemptStatus, RunStatus
from maistro.runs.concurrency import (
    ConcurrencyLimits,
    InMemoryConcurrencyAdmission,
    RunAdmissionRejected,
    SqliteConcurrencyAdmission,
)
from maistro.runs.store import InMemoryRunStore


def _graph(workspace_id: str, project_id: str) -> Graph:
    return Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name="bounded",
        nodes=[Node(node_id="step", node_type="agent")],
    )


async def _store() -> tuple[InMemoryRunStore, str, str]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("shared")
    project = await projects.create(
        workspace_id="shared", parent_project_id=root.project_id, name="execution"
    )
    admission = InMemoryConcurrencyAdmission(
        ConcurrencyLimits(
            max_runs_per_principal=1,
            max_runs_per_workspace=2,
            max_runs_global=2,
            max_attempts_per_principal=1,
            max_attempts_per_workspace=2,
            max_attempts_global=2,
        )
    )
    return (
        InMemoryRunStore(project_store=projects, concurrency_admission=admission),
        project.project_id,
        root.project_id,
    )


@pytest.mark.asyncio
async def test_principal_bound_does_not_starve_an_unrelated_principal() -> None:
    store, project_id, _ = await _store()
    first = await store.create_run(_graph("shared", project_id), actor_principal_id="alice")

    with pytest.raises(RunAdmissionRejected, match="runs/principal"):
        await store.create_run(_graph("shared", project_id), actor_principal_id="alice")

    second = await store.create_run(_graph("shared", project_id), actor_principal_id="bob")
    assert second.run_id != first.run_id


@pytest.mark.asyncio
async def test_terminal_run_releases_capacity_and_stale_lease_recovers() -> None:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("w")
    project = await projects.create(workspace_id="w", parent_project_id=root.project_id, name="p")
    admission = InMemoryConcurrencyAdmission(
        ConcurrencyLimits(
            max_runs_per_principal=1,
            max_runs_per_workspace=1,
            max_runs_global=1,
            max_attempts_per_principal=1,
            max_attempts_per_workspace=1,
            max_attempts_global=1,
            lease_ttl=timedelta(seconds=1),
        )
    )
    store = InMemoryRunStore(project_store=projects, concurrency_admission=admission)
    first = await store.create_run(_graph("w", project.project_id), actor_principal_id="alice")
    await store.transition_run(first.run_id, target=RunStatus.CANCELLED)
    released = await store.create_run(_graph("w", project.project_id), actor_principal_id="alice")
    assert released.run_id != first.run_id
    await store.transition_run(released.run_id, target=RunStatus.CANCELLED)

    lease = await admission.acquire_run("crashed", workspace_id="w", principal_id="alice")
    assert lease.expires_at > lease.expires_at - timedelta(seconds=1)
    assert await admission.reclaim_stale(now=lease.expires_at + timedelta(seconds=1)) == 1
    replacement = await admission.acquire_run("replacement", workspace_id="w", principal_id="alice")
    assert replacement.resource_id == "replacement"


@pytest.mark.asyncio
async def test_sqlite_connections_share_admission_capacity(tmp_path) -> None:
    import aiosqlite

    limits = ConcurrencyLimits(
        max_runs_per_principal=1,
        max_runs_per_workspace=1,
        max_runs_global=1,
        max_attempts_per_principal=1,
        max_attempts_per_workspace=1,
        max_attempts_global=1,
    )
    async with (
        aiosqlite.connect(tmp_path / "admission.db") as first_conn,
        aiosqlite.connect(tmp_path / "admission.db") as second_conn,
    ):
        first = SqliteConcurrencyAdmission(first_conn, limits)
        second = SqliteConcurrencyAdmission(second_conn, limits)
        await first.ensure_schema()
        await second.ensure_schema()
        await first.acquire_run("one", workspace_id="w", principal_id="alice")
        with pytest.raises(RunAdmissionRejected, match="runs/"):
            await second.acquire_run("two", workspace_id="w", principal_id="bob")


@pytest.mark.asyncio
async def test_attempt_capacity_is_released_on_terminalization() -> None:
    store, project_id, _ = await _store()
    first = await store.create_run(_graph("shared", project_id), actor_principal_id="alice")
    node = await store.create_node_run(first.run_id, node_id="step")
    attempt = await store.create_attempt(node.node_run_id)
    second_node = await store.create_node_run(first.run_id, node_id="step")
    with pytest.raises(RunAdmissionRejected, match="attempts/principal"):
        await store.create_attempt(second_node.node_run_id)
    await store.transition_attempt(attempt.attempt_id, AttemptStatus.CANCELLED)
    # The Run limit still applies, while the Attempt lease itself is now free.
    snapshot = await store._concurrency.snapshot()  # type: ignore[attr-defined]
    assert snapshot.active_attempts == 0
