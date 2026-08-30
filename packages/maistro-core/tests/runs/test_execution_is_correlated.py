"""The execution seams bind the canonical ids the executor runs under (#707).

These are the cases the acceptance list turns on: what an executor, a log line
or an event emitted *inside* a running Attempt can say about which execution it
belongs to. Every case reads the ambient context from inside real work driven
through the real service, never from a mock's call arguments.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.graph import Graph, Node
from maistro.observability.correlation import (
    ExecutionContext,
    bind_execution_context,
    current_execution_context,
)
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import AttemptExecutionService, InMemoryRunStore, RunExecutionService
from maistro.runtime import PythonExecutionRuntime

pytestmark = [pytest.mark.contract("behavioral")]


async def _store_and_graph() -> tuple[InMemoryRunStore, Graph]:
    project_store = InMemoryProjectScopeStore()
    root = await project_store.create_root("ws-1")
    project = await project_store.create(
        workspace_id="ws-1",
        parent_project_id=root.project_id,
        name="Correlation",
    )
    store = InMemoryRunStore(project_store=project_store)
    graph = Graph(
        workspace_id="ws-1",
        project_id=project.project_id,
        name="One node",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    return store, graph


def _recording_executor(seen: list[ExecutionContext]) -> Any:
    async def executor(work_item: Any, context: Any) -> str:
        seen.append(current_execution_context())
        return "done"

    return executor


class TestAnExecutorRunsUnderItsOwnIds:
    @pytest.mark.ac("SPEC-083026-20b2/AC-5")
    async def test_the_executor_sees_run_node_run_and_attempt(self) -> None:
        store, graph = await _store_and_graph()
        run = await store.create_run(graph)
        service = RunExecutionService(store=store, runtime=PythonExecutionRuntime())
        seen: list[ExecutionContext] = []

        node_run, attempt = await service.execute_node(
            run.run_id,
            "node-1",
            "work",
            {},
            executor=_recording_executor(seen),
        )

        assert seen[0].run_id == run.run_id
        assert seen[0].node_run_id == node_run.node_run_id
        assert seen[0].attempt_id == attempt.attempt_id

    @pytest.mark.ac("SPEC-083026-20b2/AC-4")
    async def test_a_retry_names_the_same_run_as_the_first_try(self) -> None:
        """The one question a retry raises is what the first try did. Before
        this, a retry named its NodeRun and no Run at all."""
        store, graph = await _store_and_graph()
        run = await store.create_run(graph)
        service = RunExecutionService(store=store, runtime=PythonExecutionRuntime())
        seen: list[ExecutionContext] = []

        async def failing(work_item: Any, context: Any) -> str:
            seen.append(current_execution_context())
            raise RuntimeError("first try fails")

        with pytest.raises(RuntimeError, match="first try fails"):
            await service.execute_node(run.run_id, "node-1", "work", {}, executor=failing)
        node_run_id = seen[0].node_run_id
        await service.retry_node(node_run_id, "work", {}, executor=_recording_executor(seen))

        assert [c.run_id for c in seen] == [run.run_id, run.run_id]
        assert seen[0].node_run_id == seen[1].node_run_id == node_run_id
        assert seen[0].attempt_id != seen[1].attempt_id

    @pytest.mark.ac("SPEC-083026-20b2/AC-4")
    async def test_a_retry_of_an_unknown_node_run_fails_on_the_node_run(self) -> None:
        """Correlation must not become the thing that reports an absence the
        execution seam below reports better."""
        store, _ = await _store_and_graph()
        service = RunExecutionService(store=store, runtime=PythonExecutionRuntime())

        with pytest.raises(Exception) as caught:
            await service.retry_node("no-such-node-run", "work", {}, executor=lambda *_: None)
        assert "not correlation ids" not in str(caught.value)


class TestTheContextDoesNotOutliveTheAttempt:
    @pytest.mark.ac("SPEC-083026-20b2/AC-3")
    async def test_nothing_is_bound_after_the_call_returns(self) -> None:
        store, graph = await _store_and_graph()
        run = await store.create_run(graph)
        service = RunExecutionService(store=store, runtime=PythonExecutionRuntime())

        await service.execute_node(
            run.run_id, "node-1", "work", {}, executor=_recording_executor([])
        )

        assert current_execution_context() == ExecutionContext()

    @pytest.mark.ac("SPEC-083026-20b2/AC-3")
    async def test_nothing_is_bound_after_the_executor_raises(self) -> None:
        store, graph = await _store_and_graph()
        run = await store.create_run(graph)
        service = RunExecutionService(store=store, runtime=PythonExecutionRuntime())

        async def failing(work_item: Any, context: Any) -> str:
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            await service.execute_node(run.run_id, "node-1", "work", {}, executor=failing)

        assert current_execution_context() == ExecutionContext()


class TestAnOuterBindingSurvives:
    async def test_a_workspace_bound_outside_reaches_the_executor(self) -> None:
        """`execute_node` binds only the Run, deliberately. Whichever seam holds
        the Workspace binds it, and the executor sees both."""
        store, graph = await _store_and_graph()
        run = await store.create_run(graph)
        service = RunExecutionService(store=store, runtime=PythonExecutionRuntime())
        seen: list[ExecutionContext] = []

        with bind_execution_context(workspace_id="ws-1", request_id="req-9"):
            await service.execute_node(
                run.run_id, "node-1", "work", {}, executor=_recording_executor(seen)
            )

        assert seen[0].workspace_id == "ws-1"
        assert seen[0].request_id == "req-9"
        assert seen[0].run_id == run.run_id


class TestTheAttemptIdIsBoundOnlyOnceItIsRunning:
    @pytest.mark.ac("SPEC-083026-20b2/AC-5")
    async def test_no_attempt_is_named_before_one_exists(self) -> None:
        """Binding an id over work that has not started names an execution that
        has not happened."""
        store, graph = await _store_and_graph()
        run = await store.create_run(graph)
        node_run = await store.create_node_run(run.run_id, node_id="node-1")
        service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())
        during_prepare: list[ExecutionContext] = []

        original = store.create_attempt

        async def watched(*args: Any, **kwargs: Any) -> Any:
            during_prepare.append(current_execution_context())
            return await original(*args, **kwargs)

        store.create_attempt = watched  # type: ignore[method-assign]
        await service.execute(node_run.node_run_id, "work", {}, executor=_recording_executor([]))

        assert during_prepare[0].node_run_id == node_run.node_run_id
        assert during_prepare[0].attempt_id == ""


class TestTheNodeRunReadBackIsStillGuarded:
    """Not a correlation case, and here because of one.

    Binding the Run put `execute_node`'s body inside a `with`, which makes its
    read-back guard a changed line -- and the diff gate then asks, correctly,
    for both arcs of a branch this change moved. Only the taken arc had a test;
    the raise had never been exercised.
    """

    async def test_a_node_run_that_vanishes_during_execution_raises(self) -> None:
        store, graph = await _store_and_graph()
        run = await store.create_run(graph)
        service = RunExecutionService(store=store, runtime=PythonExecutionRuntime())

        executed = False
        original = store.get_node_run

        async def executor(work_item: Any, context: Any) -> str:
            nonlocal executed
            executed = True
            return "done"

        async def vanishing(node_run_id: str) -> Any:
            # Only the read-back, after the Attempt has run. The layer below
            # reads the same NodeRun on its way in and raises its own, better
            # error if it is missing there, so the swap has to be late.
            return None if executed else await original(node_run_id)

        store.get_node_run = vanishing  # type: ignore[method-assign]
        with pytest.raises(RuntimeError, match="canonical NodeRun disappeared"):
            # Reconciliation deferred, because it reads the NodeRun too and
            # would hit the vanishing stub before the read-back this covers.
            await service.execute_node(
                run.run_id,
                "node-1",
                "work",
                {},
                executor=executor,
                reconcile_logical=False,
            )
