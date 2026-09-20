from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from maistro.graph.definitions import Graph, Node
from maistro.graph.durable_runs import DurableRunRecord, InMemoryDurableRunStore, recovery
from maistro.graph.durable_runs.attempt_executor import LiveAttemptOwned
from maistro.graph.execution_state import GraphExecutionState
from maistro.runs.model import GraphSnapshot, Run, RunStatus
from maistro.runs.store import run_cursor_key

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
        self.admission_source_queries: list[str | None] = []

    async def list_by_status(
        self,
        status: RunStatus,
        *,
        limit: int = 100,
        offset: int = 0,
        project_id: str | None = None,
        admission_source: str | None = None,
        after: tuple[str, str] | None = None,
    ) -> list[Run]:
        del offset
        self.admission_source_queries.append(admission_source)
        runs = [
            run
            for run in self.runs.values()
            if run.status is status
            and (project_id is None or run.project_id == project_id)
            and (
                admission_source is None
                or run.provenance.get("admission_source") == admission_source
            )
        ]
        runs.sort(key=run_cursor_key)
        if after is not None:
            runs = [run for run in runs if run_cursor_key(run) > after]
        return runs[:limit]


class _DueInMemoryStore(InMemoryDurableRunStore):
    async def list_due(
        self,
        *,
        now: datetime,
        limit: int = 100,
        after: tuple[str, str] | None = None,
    ):
        del now, after
        records = [await self.get(run_id) for run_id in self._rows]
        return [record for record in records if record is not None][:limit]


class _FailingRunStore:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def get_run(self, run_id: str):
        self.calls.append(run_id)
        raise OSError("canonical database session is unavailable")


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
async def test_one_unexpected_candidate_failure_does_not_starve_later_due_runs(
    monkeypatch,
    caplog,
) -> None:
    """Candidate-local failures advance this batch and remain due for retry."""
    now = datetime(2026, 9, 1, 4, 0, tzinfo=UTC)
    candidates = [
        _record(f"waiting-{index}", RunStatus.WAITING, now - timedelta(seconds=1))
        for index in range(1, 4)
    ]
    store = _Store(*candidates)
    calls: list[str] = []

    async def _resume(run_id: str, **kwargs) -> None:
        del kwargs
        calls.append(run_id)
        if run_id == "waiting-1":
            raise RuntimeError("resolver exploded password=not-a-secret")

    monkeypatch.setattr(recovery, "resume_durable_graph", _resume)

    with caplog.at_level("WARNING", logger="maistro.graph.durable_runs.recovery"):
        count = await recovery.resume_due_graph_runs(
            store=store,
            run_store=object(),
            node_resolver=lambda _node_id, _graph: None,
            now=now,
        )

    assert count == 2
    assert calls == ["waiting-1", "waiting-2", "waiting-3"]
    assert await store.get("waiting-1") is candidates[0]
    assert "run_id=waiting-1" in caplog.text
    assert "RuntimeError: resolver exploded password=<redacted>" in caplog.text
    assert "not-a-secret" not in caplog.text

    calls.clear()
    assert (
        await recovery.resume_due_graph_runs(
            store=store,
            run_store=object(),
            node_resolver=lambda _node_id, _graph: None,
            now=now,
        )
        == 2
    )
    assert calls == ["waiting-1", "waiting-2", "waiting-3"]


@pytest.mark.asyncio
async def test_factory_failure_terminalizes_each_candidate_for_later_recovery() -> None:
    """A real resolver failure uses durable failure policy for every candidate."""
    now = datetime(2026, 9, 1, 4, 0, tzinfo=UTC)
    runs = [
        _queued_run(f"resolver-poisoned-{index}").model_copy(update={"status": RunStatus.WAITING})
        for index in range(1, 4)
    ]
    store = _DueInMemoryStore()
    for run in runs:
        await store.create(
            DurableRunRecord(
                run=run,
                graph_state=GraphExecutionState(
                    run_id=run.run_id,
                    active_node_ids=("node-1",),
                    blackboard_snapshot={"task_objective": "Recovery graph"},
                ),
                resume_at=now - timedelta(seconds=1),
                version=1,
            )
        )

    factory_calls: list[str] = []

    def _broken_factory(run: Run):
        factory_calls.append(run.run_id)
        raise RuntimeError(f"resolver unavailable for {run.run_id}")

    assert (
        await recovery.resume_due_graph_runs(
            store=store,
            run_store=None,
            node_resolver_factory=_broken_factory,
            now=now,
        )
        == 3
    )
    assert factory_calls == [run.run_id for run in runs]
    for run in runs:
        failed = await store.get(run.run_id)
        assert failed is not None
        assert failed.run.status is RunStatus.FAILED
        assert failed.run.error == (
            "PhysicalExecutionError: node resolver could not be built for Run "
            f"{run.run_id!r}: RuntimeError"
        )


@pytest.mark.asyncio
async def test_factory_failure_text_never_reaches_the_failed_run() -> None:
    """The persisted failure is the stable message, not the factory's own text."""
    now = datetime(2026, 9, 1, 4, 0, tzinfo=UTC)
    run = _queued_run("resolver-leaky").model_copy(update={"status": RunStatus.WAITING})
    store = _DueInMemoryStore()
    await store.create(
        DurableRunRecord(
            run=run,
            graph_state=GraphExecutionState(
                run_id=run.run_id,
                active_node_ids=("node-1",),
                blackboard_snapshot={"task_objective": "Recovery graph"},
            ),
            resume_at=now - timedelta(seconds=1),
            version=1,
        )
    )

    def _leaky_factory(_run: Run):
        raise ConnectionError("provider refused {'api_key': 'sk-live'}")

    assert (
        await recovery.resume_due_graph_runs(
            store=store,
            run_store=None,
            node_resolver_factory=_leaky_factory,
            now=now,
        )
        == 1
    )
    failed = await store.get(run.run_id)
    assert failed is not None
    assert failed.run.status is RunStatus.FAILED
    assert failed.run.error == (
        "PhysicalExecutionError: node resolver could not be built for Run "
        "'resolver-leaky': ConnectionError"
    )
    assert "sk-live" not in failed.run.error
    assert "provider refused" not in failed.run.error


def test_lazy_resolver_keeps_the_factory_error_as_the_cause() -> None:
    """Operators can still see the underlying failure in-process."""
    run = _queued_run("resolver-cause")
    original = ValueError("no provider for tenant")

    def _factory(_run: Run):
        raise original

    resolve = recovery._lazy_resolver(run, _factory)
    with pytest.raises(recovery.NodeResolverUnavailable) as caught:
        resolve("node-1", object())
    assert caught.value.__cause__ is original
    assert str(caught.value) == (
        "node resolver could not be built for Run 'resolver-cause': ValueError"
    )


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("resolver exploded password=not-a-secret", "password=<redacted>"),
        ("bad config {'api_key': 'sk-live'}", "bad config {api_key=<redacted>}"),
        (
            'header {"Authorization": "Bearer sk-live"} rejected',
            "header {Authorization=<redacted>} rejected",
        ),
        ("Authorization: Bearer eyJhbGciOi.xyz, retry later", "Authorization=<redacted>, retry"),
        ("Bearer abc.def.ghi rejected", "Bearer <redacted> rejected"),
        ("provider rejected key sk-proj-ABCdef123456 for tenant", "key <redacted-key> for"),
        ("token: ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345 expired", "token=<redacted> expired"),
        ("AWS AKIAIOSFODNN7EXAMPLE denied", "AWS <redacted-key> denied"),
    ],
)
def test_sanitized_cause_redacts_quoted_header_and_provider_credentials(
    message: str, expected: str
) -> None:
    sanitized = recovery._sanitized_cause(RuntimeError(message))
    assert sanitized.startswith("RuntimeError: ")
    assert expected in sanitized
    for leak in ("not-a-secret", "sk-live", "sk-proj", "eyJhbGciOi", "abc.def.ghi", "ghp_", "AKIA"):
        assert leak not in sanitized


def test_sanitized_cause_leaves_plain_text_alone() -> None:
    assert recovery._sanitized_cause(RuntimeError("plain failure, no credentials")) == (
        "RuntimeError: plain failure, no credentials"
    )


@pytest.mark.asyncio
async def test_global_run_store_failure_aborts_the_due_tick() -> None:
    """A canonical store outage must not produce misleading later success."""
    now = datetime(2026, 9, 1, 4, 0, tzinfo=UTC)
    store = _Store(
        _record("waiting-1", RunStatus.WAITING, now - timedelta(seconds=1)),
        _record("waiting-2", RunStatus.WAITING, now - timedelta(seconds=1)),
    )
    run_store = _FailingRunStore()

    with pytest.raises(recovery.RecoveryInfrastructureError, match="canonical recovery"):
        await recovery.resume_due_graph_runs(
            store=store,
            run_store=run_store,
            node_resolver=lambda _node_id, _graph: None,
            now=now,
        )

    assert run_store.calls == ["waiting-1"]


@pytest.mark.asyncio
async def test_classified_infrastructure_failure_inside_the_walk_propagates() -> None:
    """A classified store failure inside the executor boundary is re-raised
    untouched: terminalizing the Run through the broken store would persist a
    false disposition, and isolating it would let the tick claim success over
    candidates it can no longer read."""
    now = datetime(2026, 9, 1, 4, 0, tzinfo=UTC)
    runs = [
        _queued_run(f"infra-abort-{index}").model_copy(update={"status": RunStatus.WAITING})
        for index in range(1, 3)
    ]
    store = _DueInMemoryStore()
    for run in runs:
        await store.create(
            DurableRunRecord(
                run=run,
                graph_state=GraphExecutionState(
                    run_id=run.run_id,
                    active_node_ids=("node-1",),
                    blackboard_snapshot={"task_objective": "Recovery graph"},
                ),
                resume_at=now - timedelta(seconds=1),
                version=1,
            )
        )

    resolver_calls: list[str] = []

    def _failing_resolver(node_id: str, _graph: object):
        resolver_calls.append(node_id)
        raise recovery.RecoveryInfrastructureError(
            "durable recovery store operation 'update' failed"
        )

    with pytest.raises(recovery.RecoveryInfrastructureError, match="durable recovery store"):
        await recovery.resume_due_graph_runs(
            store=store,
            run_store=None,
            node_resolver=_failing_resolver,
            now=now,
        )

    # The tick aborted on the first candidate instead of isolating the failure
    # and charging on to later candidates it cannot safely claim.
    assert resolver_calls == ["node-1"]
    failed = await store.get(runs[0].run_id)
    assert failed is not None
    assert failed.run.status is RunStatus.RUNNING
    assert failed.run.error is None


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
async def test_queued_recovery_finds_owned_work_behind_a_foreign_prefix(monkeypatch) -> None:
    """Ownership is part of the bounded status query, not only a post-query guard."""
    foreign = [_queued_run(f"foreign-{index}", source="another_consumer") for index in range(3)]
    owned = _queued_run("owned-after-foreign", source="owned")
    run_store = _RunStore(*foreign, owned)
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
        admission_source="owned",
        node_resolver_factory=lambda _run: lambda _node_id, _graph: None,
        limit=2,
    )

    assert recovered == 1
    assert calls == [owned.run_id]
    assert run_store.admission_source_queries == ["owned", "owned"]
    for run in foreign:
        assert await store.get(run.run_id) is None


@pytest.mark.asyncio
async def test_queued_recovery_crosses_a_foreign_prefix_longer_than_one_ticks_bound(
    monkeypatch,
) -> None:
    """The review finding on the first cut, at the production seam: more
    foreign-owned QUEUED Runs than one tick may inspect, and the one owned
    Run ordered behind all of them. A tick that restarted from the top every
    time never reached it; a tick that resumes where the last one stopped
    reaches it on the second call, and never touches a foreign Run."""
    from maistro.graph.durable_runs.fair_scan import DEFAULT_MAX_INSPECTED, ScanContinuation

    base = datetime(2026, 9, 1, 4, 0, tzinfo=UTC)
    foreign = [
        _queued_run(f"foreign-{i:04d}", source="some_other_consumer").model_copy(
            update={"created_at": base + timedelta(seconds=i)}
        )
        for i in range(DEFAULT_MAX_INSPECTED)
    ]
    owned = _queued_run("owned-behind-the-prefix").model_copy(
        update={"created_at": base + timedelta(seconds=DEFAULT_MAX_INSPECTED)}
    )
    run_store = _RunStore(*foreign, owned)
    store = _BootstrapStore()
    calls: list[str] = []

    async def _resume(run_id: str, **kwargs) -> None:
        del kwargs
        calls.append(run_id)

    monkeypatch.setattr(recovery, "resume_durable_graph", _resume)
    scan: ScanContinuation[tuple[str, str]] = ScanContinuation()

    def _tick():
        return recovery.recover_queued_graph_runs(
            store=store,
            run_store=run_store,
            eligible=lambda candidate: candidate.provenance.get("admission_source") == "owned",
            node_resolver_factory=lambda _run: lambda _node_id, _graph: None,
            limit=1,
            scan=scan,
        )

    assert await _tick() == 0
    assert scan.resume_after is not None, "the first tick stopped at its bound mid-store"

    assert await _tick() == 1

    assert calls == [owned.run_id]
    assert await store.get(owned.run_id) is not None
    for run in foreign[:5]:
        assert await store.get(run.run_id) is None


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


class _ScanningStore(_Store):
    """A store that can tell "nothing due on this page" from "index ended".

    `CanonicalDurableRunStore` is the real one. This is the same contract in
    miniature, so the wiring that prefers it over `list_due` is exercised at
    the seam rather than only one layer down.
    """

    def __init__(self, *records, settled: int = 0) -> None:
        super().__init__(*records)
        self.settled = settled
        self.list_due_calls = 0
        self.scan_calls = 0

    async def list_due(self, **kwargs):
        self.list_due_calls += 1
        return await super().list_due(**kwargs)

    async def scan_due_page(
        self,
        *,
        now: datetime,
        limit: int = 100,
        after: tuple[str, str] | None = None,
        max_inspected: int = 2000,
    ):
        del now, max_inspected
        self.scan_calls += 1
        rows = sorted(self.records.values(), key=_due_cursor)
        if after is not None:
            rows = [row for row in rows if _due_cursor(row) > after]
        if not rows:
            return recovery.ScanPage(items=[], resume_after=after, inspected=0, exhausted=True)
        kept = rows[:limit]
        return recovery.ScanPage(
            items=kept,
            resume_after=_due_cursor(kept[-1]),
            # The settled rows this page read and dropped: invisible in
            # `items`, and the whole reason a page needs to report them.
            inspected=len(kept) + self.settled,
        )


@pytest.mark.asyncio
async def test_a_store_that_can_page_past_settled_rows_is_asked_to(monkeypatch) -> None:
    """The due tick prefers `scan_due_page` where the store offers it.

    Without this the fix is unreached in production: `list_due` cannot say
    whether an empty page means the index ended, so a settled prefix still
    resets the scan to the top on every tick.
    """
    now = datetime(2026, 9, 1, 4, 0, tzinfo=UTC)
    waiting = _record("waiting", RunStatus.WAITING, now - timedelta(seconds=1))
    store = _ScanningStore(waiting, settled=100)
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
    assert store.scan_calls >= 1
    assert store.list_due_calls == 0


@pytest.mark.asyncio
async def test_a_store_without_the_page_scanner_still_uses_the_plain_listing() -> None:
    """The preference is a capability check, not a requirement: a store that
    does not filter its own page needs nothing new."""
    now = datetime(2026, 9, 1, 4, 0, tzinfo=UTC)
    store = _Store(_record("waiting", RunStatus.WAITING, now - timedelta(seconds=1)))

    assert not isinstance(store, recovery.DuePageScanner)

    fetch = recovery._due_page_fetcher(store, now)
    page = await fetch(None, 10)

    assert [record.run_id for record in page] == ["waiting"]


@pytest.mark.asyncio
async def test_a_cancelled_due_resume_aborts_the_tick_rather_than_being_isolated(
    monkeypatch,
) -> None:
    """Per-candidate isolation must not swallow cancellation: the tick is
    being torn down, and continuing to the next candidate would resume work
    nobody is waiting for."""
    import asyncio

    now = datetime(2026, 9, 1, 4, 0, tzinfo=UTC)
    first = _record("first", RunStatus.WAITING, now - timedelta(seconds=2))
    second = _record("second", RunStatus.WAITING, now - timedelta(seconds=1))
    store = _Store(first, second)
    attempted: list[str] = []

    async def _cancel(run_id: str, **kwargs) -> None:
        del kwargs
        attempted.append(run_id)
        raise asyncio.CancelledError

    monkeypatch.setattr(recovery, "resume_durable_graph", _cancel)

    with pytest.raises(asyncio.CancelledError):
        await recovery.resume_due_graph_runs(
            store=store,
            run_store=object(),
            node_resolver=lambda _node_id, _graph: None,
            limit=5,
            now=now,
        )

    assert attempted == ["first"]


@pytest.mark.asyncio
async def test_a_cancelled_queued_resume_aborts_the_tick_too(monkeypatch) -> None:
    import asyncio

    run = _queued_run()
    store = _BootstrapStore(recovery._initial_queued_record(run))

    async def _cancel(run_id: str, **kwargs) -> None:
        del run_id, kwargs
        raise asyncio.CancelledError

    monkeypatch.setattr(recovery, "resume_durable_graph", _cancel)

    with pytest.raises(asyncio.CancelledError):
        await recovery.recover_queued_graph_runs(
            store=store,
            run_store=_RunStore(run),
            eligible=lambda _candidate: True,
            node_resolver_factory=lambda _run: lambda _node_id, _graph: None,
        )


def test_a_due_candidate_without_a_resume_at_cannot_be_paged_by() -> None:
    """The keyset cursor is `(resume_at, run_id)`. A record reaching this with
    no deadline would page from an invented position and silently skip rows,
    so the contract fails loudly instead."""
    record = _record("no-deadline", RunStatus.WAITING, None)

    with pytest.raises(ValueError, match="no resume_at to page by"):
        recovery._due_cursor_key(record)


@pytest.mark.asyncio
async def test_a_failure_after_the_candidate_was_claimed_is_raised_not_swallowed(
    monkeypatch,
) -> None:
    """A partially claimed Run must not be reported as a handled candidate.

    `resume_durable_graph` checkpoints the QUEUED continuation and moves the
    canonical Run to RUNNING before it does anything that can fail this way.
    Treating a later failure as candidate-local strands the Run for good: the
    QUEUED scan no longer returns it and the due index never held it, so
    nothing would ever look at it again. The generic arm used to do exactly
    that, unlike the `(KeyError, ValueError)` arm beside it, which re-reads
    the record first.
    """
    run = _queued_run()
    initial = recovery._initial_queued_record(run)
    store = _BootstrapStore(initial)

    async def _resume(run_id: str, **kwargs) -> None:
        del kwargs
        # Stand in for the real seam: claim the candidate, then fail after it.
        claimed = store.records[run_id]
        store.records[run_id] = claimed.model_copy(
            update={"run": claimed.run.model_copy(update={"status": RunStatus.RUNNING})}
        )
        raise RuntimeError("store hiccup after the claim")

    monkeypatch.setattr(recovery, "resume_durable_graph", _resume)

    with pytest.raises(RuntimeError, match="store hiccup after the claim"):
        await recovery.recover_queued_graph_runs(
            store=store,
            run_store=_RunStore(run),
            eligible=lambda _candidate: True,
            node_resolver_factory=lambda _run: lambda _node_id, _graph: None,
        )


@pytest.mark.asyncio
async def test_a_failure_before_anything_was_claimed_stays_candidate_local(
    monkeypatch,
) -> None:
    """The other half of the rule: an untouched candidate is still isolated.

    The fix above must not turn every unexpected error into an aborted tick —
    a Run left exactly as the scan found it is genuinely candidate-local, and
    the remaining candidates still deserve their turn.
    """
    run = _queued_run()
    initial = recovery._initial_queued_record(run)
    store = _BootstrapStore(initial)

    async def _resume(run_id: str, **kwargs) -> None:
        del run_id, kwargs
        raise RuntimeError("resolver blew up before touching anything")

    monkeypatch.setattr(recovery, "resume_durable_graph", _resume)

    recovered = await recovery.recover_queued_graph_runs(
        store=store,
        run_store=_RunStore(run),
        eligible=lambda _candidate: True,
        node_resolver_factory=lambda _run: lambda _node_id, _graph: None,
    )

    assert recovered == 0
    assert store.records[run.run_id].run.status is RunStatus.QUEUED
