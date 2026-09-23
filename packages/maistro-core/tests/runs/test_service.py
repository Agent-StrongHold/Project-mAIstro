from __future__ import annotations

from typing import Any

import pytest

from maistro.graph import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import (
    AttemptStatus,
    InMemoryRunStore,
    RunExecutionService,
    RunStatus,
)
from maistro.runs.lifecycle import InvalidLifecycleTransition
from maistro.runtime import PythonExecutionRuntime


async def _service() -> tuple[RunExecutionService, InMemoryRunStore, Graph]:
    project_store = InMemoryProjectScopeStore()
    root = await project_store.create_root("workspace-1")
    project = await project_store.create(
        workspace_id="workspace-1",
        parent_project_id=root.project_id,
        name="Execution",
    )
    store = InMemoryRunStore(project_store=project_store)
    service = RunExecutionService(store=store, runtime=PythonExecutionRuntime())
    graph = Graph(
        graph_id="graph-1",
        workspace_id="workspace-1",
        project_id=project.project_id,
        name="Single node",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    return service, store, graph


@pytest.mark.asyncio
async def test_graph_to_run_to_node_run_to_attempt_to_runtime() -> None:
    service, store, graph = await _service()
    run = await service.create_run(graph, provenance={"entry": "test"})

    async def executor(work_item: Any, context: Any) -> dict[str, Any]:
        return {"work": work_item, "context": context}

    node_run, attempt = await service.execute_node(
        run.run_id,
        "node-1",
        "payload",
        {"run_id": run.run_id},
        executor=executor,
        executor_id="agent",
    )

    assert node_run.run_id == run.run_id
    assert node_run.node_id == "node-1"
    assert node_run.status is RunStatus.COMPLETED
    assert attempt.node_run_id == node_run.node_run_id
    assert attempt.status is AttemptStatus.COMPLETED
    assert attempt.result == {
        "work": "payload",
        "context": {"run_id": run.run_id},
    }

    stored_run = await store.get_run(run.run_id)
    assert stored_run is not None
    assert stored_run.status is RunStatus.COMPLETED
    assert stored_run.result == attempt.result
    assert stored_run.graph.content_hash == graph.content_hash


@pytest.mark.asyncio
async def test_retry_reuses_node_run_and_creates_new_attempt() -> None:
    service, store, graph = await _service()
    run = await service.create_run(graph)

    async def fail(_work: Any, _context: Any) -> None:
        raise RuntimeError("transient")

    with pytest.raises(RuntimeError, match="transient"):
        await service.execute_node(
            run.run_id,
            "node-1",
            None,
            None,
            executor=fail,
        )

    node_runs = await store.list_node_runs(run.run_id)
    assert len(node_runs) == 1
    node_run = node_runs[0]
    assert node_run.status is RunStatus.WAITING

    async def succeed(_work: Any, _context: Any) -> str:
        return "ok"

    retry = await service.retry_node(
        node_run.node_run_id,
        None,
        None,
        executor=succeed,
    )

    attempts = await store.list_attempts(node_run.node_run_id)
    assert [attempt.ordinal for attempt in attempts] == [1, 2]
    assert attempts[0].status is AttemptStatus.FAILED
    assert retry.status is AttemptStatus.COMPLETED
    assert retry.node_run_id == node_run.node_run_id


# --- cancellation against a spine that moves underneath the fence ----------


async def test_cancel_run_reports_a_run_that_never_existed() -> None:
    service, _store, _graph = await _service()
    with pytest.raises(ValueError, match="does not exist"):
        await service.cancel_run("run-never-was")


class _VanishingAfterFenceStore(InMemoryRunStore):
    """The Run fence transition lands, then the record is gone."""

    async def transition_run(self, run_id: str, target: RunStatus, **kwargs: object):
        updated = await super().transition_run(run_id, target, **kwargs)  # type: ignore[arg-type]
        if target is RunStatus.CANCELLED:
            self._vanished = True  # type: ignore[attr-defined]
        return updated

    async def get_run(self, run_id: str):
        if getattr(self, "_vanished", False):
            return None
        return await super().get_run(run_id)


async def test_cancel_run_surfaces_a_run_that_vanished_after_its_fence() -> None:
    """A Run that disappears after fencing is torn state, not a cancellation.

    The fence write succeeded, so the caller believes the Run is CANCELLED;
    the re-read that should confirm it finds nothing. Reporting success would
    hide the disagreement between the transition and the record.
    """
    project_store = InMemoryProjectScopeStore()
    root = await project_store.create_root("workspace-1")
    store = _VanishingAfterFenceStore(project_store=project_store)
    graph = Graph(
        graph_id="graph-vanish",
        workspace_id="workspace-1",
        project_id=root.project_id,
        name="One node",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await store.create_run(graph)
    service = RunExecutionService(store=store, runtime=PythonExecutionRuntime())

    with pytest.raises(ValueError, match="disappeared during cancellation"):
        await service.cancel_run(run.run_id)


class _FenceLosingToCompletionStore(InMemoryRunStore):
    """The Run COMPLETES in the gap before the CANCELLED fence lands."""

    async def transition_run(self, run_id: str, target: RunStatus, **kwargs: object):
        if target is RunStatus.CANCELLED:
            current = await super().get_run(run_id)
            assert current is not None
            if current.status is RunStatus.RUNNING:
                await super().transition_run(run_id, RunStatus.COMPLETED, result="late success")
            return await super().transition_run(run_id, target, **kwargs)  # type: ignore[arg-type]
        return await super().transition_run(run_id, target, **kwargs)  # type: ignore[arg-type]


async def test_cancel_run_yields_to_a_run_that_completed_first() -> None:
    """A fence that loses a race to COMPLETED returns the survivor, not CANCELLED.

    The Run reached a *successful* terminal state between the caller's read
    and the fence write. The completion is durable truth; cancellation of an
    already-finished Run must report the finished record unchanged.
    """
    project_store = InMemoryProjectScopeStore()
    root = await project_store.create_root("workspace-1")
    store = _FenceLosingToCompletionStore(project_store=project_store)
    graph = Graph(
        graph_id="graph-race",
        workspace_id="workspace-1",
        project_id=root.project_id,
        name="One node",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await store.create_run(graph)
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    service = RunExecutionService(store=store, runtime=PythonExecutionRuntime())

    survivor = await service.cancel_run(run.run_id)
    assert survivor.status is RunStatus.COMPLETED
    assert survivor.result == "late success"


async def test_cancel_run_probes_attempts_when_no_local_owner_exists() -> None:
    """A Run with live Attempts but no in-process owner still sweeps them.

    The owner probe is what makes run-level cancellation reach a registered
    execution; when there is none, the cancel must still complete the fence
    and the settled-NodeRun sweep without inventing an owner.
    """
    from datetime import timedelta

    service, store, graph = await _service()
    run = await service.create_run(graph)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    attempt = await store.create_attempt(
        node_run.node_run_id,
        runtime_id="test",
        lease_holder="test",
        lease_ttl=timedelta(seconds=30),
    )
    assert attempt.execution_lease is not None
    await store.transition_attempt(
        attempt.attempt_id,
        AttemptStatus.RUNNING,
        fencing_token=attempt.execution_lease.fencing_token,
    )

    cancelled = await service.cancel_run(run.run_id)
    assert cancelled.status is RunStatus.CANCELLED
    # No local owner was registered, so the live Attempt keeps its epoch.
    persisted = await store.get_attempt(attempt.attempt_id)
    assert persisted is not None
    assert persisted.status is AttemptStatus.RUNNING


class _FenceRejectedThenVanishedStore(InMemoryRunStore):
    """The fence is rejected (the Run moved on) and the record is then gone."""

    async def transition_run(self, run_id: str, target: RunStatus, **kwargs: object):
        if target is RunStatus.CANCELLED:
            self._vanished = True  # type: ignore[attr-defined]
            raise InvalidLifecycleTransition("illegal transition: running -> cancelled")
        return await super().transition_run(run_id, target, **kwargs)  # type: ignore[arg-type]

    async def get_run(self, run_id: str):
        if getattr(self, "_vanished", False):
            return None
        return await super().get_run(run_id)


async def test_cancel_run_surfaces_a_run_that_rejected_the_fence_and_vanished() -> None:
    """A rejected fence followed by a vanished record is a disagreement.

    The transition was refused because the Run had already moved on, and the
    re-read that should say where it moved found nothing at all. There is no
    honest cancellation answer to return.
    """
    project_store = InMemoryProjectScopeStore()
    root = await project_store.create_root("workspace-1")
    store = _FenceRejectedThenVanishedStore(project_store=project_store)
    graph = Graph(
        graph_id="graph-reject",
        workspace_id="workspace-1",
        project_id=root.project_id,
        name="One node",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await store.create_run(graph)
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    service = RunExecutionService(store=store, runtime=PythonExecutionRuntime())

    with pytest.raises(ValueError, match="disappeared during cancellation"):
        await service.cancel_run(run.run_id)
