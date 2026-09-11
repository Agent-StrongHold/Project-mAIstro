from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from maistro.graph.definitions import Graph, Node
from maistro.graph.durable_runs import recovery
from maistro.graph.durable_runs.attempt_executor import LiveAttemptOwned
from maistro.runs.model import GraphSnapshot, Run, RunStatus

pytestmark = [pytest.mark.contract("behavioral")]


def _due_cursor(record) -> tuple[str, str]:
    resume_at = getattr(record, "resume_at", None)
    return (resume_at.isoformat() if resume_at else "", record.run_id)


class _Store:
    def __init__(self, *records) -> None:
        self.records = {record.run_id: record for record in records}

    async def list_due(
        self,
        *,
        now: datetime,
        limit: int = 100,
        after: tuple[str, str] | None = None,
    ):
        del now
        rows = sorted(self.records.values(), key=_due_cursor)
        if after is not None:
            rows = [row for row in rows if _due_cursor(row) > after]
        return rows[:limit]

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
        after: tuple[str, str] | None = None,
    ) -> list[Run]:
        del offset
        rows = sorted(
            (
                run
                for run in self.runs.values()
                if run.status is status and (project_id is None or run.project_id == project_id)
            ),
            key=lambda run: (run.created_at.isoformat(), run.run_id),
        )
        if after is not None:
            rows = [run for run in rows if (run.created_at.isoformat(), run.run_id) > after]
        return rows[:limit]


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
async def test_resume_failure_is_isolated_when_the_record_is_still_eligible(
    monkeypatch, caplog
) -> None:
    """A candidate-local failure (#1143) is logged and isolated, not raised: it
    would otherwise abort the whole tick for one Run's own resolver/node bug,
    exactly the defect #1143 exists to fix. The candidate's durable state is
    untouched, so a later tick can still retry it."""
    now = datetime(2026, 9, 1, 4, 0, tzinfo=UTC)
    waiting = _record("waiting", RunStatus.WAITING, now - timedelta(seconds=1))
    store = _Store(waiting)

    async def _broken(_run_id: str, **kwargs) -> None:
        del kwargs
        raise ValueError("broken recovery invariant")

    monkeypatch.setattr(recovery, "resume_durable_graph", _broken)

    with caplog.at_level("ERROR", logger="maistro.graph.durable_runs.recovery"):
        count = await recovery.resume_due_graph_runs(
            store=store,
            run_store=object(),
            node_resolver=lambda _node_id, _graph: None,
            now=now,
        )

    assert count == 0
    assert "waiting" in caplog.text
    assert "broken recovery invariant" in caplog.text


@pytest.mark.asyncio
async def test_a_poisoned_due_candidate_does_not_starve_later_candidates(monkeypatch) -> None:
    """The core #1143 fixture: three due candidates, the first deterministically
    poisoned. Candidates two and three must still be attempted every tick."""
    now = datetime(2026, 9, 1, 4, 0, tzinfo=UTC)
    poisoned = _record("poisoned", RunStatus.WAITING, now - timedelta(seconds=3))
    second = _record("second", RunStatus.WAITING, now - timedelta(seconds=2))
    third = _record("third", RunStatus.WAITING, now - timedelta(seconds=1))
    store = _Store(poisoned, second, third)
    calls: list[str] = []

    async def _resume(run_id: str, **kwargs) -> None:
        del kwargs
        if run_id == "poisoned":
            raise RuntimeError("resolver bug tied to this one Run")
        calls.append(run_id)

    monkeypatch.setattr(recovery, "resume_durable_graph", _resume)

    count = await recovery.resume_due_graph_runs(
        store=store,
        run_store=object(),
        node_resolver=lambda _node_id, _graph: None,
        now=now,
    )

    assert count == 2
    assert calls == ["second", "third"]


@pytest.mark.asyncio
async def test_a_deliberate_store_failure_aborts_the_tick_rather_than_isolating(
    monkeypatch,
) -> None:
    """A failure raised while *listing* candidates is infrastructure-wide
    (#1143): it invalidates the whole scan and must propagate, never produce a
    misleadingly successful partial count."""
    now = datetime(2026, 9, 1, 4, 0, tzinfo=UTC)

    class _BrokenListingStore(_Store):
        async def list_due(self, **kwargs):
            raise ConnectionError("database connection lost")

    store = _BrokenListingStore(_record("waiting", RunStatus.WAITING, now - timedelta(seconds=1)))

    with pytest.raises(ConnectionError, match="database connection lost"):
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
        node_resolver_factory=lambda _run: lambda _node_id, _graph: None,
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
        node_resolver_factory=lambda _run: lambda _node_id, _graph: None,
    )

    assert recovered == 0
    assert calls == []
    assert await store.get(run.run_id) is None


@pytest.mark.asyncio
async def test_initial_continuation_insert_is_the_cross_replica_bootstrap_claim(
    monkeypatch,
) -> None:
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
        node_resolver_factory=lambda _run: lambda _node_id, _graph: None,
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
        node_resolver_factory=lambda _run: lambda _node_id, _graph: None,
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
            node_resolver_factory=lambda _run: lambda _node_id, _graph: None,
        )
        == 0
    )


@pytest.mark.asyncio
async def test_wakeup_and_queued_ticks_are_noops_for_a_non_positive_limit() -> None:
    """A zero budget must not touch persistence at all, let alone resume."""
    store = _Store()
    run = _queued_run()
    assert (
        await recovery.resume_due_graph_runs(
            store=store,
            run_store=object(),
            node_resolver=lambda _node_id, _graph: None,
            limit=0,
        )
        == 0
    )
    assert (
        await recovery.recover_queued_graph_runs(
            store=store,
            run_store=_RunStore(run),
            node_resolver_factory=lambda _run: lambda _node_id, _graph: None,
            eligible=lambda _candidate: True,
            limit=0,
        )
        == 0
    )
    assert await store.get("waiting") is None


@pytest.mark.asyncio
async def test_wakeup_ignores_a_due_record_the_due_query_still_returned(monkeypatch) -> None:
    """The indexed query over-returns on purpose (HITL reconciliation reads it
    too), so the tick re-checks visibility: a terminal record is never resumed."""
    now = datetime(2026, 9, 1, 4, 0, tzinfo=UTC)
    completed = _record("completed", RunStatus.COMPLETED, now - timedelta(seconds=1))
    store = _Store(completed)
    calls: list[str] = []

    async def _resume(run_id: str, **kwargs) -> None:
        del kwargs
        calls.append(run_id)

    monkeypatch.setattr(recovery, "resume_durable_graph", _resume)

    assert (
        await recovery.resume_due_graph_runs(
            store=store,
            run_store=object(),
            node_resolver=lambda _node_id, _graph: None,
            now=now,
        )
        == 0
    )
    assert calls == []


@pytest.mark.asyncio
async def test_wakeup_tick_yields_to_a_live_attempt_that_still_owns_the_run(
    monkeypatch,
) -> None:
    now = datetime(2026, 9, 1, 4, 0, tzinfo=UTC)
    waiting = _record("waiting", RunStatus.WAITING, now - timedelta(seconds=1))
    store = _Store(waiting)

    async def _owned_elsewhere(run_id: str, **kwargs) -> None:
        del kwargs, run_id
        raise LiveAttemptOwned("another worker holds a live Attempt for this Run")

    monkeypatch.setattr(recovery, "resume_durable_graph", _owned_elsewhere)

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
async def test_a_resume_race_that_vanished_the_record_is_not_reraised(monkeypatch) -> None:
    """A KeyError whose Run no longer exists was someone else completing the
    cleanup; reraising it would fail the whole tick for one settled record."""
    now = datetime(2026, 9, 1, 4, 0, tzinfo=UTC)
    waiting = _record("waiting", RunStatus.WAITING, now - timedelta(seconds=1))
    store = _Store(waiting)

    async def _vanished_mid_resume(run_id: str, **kwargs) -> None:
        del kwargs
        del store.records[run_id]
        raise KeyError(run_id)

    monkeypatch.setattr(recovery, "resume_durable_graph", _vanished_mid_resume)

    assert (
        await recovery.resume_due_graph_runs(
            store=store,
            run_store=object(),
            node_resolver=lambda _node_id, _graph: None,
            now=now,
        )
        == 0
    )


class _ReconcilingStore(_BootstrapStore):
    """A store whose persistence half can be repaired before the tick reads it."""

    def __init__(self, *records) -> None:
        super().__init__(*records)
        self.reconciled: list[int] = []

    async def reconcile_persistence(self, *, limit: int = 100) -> int:
        self.reconciled.append(limit)
        return 0


@pytest.mark.asyncio
async def test_a_tick_reconciles_persistence_before_reading_due_work(monkeypatch) -> None:
    """Crash residue is repaired first, or the tick would read a stale split:
    purged orphans resurfacing as candidates, stepped statuses missed."""
    now = datetime(2026, 9, 1, 4, 0, tzinfo=UTC)
    waiting = _record("waiting", RunStatus.WAITING, now - timedelta(seconds=1))
    store = _ReconcilingStore(waiting)

    async def _resume(run_id: str, **kwargs) -> None:
        del kwargs, run_id

    monkeypatch.setattr(recovery, "resume_durable_graph", _resume)

    assert (
        await recovery.resume_due_graph_runs(
            store=store,
            run_store=object(),
            node_resolver=lambda _node_id, _graph: None,
            now=now,
            limit=7,
        )
        == 1
    )
    assert store.reconciled == [7]

    assert (
        await recovery.recover_queued_graph_runs(
            store=store,
            run_store=_RunStore(_queued_run()),
            node_resolver_factory=lambda _run: lambda _node_id, _graph: None,
            eligible=lambda _candidate: True,
            limit=3,
        )
        == 1
    )
    assert store.reconciled == [7, 3]


class _VanishingBootstrapStore(_Store):
    """A create that fails without leaving the record behind."""

    async def create(self, record):
        raise ValueError(f"persistence refused the claim for {record.run_id!r}")


@pytest.mark.asyncio
async def test_a_failed_bootstrap_claim_that_left_nothing_reraises() -> None:
    """A create that failed *and* left no record is not a race -- it is a
    persistence refusal, and swallowing it would report the Run recovered."""
    run = _queued_run()
    store = _VanishingBootstrapStore()

    with pytest.raises(ValueError, match="persistence refused the claim"):
        await recovery.recover_queued_graph_runs(
            store=store,
            run_store=_RunStore(run),
            node_resolver_factory=lambda _run: lambda _node_id, _graph: None,
            eligible=lambda _candidate: True,
        )


@pytest.mark.asyncio
async def test_queued_recovery_leaves_a_continuation_someone_else_already_moved(
    monkeypatch,
) -> None:
    """A queued candidate whose stored continuation is no longer queued was
    claimed between listing and reading; the winner owns it now."""
    run = _queued_run()
    initial = recovery._initial_queued_record(run)
    moved = initial.model_copy(
        update={"run": initial.run.model_copy(update={"status": RunStatus.RUNNING})}
    )
    store = _BootstrapStore(moved)
    calls: list[str] = []

    async def _resume(run_id: str, **kwargs) -> None:
        del kwargs
        calls.append(run_id)

    monkeypatch.setattr(recovery, "resume_durable_graph", _resume)

    assert (
        await recovery.recover_queued_graph_runs(
            store=store,
            run_store=_RunStore(run),
            node_resolver_factory=lambda _run: lambda _node_id, _graph: None,
            eligible=lambda _candidate: True,
        )
        == 0
    )
    assert calls == []


@pytest.mark.asyncio
async def test_a_queued_resume_failure_reraises_when_the_record_vanished(monkeypatch) -> None:
    run = _queued_run()
    initial = recovery._initial_queued_record(run)
    store = _BootstrapStore(initial)

    async def _vanished_mid_resume(run_id: str, **kwargs) -> None:
        del kwargs
        del store.records[run_id]
        raise KeyError(run_id)

    monkeypatch.setattr(recovery, "resume_durable_graph", _vanished_mid_resume)

    with pytest.raises(KeyError):
        await recovery.recover_queued_graph_runs(
            store=store,
            run_store=_RunStore(run),
            node_resolver_factory=lambda _run: lambda _node_id, _graph: None,
            eligible=lambda _candidate: True,
        )


@pytest.mark.asyncio
async def test_a_queued_resume_failure_is_isolated_when_the_run_is_still_queued(
    monkeypatch, caplog
) -> None:
    """Still queued after the failure means nobody else took it, but the
    failure is still candidate-local (#1143): it is logged and isolated, not
    raised, so the Run stays QUEUED for a later tick instead of aborting the
    batch for every other queued candidate."""
    run = _queued_run()
    initial = recovery._initial_queued_record(run)
    store = _BootstrapStore(initial)

    async def _broken(run_id: str, **kwargs) -> None:
        del kwargs, run_id
        raise ValueError("broken queued recovery invariant")

    monkeypatch.setattr(recovery, "resume_durable_graph", _broken)

    with caplog.at_level("ERROR", logger="maistro.graph.durable_runs.recovery"):
        recovered = await recovery.recover_queued_graph_runs(
            store=store,
            run_store=_RunStore(run),
            node_resolver_factory=lambda _run: lambda _node_id, _graph: None,
            eligible=lambda _candidate: True,
        )

    assert recovered == 0
    assert "broken queued recovery invariant" in caplog.text
    still_queued = await store.get(run.run_id)
    assert still_queued is not None
    assert still_queued.run.status is RunStatus.QUEUED


@pytest.mark.asyncio
async def test_a_poisoned_queued_candidate_does_not_starve_later_candidates(monkeypatch) -> None:
    """The #1143 fixture for the queued path: three eligible QUEUED Runs, the
    first deterministically poisoned. The other two must still be attempted."""
    poisoned = _queued_run("poisoned")
    second = _queued_run("second")
    third = _queued_run("third")
    run_store = _RunStore(poisoned, second, third)
    store = _BootstrapStore()
    calls: list[str] = []

    async def _resume(run_id: str, **kwargs) -> None:
        del kwargs
        if run_id == "poisoned":
            raise RuntimeError("resolver bug tied to this one Run")
        calls.append(run_id)

    monkeypatch.setattr(recovery, "resume_durable_graph", _resume)

    recovered = await recovery.recover_queued_graph_runs(
        store=store,
        run_store=run_store,
        eligible=lambda _candidate: True,
        node_resolver_factory=lambda _run: lambda _node_id, _graph: None,
    )

    assert recovered == 2
    assert sorted(calls) == ["second", "third"]


@pytest.mark.asyncio
async def test_a_deliberate_run_store_failure_aborts_the_queued_tick(monkeypatch) -> None:
    """A failure raised while listing QUEUED candidates is infrastructure-wide
    (#1143) and must abort the tick rather than being isolated per candidate."""

    class _BrokenListingRunStore(_RunStore):
        async def list_by_status(self, *args, **kwargs):
            raise ConnectionError("database connection lost")

    run = _queued_run()
    store = _BootstrapStore()

    with pytest.raises(ConnectionError, match="database connection lost"):
        await recovery.recover_queued_graph_runs(
            store=store,
            run_store=_BrokenListingRunStore(run),
            eligible=lambda _candidate: True,
            node_resolver_factory=lambda _run: lambda _node_id, _graph: None,
        )


@pytest.mark.asyncio
async def test_queued_recovery_yields_when_a_live_attempt_already_owns_the_run(
    monkeypatch,
) -> None:
    """The Attempt lease outranks this tick's claim to the same queued Run."""
    run = _queued_run()
    initial = recovery._initial_queued_record(run)
    store = _BootstrapStore(initial)

    async def _owned_elsewhere(run_id: str, **kwargs) -> None:
        del kwargs, run_id
        raise LiveAttemptOwned("another worker holds a live Attempt for this Run")

    monkeypatch.setattr(recovery, "resume_durable_graph", _owned_elsewhere)

    assert (
        await recovery.recover_queued_graph_runs(
            store=store,
            run_store=_RunStore(run),
            node_resolver_factory=lambda _run: lambda _node_id, _graph: None,
            eligible=lambda _candidate: True,
        )
        == 0
    )


class _Sink:
    """Recording stand-in for the canonical recovery Event sink."""

    def __init__(self) -> None:
        self.facts: list = []

    async def emit(self, event) -> None:
        self.facts.append(event)


def _due_record(run: Run, *, resume_at: datetime) -> object:
    """A due WAITING candidate whose Run carries provenance a tick must read."""
    return SimpleNamespace(run_id=run.run_id, run=run, resume_at=resume_at)


@pytest.mark.asyncio
async def test_wakeup_rebuilds_the_resolver_from_each_candidates_own_run(monkeypatch) -> None:
    """A production wakeup consumer resolves nodes from durable Run facts, not
    from a resolver this process happened to be wired with at admission."""
    now = datetime(2026, 9, 1, 4, 0, tzinfo=UTC)
    run = _queued_run("waiting-owned", source="hive_legacy_dag")
    waiting = run.model_copy(update={"status": RunStatus.WAITING})
    store = _Store(_due_record(waiting, resume_at=now - timedelta(seconds=1)))
    seen_runs: list[str] = []
    calls: list[str] = []

    def _factory(candidate: Run) -> object:
        seen_runs.append(candidate.run_id)
        return lambda _node_id, _graph: calls.append(_node_id)

    async def _resume(run_id: str, **kwargs) -> None:
        assert kwargs["node_resolver"]("node-1", object()) is None

    monkeypatch.setattr(recovery, "resume_durable_graph", _resume)

    count = await recovery.resume_due_graph_runs(
        store=store,
        run_store=object(),
        node_resolver_factory=_factory,
        now=now,
    )

    assert count == 1
    assert seen_runs == [waiting.run_id]


@pytest.mark.asyncio
async def test_wakeup_never_steals_a_due_continuation_owned_elsewhere(monkeypatch) -> None:
    """The same admission-source guard the bootstrap tick takes: without it a
    wakeup consumer would execute another consumer's paused work with resolvers
    that cannot possibly know how."""
    now = datetime(2026, 9, 1, 4, 0, tzinfo=UTC)
    foreign = _queued_run("waiting-foreign", source="some_other_consumer").model_copy(
        update={"status": RunStatus.WAITING}
    )
    store = _Store(_due_record(foreign, resume_at=now - timedelta(seconds=1)))
    calls: list[str] = []

    async def _resume(run_id: str, **kwargs) -> None:
        del kwargs
        calls.append(run_id)

    monkeypatch.setattr(recovery, "resume_durable_graph", _resume)

    assert (
        await recovery.resume_due_graph_runs(
            store=store,
            run_store=object(),
            node_resolver_factory=lambda _run: lambda _node_id, _graph: None,
            eligible=lambda candidate: (
                candidate.provenance.get("admission_source") == "hive_legacy_dag"
            ),
            now=now,
        )
        == 0
    )
    assert calls == []


@pytest.mark.asyncio
async def test_wakeup_requires_exactly_one_resolver_shape() -> None:
    """Both shapes means the caller cannot say which one wins; neither means
    the tick has no idea how to execute anything."""
    with pytest.raises(ValueError, match="exactly one of node_resolver"):
        await recovery.resume_due_graph_runs(
            store=_Store(),
            run_store=object(),
            node_resolver=lambda _node_id, _graph: None,
            node_resolver_factory=lambda _run: lambda _node_id, _graph: None,
        )
    with pytest.raises(ValueError, match="exactly one of node_resolver"):
        await recovery.resume_due_graph_runs(store=_Store(), run_store=object())


@pytest.mark.asyncio
async def test_wakeup_threads_the_recovery_event_sink_into_the_resume(monkeypatch) -> None:
    """The tick's crash dispositions must land on the canonical Event stream
    through the same sink the abandoned-Attempt sweep uses (#62)."""
    now = datetime(2026, 9, 1, 4, 0, tzinfo=UTC)
    run = _queued_run("waiting-events", source="hive_legacy_dag").model_copy(
        update={"status": RunStatus.WAITING}
    )
    store = _Store(_due_record(run, resume_at=now - timedelta(seconds=1)))
    sink = _Sink()
    seen: dict[str, object] = {}

    async def _resume(run_id: str, **kwargs) -> None:
        seen["events"] = kwargs.get("events")

    monkeypatch.setattr(recovery, "resume_durable_graph", _resume)

    await recovery.resume_due_graph_runs(
        store=store,
        run_store=object(),
        node_resolver=lambda _node_id, _graph: None,
        events=sink,
        now=now,
    )

    assert seen["events"] is sink


@pytest.mark.asyncio
async def test_queued_recovery_threads_the_recovery_event_sink_into_the_resume(
    monkeypatch,
) -> None:
    run = _queued_run()
    store = _BootstrapStore(recovery._initial_queued_record(run))
    sink = _Sink()
    seen: dict[str, object] = {}

    async def _resume(run_id: str, **kwargs) -> None:
        del run_id
        seen["events"] = kwargs.get("events")

    monkeypatch.setattr(recovery, "resume_durable_graph", _resume)

    await recovery.recover_queued_graph_runs(
        store=store,
        run_store=_RunStore(run),
        node_resolver_factory=lambda _run: lambda _node_id, _graph: None,
        eligible=lambda _candidate: True,
        events=sink,
    )

    assert seen["events"] is sink
