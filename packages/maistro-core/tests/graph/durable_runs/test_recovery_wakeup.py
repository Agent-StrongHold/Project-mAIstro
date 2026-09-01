from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from maistro.graph.definitions import Graph, Node
from maistro.graph.durable_runs import recovery
from maistro.runs.model import GraphSnapshot, Run, RunStatus

pytestmark = [pytest.mark.contract("behavioral")]


class _Store:
    def __init__(self, *records) -> None:
        self.records = {record.run_id: record for record in records}

    async def list_due(self, *, now: datetime, limit: int = 100):
        del now
        return list(self.records.values())[:limit]

    async def get(self, run_id: str):
        return self.records.get(run_id)


class _BootstrapStore(_Store):
    def __init__(self, *records, lose_create_race: bool = False) -> None:
        super().__init__(*records)
        self.lose_create_race = lose_create_race

    async def create(self, record):
        if self.lose_create_race:
            self.records[record.run_id] = record
            raise ValueError(f"run_id collision: {record.run_id!r}")
        if record.run_id in self.records:
            raise ValueError(f"run_id collision: {record.run_id!r}")
        self.records[record.run_id] = record
        return record


class _RunStore:
    def __init__(self, *runs: Run) -> None:
        self.runs = {run.run_id: run for run in runs}

    async def list_by_status(
        self,
        status: RunStatus,
        *,
        limit: int = 100,
        offset: int = 0,
        project_id: str | None = None,
        after=None,
    ) -> list[Run]:
        del offset, after
        return [
            run
            for run in self.runs.values()
            if run.status is status and (project_id is None or run.project_id == project_id)
        ][:limit]


def _record(run_id: str, status: RunStatus, resume_at: datetime | None):
    return SimpleNamespace(
        run_id=run_id,
        run=SimpleNamespace(status=status),
        resume_at=resume_at,
    )


def _queued_run(run_id: str = "queued", *, source: str = "owned") -> Run:
    graph = Graph(
        graph_id=f"graph-{run_id}",
        workspace_id="ws-1",
        project_id="project-1",
        name="Recovery graph",
        nodes=[Node(node_id="node-1", node_type="test.recovery", name="Node")],
    )
    return Run(
        run_id=run_id,
        workspace_id=graph.workspace_id,
        project_id=graph.project_id,
        graph=GraphSnapshot.from_graph(graph),
        status=RunStatus.QUEUED,
        provenance={"admission_source": source},
    )


@pytest.mark.asyncio
async def test_wakeup_executes_due_waiting_graphs_but_never_hitl_pauses(monkeypatch) -> None:
    now = datetime(2026, 9, 1, 4, 0, tzinfo=UTC)
    waiting = _record("waiting", RunStatus.WAITING, now - timedelta(seconds=1))
    paused = _record("paused", RunStatus.PAUSED, now - timedelta(seconds=2))
    future = _record("future", RunStatus.WAITING, now + timedelta(seconds=1))
    store = _Store(waiting, paused, future)
    calls: list[str] = []

    async def _resume(run_id: str, **kwargs) -> None:
        del kwargs
        calls.append(run_id)

    monkeypatch.setattr(recovery, "resume_durable_graph", _resume)

    count = await recovery.resume_due_graph_runs(
        store=store,
        run_store=object(),
        node_resolver=lambda _node_id, _graph: None,
        now=now,
    )

    assert count == 1
    assert calls == ["waiting"]


@pytest.mark.asyncio
async def test_losing_a_cross_replica_resume_race_is_idempotent(monkeypatch) -> None:
    now = datetime(2026, 9, 1, 4, 0, tzinfo=UTC)
    waiting = _record("waiting", RunStatus.WAITING, now - timedelta(seconds=1))
    store = _Store(waiting)

    async def _lose_race(run_id: str, **kwargs) -> None:
        del kwargs
        store.records[run_id] = _record(run_id, RunStatus.RUNNING, None)
        raise ValueError("version regression: another worker won")

    monkeypatch.setattr(recovery, "resume_durable_graph", _lose_race)

    assert (
        await recovery.resume_due_graph_runs(
            store=store,
            run_store=object(),
            node_resolver=lambda _node_id, _graph: None,
            now=now,
        )
        == 0
    )


@pytest.mark.asyncio
async def test_resume_failure_stays_visible_when_the_record_is_still_eligible(monkeypatch) -> None:
    now = datetime(2026, 9, 1, 4, 0, tzinfo=UTC)
    waiting = _record("waiting", RunStatus.WAITING, now - timedelta(seconds=1))
    store = _Store(waiting)

    async def _broken(_run_id: str, **kwargs) -> None:
        del kwargs
        raise ValueError("broken recovery invariant")

    monkeypatch.setattr(recovery, "resume_durable_graph", _broken)

    with pytest.raises(ValueError, match="broken recovery invariant"):
        await recovery.resume_due_graph_runs(
            store=store,
            run_store=object(),
            node_resolver=lambda _node_id, _graph: None,
            now=now,
        )


@pytest.mark.asyncio
async def test_queued_run_without_continuation_is_claimed_then_resumed(monkeypatch) -> None:
    run = _queued_run()
    run_store = _RunStore(run)
    store = _BootstrapStore()
    calls: list[str] = []

    async def _resume(run_id: str, **kwargs) -> None:
        del kwargs
        calls.append(run_id)

    monkeypatch.setattr(recovery, "resume_durable_graph", _resume)

    recovered = await recovery.recover_queued_graph_runs(
        store=store,
        run_store=run_store,
        eligible=lambda candidate: candidate.provenance.get("admission_source") == "owned",
        node_resolver_factory=lambda _run: (lambda _node_id, _graph: None),
    )

    assert recovered == 1
    assert calls == [run.run_id]
    initial = await store.get(run.run_id)
    assert initial is not None
    assert initial.version == 1
    assert initial.graph_state.active_node_ids == ("node-1",)


@pytest.mark.asyncio
async def test_queued_recovery_never_steals_an_unowned_admission_source(monkeypatch) -> None:
    run = _queued_run(source="some_other_consumer")
    store = _BootstrapStore()
    calls: list[str] = []

    async def _resume(run_id: str, **kwargs) -> None:
        del kwargs
        calls.append(run_id)

    monkeypatch.setattr(recovery, "resume_durable_graph", _resume)

    recovered = await recovery.recover_queued_graph_runs(
        store=store,
        run_store=_RunStore(run),
        eligible=lambda candidate: candidate.provenance.get("admission_source") == "owned",
        node_resolver_factory=lambda _run: (lambda _node_id, _graph: None),
    )

    assert recovered == 0
    assert calls == []
    assert await store.get(run.run_id) is None


@pytest.mark.asyncio
async def test_initial_continuation_insert_is_the_cross_replica_bootstrap_claim(monkeypatch) -> None:
    run = _queued_run()
    store = _BootstrapStore(lose_create_race=True)
    calls: list[str] = []

    async def _resume(run_id: str, **kwargs) -> None:
        del kwargs
        calls.append(run_id)

    monkeypatch.setattr(recovery, "resume_durable_graph", _resume)

    recovered = await recovery.recover_queued_graph_runs(
        store=store,
        run_store=_RunStore(run),
        eligible=lambda _candidate: True,
        node_resolver_factory=lambda _run: (lambda _node_id, _graph: None),
    )

    assert recovered == 0
    assert calls == []
    assert await store.get(run.run_id) is not None


@pytest.mark.asyncio
async def test_existing_queued_continuation_is_resumed_after_bootstrap_process_loss(
    monkeypatch,
) -> None:
    run = _queued_run()
    initial = recovery._initial_queued_record(run)
    store = _BootstrapStore(initial)
    calls: list[str] = []

    async def _resume(run_id: str, **kwargs) -> None:
        del kwargs
        calls.append(run_id)

    monkeypatch.setattr(recovery, "resume_durable_graph", _resume)

    recovered = await recovery.recover_queued_graph_runs(
        store=store,
        run_store=_RunStore(run),
        eligible=lambda _candidate: True,
        node_resolver_factory=lambda _run: (lambda _node_id, _graph: None),
    )

    assert recovered == 1
    assert calls == [run.run_id]


@pytest.mark.asyncio
async def test_queued_resume_race_uses_canonical_status_to_yield_to_the_winner(monkeypatch) -> None:
    run = _queued_run()
    initial = recovery._initial_queued_record(run)
    store = _BootstrapStore(initial)

    async def _lose_race(run_id: str, **kwargs) -> None:
        del kwargs
        current = store.records[run_id]
        store.records[run_id] = current.model_copy(
            update={"run": current.run.model_copy(update={"status": RunStatus.RUNNING})}
        )
        raise ValueError("version regression: another worker won")

    monkeypatch.setattr(recovery, "resume_durable_graph", _lose_race)

    assert (
        await recovery.recover_queued_graph_runs(
            store=store,
            run_store=_RunStore(run),
            eligible=lambda _candidate: True,
            node_resolver_factory=lambda _run: (lambda _node_id, _graph: None),
        )
        == 0
    )
