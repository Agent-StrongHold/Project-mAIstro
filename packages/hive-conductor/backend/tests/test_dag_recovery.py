from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from maistro.graph.definitions import Graph
from maistro.runs.model import GraphSnapshot, Run, RunStatus


def _legacy_dag() -> dict:
    return {
        "id": "recoverable-dag",
        "name": "recoverable-dag",
        "nodes": [
            {
                "id": "n1",
                "name": "worker",
                "role": "worker",
                "prompt": "do the work",
                "config": {"execution_tier": "safe"},
            }
        ],
        "edges": [],
        "entry_node": "n1",
    }


def _queued_run(*, mode: str = "interactive", source: str = "hive_legacy_dag") -> tuple[Run, Graph]:
    import services.canonical_dag_runner as runner

    graph = runner.graph_from_legacy_dag(_legacy_dag(), workspace_id="ws-1", project_id="project-1")
    run = Run(
        run_id="run-recoverable",
        workspace_id=graph.workspace_id,
        project_id=graph.project_id,
        graph=GraphSnapshot.from_graph(graph),
        status=RunStatus.QUEUED,
        actor_principal_id="user-1",
        provenance={
            "admission_source": source,
            "legacy_dag_id": "recoverable-dag",
            "executor": "durable_graph",
            "execution_mode": mode,
        },
    )
    return run, graph


def test_recovery_resolver_rehydrates_node_and_execution_mode_from_run_snapshot() -> None:
    import services.canonical_dag_runner as runner

    run, graph = _queued_run(mode="interactive")
    resolver = runner._recovery_resolver(run)
    node = resolver("n1", graph)

    assert node._raw_node["prompt"] == "do the work"
    assert node._execution_mode == "interactive"
    assert node._node_env["DAG_USER_ID"] == "user-1"
    assert node._node_env["DAG_ID"] == "recoverable-dag"
    assert not any(key.startswith("USER_CRED_") for key in node._node_env)


def test_recovery_resolver_rejects_a_run_whose_mode_is_not_a_legacy_mode() -> None:
    """The durable snapshot is the only source of truth for how the Run may
    execute; an execution_mode outside the two the adapter admits is not a
    default waiting to happen but a corrupt admission."""
    import services.canonical_dag_runner as runner

    run, _graph = _queued_run(mode="batch")
    with pytest.raises(ValueError, match="invalid legacy execution_mode"):
        runner._recovery_resolver(run)


@pytest.mark.asyncio
async def test_recovery_owns_only_hive_legacy_admissions(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.canonical_dag_runner as runner

    graph_store = object()
    run_store = object()
    container = SimpleNamespace(graph_run_store=graph_store, run_store=run_store)
    captured: dict = {}

    async def _recover(**kwargs):
        captured.update(kwargs)
        return 3

    monkeypatch.setattr(runner, "_container", lambda: container)
    monkeypatch.setattr(runner, "recover_queued_graph_runs", _recover)

    assert await runner.recover_stranded_dag_runs(limit=7) == 3
    assert captured["store"] is graph_store
    assert captured["run_store"] is run_store
    assert captured["limit"] == 7

    owned, _ = _queued_run(source="hive_legacy_dag")
    foreign, _ = _queued_run(source="some_other_consumer")
    assert captured["eligible"](owned) is True
    assert captured["eligible"](foreign) is False


@pytest.mark.asyncio
async def test_admitted_run_persists_execution_mode_needed_after_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.canonical_dag_runner as runner

    seen: dict = {}

    class _RunStore:
        async def create_run(self, graph, **kwargs):
            seen["create_graph"] = graph
            seen["create"] = kwargs
            return SimpleNamespace(run_id="run-1")

    canonical_run_store = _RunStore()

    async def _scope(*args, **kwargs):
        del args, kwargs
        return "ws-1", "project-1", canonical_run_store

    async def _run_durable_graph(graph, **kwargs):
        seen["execute_graph"] = graph
        seen["execute"] = kwargs
        return SimpleNamespace(
            run_id="run-1",
            run=SimpleNamespace(status=RunStatus.WAITING, error=None),
            node_runs=(),
            graph_state=SimpleNamespace(cycle=0, blackboard_snapshot={"node_annotations": {}}),
        )

    monkeypatch.setattr(runner, "_scope", _scope)
    monkeypatch.setattr(runner, "get_run_store", lambda: object())
    monkeypatch.setattr(runner, "run_durable_graph", _run_durable_graph)

    result = await runner.execute_dag(_legacy_dag(), execution_mode="interactive")

    assert result["status"] == "waiting"
    assert seen["create"]["provenance"]["execution_mode"] == "interactive"
    assert seen["execute"]["provenance"]["execution_mode"] == "interactive"
    assert seen["execute"]["run_id"] == "run-1"


@pytest.mark.asyncio
async def test_recovery_cadence_starts_runs_a_tick_and_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.dag_recovery as recovery_driver

    ticked = asyncio.Event()

    async def _recover() -> int:
        ticked.set()
        return 0

    await recovery_driver.stop_dag_recovery()
    monkeypatch.setattr(recovery_driver, "recover_stranded_dag_runs", _recover)
    monkeypatch.setattr(recovery_driver, "_INTERVAL_S", 3600.0)

    recovery_driver.start_dag_recovery()
    await asyncio.wait_for(ticked.wait(), timeout=1.0)
    # `recovery_running()` left with the pre-#835 scheduler surface: the
    # driver's liveness is its task, which is the only state it owns.
    assert recovery_driver._task is not None
    assert not recovery_driver._task.done()

    await recovery_driver.stop_dag_recovery()
    assert recovery_driver._task is None


@pytest.mark.asyncio
async def test_recovery_cadence_survives_a_failing_tick_and_logs_recoveries(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """One malformed candidate must not kill the cadence, and a productive
    tick is reported, not swallowed: the log is the driver's only surface."""
    import logging

    import services.dag_recovery as recovery_driver

    ticks = {"count": 0}
    recovered = asyncio.Event()

    async def _tick() -> int:
        ticks["count"] += 1
        if ticks["count"] == 1:
            raise ValueError("malformed candidate")
        recovered.set()
        return 3

    await recovery_driver.stop_dag_recovery()
    monkeypatch.setattr(recovery_driver, "recover_stranded_dag_runs", _tick)
    monkeypatch.setattr(recovery_driver, "_INTERVAL_S", 0.001)

    recovery_driver.start_dag_recovery()
    with caplog.at_level(logging.INFO, logger="hive.dag_recovery"):
        await asyncio.wait_for(recovered.wait(), timeout=5.0)

    assert any("legacy_dag_recovery_tick_failed" in r.message for r in caplog.records)
    assert any("recovered=3" in r.message for r in caplog.records)

    await recovery_driver.stop_dag_recovery()
    assert recovery_driver._task is None


@pytest.mark.asyncio
async def test_recovery_cadence_cancellation_during_a_tick_ends_the_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cancel delivered while a tick is in flight must propagate as a
    cancellation, not be logged as another malformed candidate."""
    import services.dag_recovery as recovery_driver

    in_tick = asyncio.Event()

    async def _hanging_tick() -> int:
        in_tick.set()
        await asyncio.Event().wait()  # blocks until cancelled
        return 0  # pragma: no cover - unreachable once cancelled

    await recovery_driver.stop_dag_recovery()
    monkeypatch.setattr(recovery_driver, "recover_stranded_dag_runs", _hanging_tick)

    recovery_driver.start_dag_recovery()
    await asyncio.wait_for(in_tick.wait(), timeout=1.0)
    task = recovery_driver._task

    await recovery_driver.stop_dag_recovery()

    assert recovery_driver._task is None
    assert task.cancelled()


@pytest.mark.asyncio
async def test_starting_the_recovery_cadence_twice_keeps_one_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`start` is idempotent: two starts must not leave two cadences ticking,
    or one shutdown join would strand the other."""
    import services.dag_recovery as recovery_driver

    ticked = asyncio.Event()

    async def _recover() -> int:
        ticked.set()
        return 0

    await recovery_driver.stop_dag_recovery()
    monkeypatch.setattr(recovery_driver, "recover_stranded_dag_runs", _recover)
    monkeypatch.setattr(recovery_driver, "_INTERVAL_S", 3600.0)

    recovery_driver.start_dag_recovery()
    first = recovery_driver._task
    recovery_driver.start_dag_recovery()

    assert recovery_driver._task is first

    await recovery_driver.stop_dag_recovery()


@pytest.mark.asyncio
async def test_wakeup_owns_only_hive_legacy_admissions(monkeypatch: pytest.MonkeyPatch) -> None:
    """The timed half of the recovery cadence wakes due continuations through
    the canonical seam with the same ownership rule as the bootstrap half, and
    reports its crash dispositions on the Container's canonical Event bus."""
    import services.canonical_dag_runner as runner

    event_bus = object()
    container = SimpleNamespace(
        graph_run_store=object(),
        run_store=object(),
        event_bus=event_bus,
    )
    captured: dict = {}

    async def _wake(**kwargs):
        captured.update(kwargs)
        return 2

    monkeypatch.setattr(runner, "_container", lambda: container)
    monkeypatch.setattr(runner, "resume_due_graph_runs", _wake)

    assert await runner.wake_due_dag_runs(limit=5) == 2
    assert captured["store"] is container.graph_run_store
    assert captured["run_store"] is container.run_store
    assert captured["events"] is event_bus
    assert captured["limit"] == 5

    owned, _ = _queued_run(source="hive_legacy_dag")
    foreign, _ = _queued_run(source="some_other_consumer")
    assert captured["eligible"](owned) is True
    assert captured["eligible"](foreign) is False


@pytest.mark.asyncio
async def test_wakeup_is_a_noop_without_a_container_or_graph_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Standalone Conductor deployments keep today's behavior: no Container,
    no canonical tick, no fabricated work."""
    import services.canonical_dag_runner as runner

    async def _boom(**kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("wake_due_dag_runs must not reach the seam without a Container")

    monkeypatch.setattr(runner, "resume_due_graph_runs", _boom)

    monkeypatch.setattr(runner, "_container", lambda: None)
    assert await runner.wake_due_dag_runs() == 0

    monkeypatch.setattr(
        runner, "_container", lambda: SimpleNamespace(graph_run_store=None, run_store=object())
    )
    assert await runner.wake_due_dag_runs() == 0


@pytest.mark.asyncio
async def test_recovery_cadence_wakes_due_runs_and_survives_a_failed_half(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cadence's two halves are isolated: a bootstrap failure must not
    silence the timed wakeup in the same tick, and neither kills the loop."""
    import services.dag_recovery as cadence

    calls: list[str] = []

    async def _failing_recover():
        calls.append("recover")
        raise RuntimeError("one malformed queued candidate")

    async def _waking():
        calls.append("wake")
        return 1

    # The cadence bound these names at import, so the seam is patched where
    # the loop resolves them: on the cadence module itself.
    monkeypatch.setattr(cadence, "recover_stranded_dag_runs", _failing_recover)
    monkeypatch.setattr(cadence, "wake_due_dag_runs", _waking)
    # Real asyncio.sleep at a test cadence, so the loop spins without
    # wall-clock delay and without patching the shared asyncio module.
    monkeypatch.setattr(cadence, "_INTERVAL_S", 0.01)

    cadence.start_dag_recovery()
    try:
        await asyncio.wait_for(_observed(calls, ["recover", "wake", "recover", "wake"]), timeout=5)
    finally:
        await cadence.stop_dag_recovery()


async def _observed(calls: list[str], expected: list[str]) -> None:
    while calls[: len(expected)] != expected:
        await asyncio.sleep(0.01)
