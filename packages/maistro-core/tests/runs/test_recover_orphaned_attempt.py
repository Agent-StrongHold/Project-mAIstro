"""P3b: recover_orphaned_attempt is the leaseless orphan RECOVERED writer (#2417)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from maistro.graph.definitions import Graph, Node
from maistro.runs.lifecycle import (
    ORPHANED_ATTEMPT_ERROR,
    InvalidLifecycleTransition,
    recover_orphaned_attempt,
)
from maistro.runs.model import Attempt, AttemptStatus, CancellationCause, ExecutionLease, RunStatus
from maistro.runs.store import AttemptNotFound, InMemoryRunStore, RunIntegrityError
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID


def _t(offset_s: int = 0) -> datetime:
    return datetime(2026, 11, 19, 18, 0, 0, tzinfo=UTC) + timedelta(seconds=offset_s)


def _leaseless(
    *,
    status: AttemptStatus = AttemptStatus.CREATED,
    cause: CancellationCause | None = None,
    with_lease: bool = False,
) -> Attempt:
    attempt = Attempt(node_run_id="nr-1", ordinal=1, created_at=_t(0))
    values = attempt.model_dump(mode="python")
    values["status"] = status
    if status is AttemptStatus.RUNNING:
        values["started_at"] = _t(1)
    if status in {AttemptStatus.CANCELLED, AttemptStatus.COMPLETED, AttemptStatus.FAILED}:
        values["finished_at"] = _t(2)
        values["started_at"] = _t(1)
    if cause is not None:
        values["cancellation_cause"] = cause
        values["status"] = AttemptStatus.CANCELLED
        values["finished_at"] = _t(2)
    if with_lease:
        values["execution_lease"] = ExecutionLease(
            node_run_id=attempt.node_run_id,
            attempt_id=attempt.attempt_id,
            lease_epoch=1,
            holder="worker-1",
            issued_at=_t(0),
            expires_at=_t(30),
        )
    return Attempt.model_validate(values)


class TestRecoverOrphanedConstruction:
    def test_leaseless_created_commits_cancelled_recovered(self) -> None:
        settled = recover_orphaned_attempt(_leaseless(), at=_t(3))

        assert settled.status is AttemptStatus.CANCELLED
        assert settled.cancellation_cause is CancellationCause.RECOVERED
        assert settled.finished_at == _t(3)
        assert settled.error == ORPHANED_ATTEMPT_ERROR
        assert settled.execution_lease is None

    def test_leaseless_running_commits_cancelled_recovered(self) -> None:
        settled = recover_orphaned_attempt(
            _leaseless(status=AttemptStatus.RUNNING), at=_t(4), error="custom orphan"
        )

        assert settled.status is AttemptStatus.CANCELLED
        assert settled.cancellation_cause is CancellationCause.RECOVERED
        assert settled.finished_at == _t(4)
        assert settled.error == "custom orphan"
        assert settled.started_at == _t(1)

    def test_leased_is_refused(self) -> None:
        with pytest.raises(InvalidLifecycleTransition, match="execution lease"):
            recover_orphaned_attempt(_leaseless(with_lease=True), at=_t(3))

    def test_terminal_is_refused(self) -> None:
        with pytest.raises(InvalidLifecycleTransition, match="terminal"):
            recover_orphaned_attempt(_leaseless(status=AttemptStatus.COMPLETED), at=_t(3))

    def test_already_caused_terminal_is_refused(self) -> None:
        """A CANCELLED row already carries an outcome; cause rewrite is impossible."""
        with pytest.raises(InvalidLifecycleTransition, match="terminal"):
            recover_orphaned_attempt(_leaseless(cause=CancellationCause.REQUESTED), at=_t(3))

    def test_non_active_non_terminal_status_is_refused(self) -> None:
        """Defense for corrupted payloads: only CREATED/RUNNING may orphan-recover."""
        corrupted = Attempt.model_construct(
            attempt_id="att-bogus",
            node_run_id="nr-1",
            ordinal=1,
            status="queued",  # not CREATED/RUNNING and not a terminal AttemptStatus
            created_at=_t(0),
            started_at=None,
            finished_at=None,
            execution_lease=None,
            cancellation_cause=None,
            result=None,
            error=None,
            metrics={},
        )
        with pytest.raises(InvalidLifecycleTransition, match="only CREATED/RUNNING"):
            recover_orphaned_attempt(corrupted, at=_t(3))  # type: ignore[arg-type]

    def test_active_row_with_preexisting_cause_is_refused(self) -> None:
        """CREATED/RUNNING must not already carry a cause (validators normally forbid)."""
        corrupted = Attempt.model_construct(
            attempt_id="att-caused",
            node_run_id="nr-1",
            ordinal=1,
            status=AttemptStatus.CREATED,
            created_at=_t(0),
            started_at=None,
            finished_at=None,
            execution_lease=None,
            cancellation_cause=CancellationCause.REQUESTED,
            result=None,
            error=None,
            metrics={},
        )
        with pytest.raises(InvalidLifecycleTransition, match="already carries"):
            recover_orphaned_attempt(corrupted, at=_t(3))


async def _spine_store() -> tuple[InMemoryRunStore, str, str]:
    from maistro.projects.scope_store import InMemoryProjectScopeStore

    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-p3b")
    project = await projects.create(
        workspace_id="ws-p3b", parent_project_id=root.project_id, name="P3b"
    )
    store = InMemoryRunStore(project_store=projects)
    graph = Graph(
        workspace_id="ws-p3b",
        project_id=project.project_id,
        name="p3b",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await store.create_run(graph, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID)
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    await store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    await store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
    return store, run.run_id, node_run.node_run_id


class TestRecoverOrphanedStore:
    async def test_store_persists_recovered_under_owning_run(self) -> None:
        store, run_id, node_run_id = await _spine_store()
        attempt = await store.create_attempt(node_run_id)
        assert attempt.execution_lease is None

        settled = await store.recover_orphaned_attempt(
            attempt.attempt_id, owning_run_id=run_id, error="orphan boom"
        )

        assert settled.cancellation_cause is CancellationCause.RECOVERED
        assert settled.error == "orphan boom"
        reopened = await store.get_attempt(attempt.attempt_id)
        assert reopened is not None
        assert reopened.cancellation_cause is CancellationCause.RECOVERED
        assert reopened.status is AttemptStatus.CANCELLED

    async def test_wrong_owning_run_is_refused(self) -> None:
        store, _run_id, node_run_id = await _spine_store()
        attempt = await store.create_attempt(node_run_id)

        with pytest.raises(RunIntegrityError, match="owning_run_id"):
            await store.recover_orphaned_attempt(attempt.attempt_id, owning_run_id="not-the-owner")

        reopened = await store.get_attempt(attempt.attempt_id)
        assert reopened is not None
        assert reopened.status is AttemptStatus.CREATED
        assert reopened.cancellation_cause is None

    async def test_leased_winner_is_refused(self) -> None:
        store, run_id, node_run_id = await _spine_store()
        attempt = await store.create_attempt(
            node_run_id, lease_holder="worker-1", lease_ttl=timedelta(seconds=30)
        )

        with pytest.raises(InvalidLifecycleTransition, match="execution lease"):
            await store.recover_orphaned_attempt(attempt.attempt_id, owning_run_id=run_id)

    async def test_missing_raises(self) -> None:
        store, run_id, _node_run_id = await _spine_store()
        with pytest.raises(AttemptNotFound):
            await store.recover_orphaned_attempt("missing", owning_run_id=run_id)


async def _leaseless_active_attempt(
    spine: Any, *, running: bool = False
) -> tuple[Any, Attempt, str]:
    """A leaseless CREATED (or RUNNING) Attempt on whichever backend `spine` is."""
    store, workspace, project_id = spine
    graph = Graph(
        workspace_id=workspace,
        project_id=project_id,
        name="spine orphan",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await store.create_run(graph, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID)
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    await store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    await store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
    attempt = await store.create_attempt(node_run.node_run_id)
    assert attempt.execution_lease is None
    if running:
        attempt = await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
    return store, attempt, run.run_id


async def _leased_created_attempt(spine: Any) -> tuple[Any, Attempt, str]:
    store, workspace, project_id = spine
    graph = Graph(
        workspace_id=workspace,
        project_id=project_id,
        name="spine leased orphan refuse",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await store.create_run(graph, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID)
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    await store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    await store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
    attempt = await store.create_attempt(
        node_run.node_run_id, lease_holder="worker-1", lease_ttl=timedelta(seconds=30)
    )
    assert attempt.execution_lease is not None
    return store, attempt, run.run_id


class TestRecoverOrphanedSpine:
    """The same orphan leaf on every shipped backend (#2417 / #232 P3b)."""

    async def test_persists_recovered_under_owning_run(self, spine: Any) -> None:
        store, attempt, run_id = await _leaseless_active_attempt(spine, running=True)

        settled = await store.recover_orphaned_attempt(attempt.attempt_id, owning_run_id=run_id)

        assert settled.status is AttemptStatus.CANCELLED
        assert settled.cancellation_cause is CancellationCause.RECOVERED
        assert settled.error == ORPHANED_ATTEMPT_ERROR
        reopened = await store.get_attempt(attempt.attempt_id)
        assert reopened is not None
        assert reopened.cancellation_cause is CancellationCause.RECOVERED

    async def test_wrong_owning_run_writes_nothing(self, spine: Any) -> None:
        store, attempt, _run_id = await _leaseless_active_attempt(spine)

        with pytest.raises(RunIntegrityError, match="owning_run_id"):
            await store.recover_orphaned_attempt(attempt.attempt_id, owning_run_id="someone-else")

        reopened = await store.get_attempt(attempt.attempt_id)
        assert reopened is not None
        assert reopened.status is AttemptStatus.CREATED
        assert reopened.cancellation_cause is None
        assert reopened.finished_at is None

    async def test_leased_is_refused(self, spine: Any) -> None:
        store, attempt, run_id = await _leased_created_attempt(spine)

        with pytest.raises(InvalidLifecycleTransition, match="execution lease"):
            await store.recover_orphaned_attempt(attempt.attempt_id, owning_run_id=run_id)

        reopened = await store.get_attempt(attempt.attempt_id)
        assert reopened is not None
        assert reopened.status is AttemptStatus.CREATED
        assert reopened.cancellation_cause is None

    async def test_missing_attempt_raises_attempt_not_found(self, spine: Any) -> None:
        store, _workspace, _project_id = spine
        with pytest.raises(AttemptNotFound):
            await store.recover_orphaned_attempt("missing", owning_run_id="any-run")


class _OrphanPool:
    """Stand-in pool for ``PgRunStore.recover_orphaned_attempt`` lock refusals."""

    def __init__(self) -> None:
        self.runs: dict[str, dict[str, object]] = {}
        self.node_runs: dict[str, dict[str, object]] = {}
        self.attempts: dict[str, dict[str, object]] = {}
        self.attempt_nodes: dict[str, str] = {}
        self.node_run_runs: dict[str, str] = {}
        self.statements: list[str] = []
        self.updates: list[tuple[str, str]] = []

    def acquire(self) -> _OrphanPool:
        return self

    async def __aenter__(self) -> _OrphanPool:
        return self

    async def __aexit__(self, *_exc_info: object) -> bool:
        return False

    def transaction(self) -> _OrphanPool:
        return self

    async def fetchrow(self, query: str, *args: object) -> dict[str, object] | None:
        sql = " ".join(query.split())
        self.statements.append(sql)
        if "JOIN canonical_node_runs" in sql:
            attempt_id = str(args[0])
            node_run_id = self.attempt_nodes.get(attempt_id)
            if node_run_id is None or node_run_id not in self.node_run_runs:
                return None
            return {"node_run_id": node_run_id, "run_id": self.node_run_runs[node_run_id]}
        if "FOR UPDATE" not in sql:
            raise AssertionError(f"unexpected fetchrow query: {query!r}")
        if "canonical_runs" in sql:
            return {"run_id": str(args[0])} if str(args[0]) in self.runs else None
        if "canonical_node_runs" in sql:
            payload = self.node_runs.get(str(args[0]))
            return {"node_run_id": str(args[0]), "payload": payload, "archive_key": None}
        if "canonical_attempts" in sql:
            payload = self.attempts.get(str(args[0]))
            return {"attempt_id": str(args[0]), "payload": payload, "archive_key": None}
        raise AssertionError(f"unexpected FOR UPDATE query: {query!r}")

    async def execute(self, query: str, *args: object) -> str:
        import json

        sql = " ".join(query.split())
        self.statements.append(sql)
        if "UPDATE canonical_attempts" in sql:
            identity = str(args[2])
            self.attempts[identity] = json.loads(str(args[1]))
            self.updates.append(("canonical_attempts", identity))
            return "UPDATE 1"
        raise AssertionError(f"unexpected execute query: {query!r}")


async def _orphan_pool() -> tuple[_OrphanPool, str, str]:
    """One leaseless CREATED Attempt on a stand-in PG pool; attempt id + run id."""
    from maistro.projects.scope_store import InMemoryProjectScopeStore
    from maistro.runs.evidence_json import payload_of

    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-orphan-pg")
    store = InMemoryRunStore(project_store=projects)
    graph = Graph(
        workspace_id="ws-orphan-pg",
        project_id=root.project_id,
        name="orphan-pg",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await store.create_run(graph, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID)
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    await store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    node_run = await store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
    attempt = await store.create_attempt(node_run.node_run_id)
    assert attempt.execution_lease is None

    pool = _OrphanPool()
    pool.runs[run.run_id] = payload_of(run)
    pool.node_runs[node_run.node_run_id] = payload_of(node_run)
    pool.attempts[attempt.attempt_id] = payload_of(attempt)
    pool.attempt_nodes[attempt.attempt_id] = attempt.node_run_id
    pool.node_run_runs[node_run.node_run_id] = node_run.run_id
    return pool, attempt.attempt_id, run.run_id


def _pg_store(pool: _OrphanPool) -> Any:
    from maistro.projects.scope_store import InMemoryProjectScopeStore as Projects
    from maistro.runs.pg_store import PgRunStore

    return PgRunStore(pool, project_store=Projects())  # type: ignore[arg-type]


class TestRecoverOrphanedPgLockRefusals:
    """No-services stand-ins for the PG orphan writer's integrity arms (#2417)."""

    async def test_missing_owning_run_after_lineage_is_refused(self) -> None:
        pool, attempt_id, run_id = await _orphan_pool()
        pool.runs.clear()
        store = _pg_store(pool)

        with pytest.raises(RunIntegrityError, match="does not exist"):
            await store.recover_orphaned_attempt(attempt_id, owning_run_id=run_id)

        assert pool.updates == []

    async def test_lineage_changed_under_lock_is_refused(self) -> None:
        pool, attempt_id, run_id = await _orphan_pool()
        pool.attempts[attempt_id]["node_run_id"] = "node-run-elsewhere"
        store = _pg_store(pool)

        with pytest.raises(
            RunIntegrityError, match="lineage changed under the orphan recovery lock"
        ):
            await store.recover_orphaned_attempt(attempt_id, owning_run_id=run_id)

        assert pool.updates == []
