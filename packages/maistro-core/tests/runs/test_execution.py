from __future__ import annotations

import asyncio
from typing import Any

import pytest

from maistro.graph import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import (
    Attempt,
    AttemptExecutionService,
    AttemptStatus,
    InMemoryRunStore,
    RunExecutionService,
    RunStatus,
)
from maistro.runs.execution import ExecutionYielded
from maistro.runtime import PythonExecutionRuntime, RuntimeDeadlineExceeded


class RecordingRuntime(PythonExecutionRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.last_execution_id: str | None = None

    async def execute(
        self,
        work_item: Any,
        execution_context: Any,
        *,
        execution_id: str,
        executor: Any,
        timeout_s: float | None = None,
    ) -> Any:
        self.last_execution_id = execution_id
        return await super().execute(
            work_item,
            execution_context,
            execution_id=execution_id,
            executor=executor,
            timeout_s=timeout_s,
        )


async def _node_run() -> tuple[InMemoryRunStore, str, str]:
    project_store = InMemoryProjectScopeStore()
    root = await project_store.create_root("ws-1")
    project = await project_store.create(
        workspace_id="ws-1",
        parent_project_id=root.project_id,
        name="Execution",
    )
    store = InMemoryRunStore(project_store=project_store)
    graph = Graph(
        workspace_id="ws-1",
        project_id=project.project_id,
        name="One node",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await store.create_run(graph)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    return store, run.run_id, node_run.node_run_id


def _lease_token(attempt: Attempt) -> str:
    """Fencing token of an Attempt created with a lease in these tests."""
    assert attempt.execution_lease is not None
    return attempt.execution_lease.fencing_token


@pytest.mark.asyncio
async def test_attempt_id_is_runtime_execution_id_and_reconciles_after_terminal_persist() -> None:
    store, run_id, node_run_id = await _node_run()
    runtime = RecordingRuntime()
    reconciled: list[Attempt] = []

    async def reconcile(attempt: Attempt) -> None:
        persisted = await store.list_attempts(node_run_id)
        assert persisted[-1].status is AttemptStatus.COMPLETED
        assert persisted[-1].attempt_id == attempt.attempt_id
        logical = await store.get_node_run(node_run_id)
        assert logical is not None
        assert logical.status is RunStatus.COMPLETED
        reconciled.append(attempt)

    service = AttemptExecutionService(store=store, runtime=runtime, reconciler=reconcile)

    async def executor(work_item: Any, context: Any) -> dict[str, Any]:
        return {"work": work_item, "context": context}

    terminal = await service.execute(
        node_run_id,
        "work",
        {"run": "context"},
        executor=executor,
        executor_id="agent",
    )

    assert terminal.status is AttemptStatus.COMPLETED
    assert terminal.result == {"work": "work", "context": {"run": "context"}}
    assert runtime.last_execution_id == terminal.attempt_id
    assert reconciled == [terminal]

    stored_run = await store.get_run(run_id)
    assert stored_run is not None
    assert stored_run.status is RunStatus.COMPLETED
    assert stored_run.result == terminal.result


@pytest.mark.asyncio
async def test_executor_exception_persists_failed_attempt_and_parks_logical_state() -> None:
    store, run_id, node_run_id = await _node_run()
    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())

    async def executor(_work: Any, _context: Any) -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await service.execute(node_run_id, None, None, executor=executor)

    attempts = await store.list_attempts(node_run_id)
    assert attempts[-1].status is AttemptStatus.FAILED
    assert attempts[-1].error == "boom"

    node_run = await store.get_node_run(node_run_id)
    run = await store.get_run(run_id)
    assert node_run is not None and node_run.status is RunStatus.WAITING
    assert run is not None and run.status is RunStatus.WAITING


@pytest.mark.asyncio
async def test_executor_timeout_is_failed_attempt_not_runtime_timeout() -> None:
    store, run_id, node_run_id = await _node_run()
    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())

    async def executor(_work: Any, _context: Any) -> None:
        raise TimeoutError("provider timed out")

    with pytest.raises(TimeoutError, match="provider timed out"):
        await service.execute(
            node_run_id,
            None,
            None,
            executor=executor,
            timeout_s=1,
        )

    attempts = await store.list_attempts(node_run_id)
    assert attempts[-1].status is AttemptStatus.FAILED
    node_run = await store.get_node_run(node_run_id)
    run = await store.get_run(run_id)
    assert node_run is not None and node_run.status is RunStatus.WAITING
    assert run is not None and run.status is RunStatus.WAITING


@pytest.mark.asyncio
async def test_runtime_deadline_persists_timed_out_attempt_and_parks_logical_state() -> None:
    store, run_id, node_run_id = await _node_run()
    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())

    async def executor(_work: Any, _context: Any) -> None:
        await asyncio.sleep(0.1)

    with pytest.raises(RuntimeDeadlineExceeded):
        await service.execute(
            node_run_id,
            None,
            None,
            executor=executor,
            timeout_s=0.001,
        )

    attempts = await store.list_attempts(node_run_id)
    assert attempts[-1].status is AttemptStatus.TIMED_OUT
    assert attempts[-1].deadline_at is not None
    node_run = await store.get_node_run(node_run_id)
    run = await store.get_run(run_id)
    assert node_run is not None and node_run.status is RunStatus.WAITING
    assert run is not None and run.status is RunStatus.WAITING


@pytest.mark.asyncio
async def test_runtime_cancellation_persists_cancelled_attempt_without_phantom_running() -> None:
    store, run_id, node_run_id = await _node_run()
    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())
    started = asyncio.Event()

    async def executor(_work: Any, _context: Any) -> None:
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(service.execute(node_run_id, None, None, executor=executor))
    await started.wait()
    running = await store.list_attempts(node_run_id)
    attempt_id = running[-1].attempt_id

    assert await service.cancel(attempt_id) is True
    with pytest.raises(asyncio.CancelledError):
        await task

    attempts = await store.list_attempts(node_run_id)
    assert attempts[-1].status is AttemptStatus.CANCELLED
    node_run = await store.get_node_run(node_run_id)
    run = await store.get_run(run_id)
    # Terminal, not parked (#230). `service.cancel()` is a request to stop, so
    # the retry decision has been made and it was *don't*. Parked here — which
    # is what this asserted before — left a cancelled turn indistinguishable
    # from a provider outage on any record that counts them.
    assert node_run is not None and node_run.status is RunStatus.CANCELLED
    assert run is not None and run.status is RunStatus.CANCELLED


@pytest.mark.asyncio
async def test_run_cancellation_fences_before_provider_launch() -> None:
    class GateStore(InMemoryRunStore):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.running_transition = asyncio.Event()
            self.release_transition = asyncio.Event()

        async def transition_attempt(
            self, attempt_id: str, target: AttemptStatus, **kwargs: Any
        ) -> Attempt:
            if target is AttemptStatus.RUNNING and not self.running_transition.is_set():
                self.running_transition.set()
                await self.release_transition.wait()
            return await super().transition_attempt(attempt_id, target, **kwargs)

    project_store = InMemoryProjectScopeStore()
    root = await project_store.create_root("ws-1")
    store = GateStore(project_store=project_store)
    graph = Graph(
        workspace_id="ws-1",
        project_id=root.project_id,
        name="One node",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await store.create_run(graph)
    service = RunExecutionService(store=store, runtime=PythonExecutionRuntime())
    started = asyncio.Event()

    async def executor(_work: Any, _context: Any) -> None:
        started.set()

    running = asyncio.create_task(
        service.execute_node(run.run_id, "node-1", None, None, executor=executor)
    )
    await store.running_transition.wait()
    cancelling = asyncio.create_task(service.cancel_run(run.run_id))
    for _ in range(100):
        current = await store.get_run(run.run_id)
        if current is not None and current.status is RunStatus.CANCELLED:
            break
        await asyncio.sleep(0)
    else:
        raise AssertionError("cancellation did not win the durable fence")
    store.release_transition.set()

    assert (await cancelling).status is RunStatus.CANCELLED
    with pytest.raises(asyncio.CancelledError):
        await running
    assert not started.is_set()
    node_run = (await store.list_node_runs(run.run_id))[-1]
    attempt = (await store.list_attempts(node_run.node_run_id))[0]
    assert attempt.status is AttemptStatus.CANCELLED


@pytest.mark.asyncio
async def test_run_cancellation_fences_a_provider_that_returns_after_cancel() -> None:
    store, run_id, node_run_id = await _node_run()
    service = RunExecutionService(store=store, runtime=PythonExecutionRuntime())
    started = asyncio.Event()
    returned_after_cancel = asyncio.Event()

    async def executor(_work: Any, _context: Any) -> str:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            # A provider may acknowledge cancellation only after it has
            # produced a final response. The durable Run fence must still win.
            returned_after_cancel.set()
            return "stale success"
        raise AssertionError("unreachable")

    running = asyncio.create_task(
        service.execute_node(
            run_id,
            "node-1",
            None,
            None,
            executor=executor,
            reconcile_logical=False,
        )
    )
    await started.wait()
    cancelled = await service.cancel_run(run_id)
    again = await service.cancel_run(run_id)

    assert cancelled.status is RunStatus.CANCELLED
    assert again.status is RunStatus.CANCELLED
    assert returned_after_cancel.is_set()
    with pytest.raises(asyncio.CancelledError):
        await running
    attempts = await store.list_attempts(node_run_id)
    assert attempts == []  # execute_node owns a fresh NodeRun, not the fixture one

    node_runs = await store.list_node_runs(run_id)
    assert len(node_runs) == 2
    attempt = (await store.list_attempts(node_runs[-1].node_run_id))[0]
    assert attempt.status is AttemptStatus.CANCELLED
    assert (await store.get_node_run(node_runs[-1].node_run_id)).status is RunStatus.CANCELLED


@pytest.mark.asyncio
async def test_failed_attempt_can_retry_same_logical_node_run() -> None:
    store, run_id, node_run_id = await _node_run()
    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())

    async def fail(_work: Any, _context: Any) -> None:
        raise RuntimeError("transient")

    with pytest.raises(RuntimeError, match="transient"):
        await service.execute(node_run_id, None, None, executor=fail)

    parked_node_run = await store.get_node_run(node_run_id)
    parked_run = await store.get_run(run_id)
    assert parked_node_run is not None and parked_node_run.status is RunStatus.WAITING
    assert parked_run is not None and parked_run.status is RunStatus.WAITING

    async def succeed(_work: Any, _context: Any) -> str:
        return "ok"

    second = await service.execute(node_run_id, None, None, executor=succeed)
    attempts = await store.list_attempts(node_run_id)

    assert [attempt.ordinal for attempt in attempts] == [1, 2]
    assert attempts[0].status is AttemptStatus.FAILED
    assert second.status is AttemptStatus.COMPLETED
    assert second.result == "ok"
    completed_node_run = await store.get_node_run(node_run_id)
    resumed_run = await store.get_run(run_id)
    assert completed_node_run is not None and completed_node_run.status is RunStatus.COMPLETED
    assert resumed_run is not None and resumed_run.status is RunStatus.COMPLETED
    assert resumed_run.result == "ok"


@pytest.mark.asyncio
async def test_a_yielded_attempt_is_a_pause_in_the_runtime_metrics_too() -> None:
    """The two records of one event agree (#642).

    `AttemptExecutionService` terminalizes the Attempt as YIELDED, and before
    this the same escape was counted as a failed execution in `RuntimeMetrics`,
    so the physical outcome and the migration-trigger measurement said different
    things about the same pause. This is the end-to-end version of the runtime
    unit tests: it goes through the class the consumer actually raises.
    """
    store, _run_id, node_run_id = await _node_run()
    runtime = PythonExecutionRuntime()
    service = AttemptExecutionService(store=store, runtime=runtime)

    async def pause(_work: Any, _context: Any) -> None:
        raise ExecutionYielded(awaits_human=True)

    terminal = await service.execute(node_run_id, None, None, executor=pause)

    assert terminal.status is AttemptStatus.YIELDED
    metrics = runtime.metrics()
    assert metrics.executions_yielded == 1
    assert metrics.executions_failed == 0
    assert metrics.executions_completed == 0


@pytest.mark.asyncio
async def test_execute_claimed_rejects_attempt_without_lease() -> None:
    from maistro.runs.store import RunIntegrityError

    store, _run_id, node_run_id = await _node_run()
    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())
    attempt = Attempt(node_run_id=node_run_id, ordinal=1, runtime_id="test")

    async def executor(_work: Any, _context: Any) -> None:
        return None

    with pytest.raises(RunIntegrityError, match="missing its execution lease"):
        await service.execute_claimed(attempt, None, None, executor=executor)


@pytest.mark.asyncio
async def test_execute_claimed_rejects_terminal_attempt() -> None:
    from datetime import UTC, datetime, timedelta

    from maistro.runs.store import RunIntegrityError

    store, _run_id, node_run_id = await _node_run()
    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())
    attempt = await store.create_attempt(
        node_run_id,
        runtime_id="test",
        lease_holder="test",
        lease_ttl=timedelta(seconds=30),
    )
    terminal = Attempt.model_validate(
        {
            **attempt.model_dump(mode="python"),
            "status": AttemptStatus.COMPLETED,
            "finished_at": datetime.now(UTC),
        }
    )

    async def executor(_work: Any, _context: Any) -> None:
        return None

    with pytest.raises(RunIntegrityError, match="requires an active Attempt"):
        await service.execute_claimed(terminal, None, None, executor=executor)


# --- external settlement of a claimed Attempt before Runtime launch --------


@pytest.mark.asyncio
async def test_execute_claimed_rejects_an_attempt_that_disappeared_before_launch() -> None:
    """The pre-launch claim survives only if the record is still there.

    A lease that points at an Attempt id the RunStore no longer has means the
    reclaim sweeper settled the epoch underneath the claim. That is torn
    durable state, not a retryable launch: it must surface as an integrity
    error rather than a Runtime execution nothing can settle.
    """
    from datetime import timedelta

    from maistro.runs.store import RunIntegrityError

    store, _run_id, node_run_id = await _node_run()
    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())
    attempt = await store.create_attempt(
        node_run_id,
        runtime_id="test",
        lease_holder="test",
        lease_ttl=timedelta(seconds=30),
    )
    vanished = attempt.model_copy(update={"attempt_id": "attempt-never-was"})

    async def executor(_work: Any, _context: Any) -> None:
        return None

    with pytest.raises(RunIntegrityError, match="attempt-never-was"):
        await service.execute_claimed(vanished, None, None, executor=executor)


@pytest.mark.asyncio
async def test_execute_claimed_yields_to_an_attempt_cancelled_elsewhere() -> None:
    """A persisted CANCELLED verdict is honoured, not re-executed.

    The client-side snapshot still says CREATED (it was claimed before the
    external cancel landed), so the guard that rejects terminal snapshots
    cannot catch this. The store re-read is the only line of defence, and it
    must end the claim as a cancellation — quietly, without a Runtime launch.
    """
    from datetime import timedelta

    store, _run_id, node_run_id = await _node_run()
    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())
    attempt = await store.create_attempt(
        node_run_id,
        runtime_id="test",
        lease_holder="test",
        lease_ttl=timedelta(seconds=30),
    )
    await store.transition_attempt(
        attempt.attempt_id,
        AttemptStatus.CANCELLED,
        error="cancelled by an operator",
        fencing_token=_lease_token(attempt),
    )

    async def executor(_work: Any, _context: Any) -> None:
        return None

    with pytest.raises(asyncio.CancelledError):
        await service.execute_claimed(attempt, None, None, executor=executor)

    persisted = await store.get_attempt(attempt.attempt_id)
    assert persisted is not None
    assert persisted.status is AttemptStatus.CANCELLED


@pytest.mark.asyncio
async def test_execute_claimed_refuses_an_attempt_completed_elsewhere() -> None:
    """A persisted terminal verdict that is not CANCELLED is a disagreement.

    Reconciling a CREATED snapshot against a run the store says COMPLETED
    would mean executing an epoch the durable spine already settled. The
    honest outcome is an integrity error naming the persisted status.
    """
    from datetime import timedelta

    from maistro.runs.store import RunIntegrityError

    store, _run_id, node_run_id = await _node_run()
    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())
    attempt = await store.create_attempt(
        node_run_id,
        runtime_id="test",
        lease_holder="test",
        lease_ttl=timedelta(seconds=30),
    )
    await store.transition_attempt(
        attempt.attempt_id,
        AttemptStatus.RUNNING,
        fencing_token=_lease_token(attempt),
    )
    await store.transition_attempt(
        attempt.attempt_id,
        AttemptStatus.COMPLETED,
        result="late success",
        fencing_token=_lease_token(attempt),
    )

    async def executor(_work: Any, _context: Any) -> None:
        return None

    with pytest.raises(RunIntegrityError, match="requires an active Attempt"):
        await service.execute_claimed(attempt, None, None, executor=executor)


@pytest.mark.asyncio
async def test_cancelling_the_claiming_task_stops_the_runtime_task() -> None:
    """Losing the claiming task during the launch window must not leak the Runtime.

    `execute_claimed` is itself a task (the spine claims attempts
    concurrently). The window `_launch_claimed` yields for — while holding the
    launch lock, after the Runtime task exists but before the claim returns —
    is exactly where a cancellation of the claiming task can land. The Runtime
    task it spawned has no owner left, so the unwinding must cancel and drain
    it before the Attempt settles CANCELLED.

    The cancellation is queued ahead of the claim's first step so it is
    delivered at that documented yield: ``Task.cancel()`` on a task parked on
    ``await runtime_task`` pre-cancels the Runtime task itself (the awaited
    future), so the mid-execution window is the one this path owns.
    """
    from datetime import timedelta

    store, run_id, node_run_id = await _node_run()
    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())
    await store.transition_run(run_id, RunStatus.QUEUED)
    await store.transition_run(run_id, RunStatus.RUNNING)
    runtime = PythonExecutionRuntime()

    async def executor(_work: Any, _context: Any) -> None:
        await asyncio.Event().wait()

    service = AttemptExecutionService(store=store, runtime=runtime)
    attempt = await store.create_attempt(
        node_run_id,
        runtime_id="test",
        lease_holder="test",
        lease_ttl=timedelta(seconds=30),
    )
    claiming = asyncio.create_task(service.execute_claimed(attempt, None, None, executor=executor))
    # Land the cancellation inside the launch window's yield, not on the
    # later `await runtime_task` (whose cancellation is routed through the
    # Runtime task by the event loop).
    asyncio.get_running_loop().call_soon(claiming.cancel)
    with pytest.raises(asyncio.CancelledError):
        await claiming

    # The spawned Runtime execution was cancelled and drained, not leaked.
    assert runtime.metrics().executions_cancelled == 1
    persisted = await store.get_attempt(attempt.attempt_id)
    assert persisted is not None
    assert persisted.status is AttemptStatus.CANCELLED
    node_run = await store.get_node_run(node_run_id)
    assert node_run is not None
    assert node_run.status is RunStatus.CANCELLED
    run = await store.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.CANCELLED


# --- cancelling a registered (in-process) Attempt --------------------------


@pytest.mark.asyncio
async def test_cancel_registered_reports_no_owner_for_an_unknown_attempt() -> None:
    assert await AttemptExecutionService.cancel_registered("attempt-unknown") is False


@pytest.mark.asyncio
async def test_cancelling_a_claimed_but_unlaunched_attempt_settles_it() -> None:
    """Cancel between the claim and the Runtime launch is a clean pre-launch settle.

    A registered Attempt that is still CREATED has no runtime execution to
    stop, so cancellation skips that leg and terminalizes the Attempt with the
    pre-launch cause, then reconciles the NodeRun and Run to CANCELLED.
    """
    from datetime import timedelta

    store, run_id, node_run_id = await _node_run()
    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())
    await store.transition_run(run_id, RunStatus.QUEUED)
    await store.transition_run(run_id, RunStatus.RUNNING)
    attempt = await store.create_attempt(
        node_run_id,
        runtime_id="test",
        lease_holder="test",
        lease_ttl=timedelta(seconds=30),
    )
    service._active_services[attempt.attempt_id] = service
    try:
        assert await service.cancel_registered(attempt.attempt_id) is True
        persisted = await store.get_attempt(attempt.attempt_id)
        assert persisted is not None
        assert persisted.status is AttemptStatus.CANCELLED
        node_run = await store.get_node_run(node_run_id)
        assert node_run is not None
        assert node_run.status is RunStatus.CANCELLED
        run = await store.get_run(run_id)
        assert run is not None
        assert run.status is RunStatus.CANCELLED

        # An already-CANCELLED registration reports success without redoing work.
        assert await service.cancel_registered(attempt.attempt_id) is True
    finally:
        service._active_services.pop(attempt.attempt_id, None)


@pytest.mark.asyncio
async def test_cancelling_a_registration_whose_record_vanished_is_not_a_cancel() -> None:
    """A registration pointing at a gone record is stale, not cancelled."""
    from datetime import timedelta

    store, _run_id, node_run_id = await _node_run()
    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())
    service._active_services["attempt-vanished"] = service
    settled = await store.create_attempt(
        node_run_id,
        runtime_id="test",
        lease_holder="test",
        lease_ttl=timedelta(seconds=30),
    )
    await store.transition_attempt(
        settled.attempt_id,
        AttemptStatus.RUNNING,
        fencing_token=_lease_token(settled),
    )
    await store.transition_attempt(
        settled.attempt_id,
        AttemptStatus.COMPLETED,
        result="done",
        fencing_token=_lease_token(settled),
    )
    service._active_services[settled.attempt_id] = service
    try:
        assert await service.cancel_registered("attempt-vanished") is False
        # and a terminal-but-not-cancelled record is likewise left alone
        assert await service.cancel_registered(settled.attempt_id) is False
    finally:
        service._active_services.pop("attempt-vanished", None)
        service._active_services.pop(settled.attempt_id, None)


@pytest.mark.asyncio
async def test_cancelling_an_active_attempt_without_a_lease_is_an_integrity_error() -> None:
    """An active Attempt must be cancellable under its own fencing token.

    An active record with no execution lease cannot be terminalized without
    breaking fencing, so cancellation refuses loudly instead of settling the
    record unaccountably.
    """
    from maistro.runs.store import RunIntegrityError

    store, _run_id, node_run_id = await _node_run()
    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())
    attempt = await store.create_attempt(node_run_id, runtime_id="test")
    service._active_services[attempt.attempt_id] = service
    try:
        with pytest.raises(RunIntegrityError, match="missing its execution lease"):
            await service.cancel_registered(attempt.attempt_id)
    finally:
        service._active_services.pop(attempt.attempt_id, None)


# --- cancelling a registered Run -------------------------------------------


@pytest.mark.asyncio
async def test_cancelling_a_registered_run_transitions_a_still_open_run() -> None:
    """`cancel_registered_run` is the owner-visible leg of cancellation.

    When the Run is not fenced CANCELLED yet (the spine asks for cancellation
    before any fence is written), the owning service must transition it, not
    assume someone else did.
    """
    from datetime import timedelta

    store, run_id, node_run_id = await _node_run()
    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())
    await store.transition_run(run_id, RunStatus.QUEUED)
    await store.transition_run(run_id, RunStatus.RUNNING)
    attempt = await store.create_attempt(
        node_run_id,
        runtime_id="test",
        lease_holder="test",
        lease_ttl=timedelta(seconds=30),
    )
    service._active_services[attempt.attempt_id] = service
    try:
        assert await AttemptExecutionService.cancel_registered_run(run_id) is True
        run = await store.get_run(run_id)
        assert run is not None
        assert run.status is RunStatus.CANCELLED
    finally:
        service._active_services.pop(attempt.attempt_id, None)


@pytest.mark.asyncio
async def test_cancelling_a_local_run_for_a_missing_run_is_an_integrity_error() -> None:
    """A Run that vanishes mid-cancel is torn state, not a clean no-op.

    `_active_run_attempts` still sees the Run's rows; `get_run` no longer
    does. That gap must surface as an integrity error rather than an
    assumed CANCELLED.
    """
    from maistro.runs.store import InMemoryRunStore, RunIntegrityError

    class _VanishedRunStore(InMemoryRunStore):
        def __init__(self, **kwargs: object) -> None:
            super().__init__(**kwargs)  # type: ignore[arg-type]
            self._vanished_run_id: str | None = None

        async def get_run(self, run_id: str):
            if run_id == self._vanished_run_id:
                return None
            return await super().get_run(run_id)

    project_store = InMemoryProjectScopeStore()
    root = await project_store.create_root("ws-1")
    torn = _VanishedRunStore(project_store=project_store)
    graph = Graph(
        workspace_id="ws-1",
        project_id=root.project_id,
        name="One node",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await torn.create_run(graph)
    torn._vanished_run_id = run.run_id
    service = AttemptExecutionService(store=torn, runtime=PythonExecutionRuntime())
    with pytest.raises(RunIntegrityError, match="does not exist"):
        await service._cancel_local_run(run.run_id)


@pytest.mark.asyncio
async def test_terminalizing_an_attempt_that_disappeared_mid_execution_is_an_integrity_error() -> (
    None
):
    from maistro.runs.store import RunIntegrityError

    store, _run_id, _node_run_id = await _node_run()
    service = AttemptExecutionService(store=store, runtime=PythonExecutionRuntime())
    with pytest.raises(RunIntegrityError, match="disappeared during execution"):
        await service._terminalize_if_open(
            "attempt-ghost", AttemptStatus.FAILED, fencing_token="token-1"
        )


# --- settled NodeRun cleanup when a Run is cancelled ------------------------


@pytest.mark.asyncio
async def test_run_cancellation_settles_queue_only_node_runs() -> None:
    """Cancellation sweeps exactly the NodeRuns that have nothing left running.

    Three shapes under one cancelled Run: a terminal NodeRun (left as is), a
    NodeRun with a live Attempt (left for its owner), and a NodeRun whose only
    Attempt settled while the NodeRun never re-opened (transitions CANCELLED).
    """
    from datetime import timedelta

    project_store = InMemoryProjectScopeStore()
    root = await project_store.create_root("ws-1")
    store = InMemoryRunStore(project_store=project_store)
    graph = Graph(
        workspace_id="ws-1",
        project_id=root.project_id,
        name="Three nodes",
        nodes=[
            Node(node_id="node-1", node_type="agent"),
            Node(node_id="node-2", node_type="agent"),
            Node(node_id="node-3", node_type="agent"),
        ],
    )
    run = await store.create_run(graph)
    queue_only = await store.create_node_run(run.run_id, node_id="node-1")
    with_live_attempt = await store.create_node_run(run.run_id, node_id="node-2")
    already_terminal = await store.create_node_run(run.run_id, node_id="node-3")

    settled = await store.create_attempt(
        queue_only.node_run_id,
        runtime_id="test",
        lease_holder="test",
        lease_ttl=timedelta(seconds=30),
    )
    await store.transition_attempt(
        settled.attempt_id,
        AttemptStatus.RUNNING,
        fencing_token=_lease_token(settled),
    )
    await store.transition_attempt(
        settled.attempt_id,
        AttemptStatus.COMPLETED,
        result="done",
        fencing_token=_lease_token(settled),
    )

    live = await store.create_attempt(
        with_live_attempt.node_run_id,
        runtime_id="test",
        lease_holder="test",
        lease_ttl=timedelta(seconds=30),
    )
    await store.transition_attempt(
        live.attempt_id,
        AttemptStatus.RUNNING,
        fencing_token=_lease_token(live),
    )

    await store.transition_node_run(already_terminal.node_run_id, RunStatus.CANCELLED)

    service = RunExecutionService(store=store, runtime=PythonExecutionRuntime())
    cancelled = await service.cancel_run(run.run_id)
    assert cancelled.status is RunStatus.CANCELLED

    # The in-memory Run fence cascades CANCELLED to every non-terminal
    # NodeRun, so all three land CANCELLED; the live Attempt itself is left
    # to the durable reclaim sweeper that owns its epoch.
    for node_run_id in (
        queue_only.node_run_id,
        with_live_attempt.node_run_id,
        already_terminal.node_run_id,
    ):
        after = await store.get_node_run(node_run_id)
        assert after is not None
        assert after.status is RunStatus.CANCELLED
    live_attempt = await store.get_attempt(live.attempt_id)
    assert live_attempt is not None
    assert live_attempt.status is AttemptStatus.RUNNING


@pytest.mark.asyncio
async def test_cancel_settled_node_runs_sweeps_exactly_the_queue_only_nodes() -> None:
    """The sweep's own contract, exercised before any Run fence can cascade.

    `RunExecutionService.cancel_run` fences the Run first and the in-memory
    fence already cascades, so this unit call is what pins the sweep itself:
    skip terminal NodeRuns, skip anything with a live Attempt, settle the
    rest as CANCELLED.
    """
    from datetime import timedelta

    from maistro.runs.execution import _cancel_settled_node_runs

    project_store = InMemoryProjectScopeStore()
    root = await project_store.create_root("ws-1")
    store = InMemoryRunStore(project_store=project_store)
    graph = Graph(
        workspace_id="ws-1",
        project_id=root.project_id,
        name="Three nodes",
        nodes=[
            Node(node_id="node-1", node_type="agent"),
            Node(node_id="node-2", node_type="agent"),
            Node(node_id="node-3", node_type="agent"),
        ],
    )
    run = await store.create_run(graph)
    queue_only = await store.create_node_run(run.run_id, node_id="node-1")
    with_live_attempt = await store.create_node_run(run.run_id, node_id="node-2")
    already_terminal = await store.create_node_run(run.run_id, node_id="node-3")

    settled = await store.create_attempt(
        queue_only.node_run_id,
        runtime_id="test",
        lease_holder="test",
        lease_ttl=timedelta(seconds=30),
    )
    await store.transition_attempt(
        settled.attempt_id,
        AttemptStatus.RUNNING,
        fencing_token=_lease_token(settled),
    )
    await store.transition_attempt(
        settled.attempt_id,
        AttemptStatus.COMPLETED,
        result="done",
        fencing_token=_lease_token(settled),
    )

    live = await store.create_attempt(
        with_live_attempt.node_run_id,
        runtime_id="test",
        lease_holder="test",
        lease_ttl=timedelta(seconds=30),
    )
    await store.transition_attempt(
        live.attempt_id,
        AttemptStatus.RUNNING,
        fencing_token=_lease_token(live),
    )

    await store.transition_node_run(already_terminal.node_run_id, RunStatus.CANCELLED)

    await _cancel_settled_node_runs(store, run.run_id)

    queue_only_after = await store.get_node_run(queue_only.node_run_id)
    assert queue_only_after is not None
    assert queue_only_after.status is RunStatus.CANCELLED
    live_after = await store.get_node_run(with_live_attempt.node_run_id)
    assert live_after is not None
    assert live_after.status is not RunStatus.CANCELLED
    terminal_after = await store.get_node_run(already_terminal.node_run_id)
    assert terminal_after is not None
    assert terminal_after.status is RunStatus.CANCELLED
