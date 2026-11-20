"""P2b: exact-ID store reclaim persists CANCELLED+RECOVERED under lock (#2358 / #232).

Protocol + in-memory / SQLite / PostgreSQL. Graph ``execution_store`` is P3a.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import aiosqlite
import pytest

from maistro.graph.definitions import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.lifecycle import renew_attempt_lease
from maistro.runs.model import Attempt, AttemptStatus, CancellationCause, RunStatus
from maistro.runs.sqlite_store import SqliteRunStore
from maistro.runs.store import DEFAULT_RECLAIM_BATCH, AttemptNotFound, InMemoryRunStore
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID


def _graph(workspace: str, project_id: str) -> Graph:
    return Graph(
        workspace_id=workspace,
        project_id=project_id,
        name="exact reclaim",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )


async def _leased_running_attempt(
    spine: Any, *, holder: str = "worker-A", ttl: timedelta
) -> tuple[Any, Any]:
    store, workspace, project_id = spine
    run = await store.create_run(
        _graph(workspace, project_id), actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID
    )
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    await store.transition_node_run(node_run.node_run_id, RunStatus.QUEUED)
    await store.transition_node_run(node_run.node_run_id, RunStatus.RUNNING)
    attempt = await store.create_attempt(node_run.node_run_id, lease_holder=holder, lease_ttl=ttl)
    assert attempt.execution_lease is not None
    running = await store.transition_attempt(
        attempt.attempt_id,
        AttemptStatus.RUNNING,
        fencing_token=attempt.execution_lease.fencing_token,
    )
    return store, running


async def _assert_exact_id_reclaim_persists_recovered(spine: Any) -> None:
    store, attempt = await _leased_running_attempt(spine, ttl=timedelta(seconds=30))
    lease = attempt.execution_lease
    assert lease is not None and lease.expires_at is not None
    after = lease.expires_at + timedelta(seconds=1)

    written = await store.reclaim_expired_attempt(attempt.attempt_id, now=after)

    assert written is not None
    assert written.attempt_id == attempt.attempt_id
    assert written.status is AttemptStatus.CANCELLED
    assert written.cancellation_cause is CancellationCause.RECOVERED
    assert written.finished_at == after
    assert written.error is not None and "worker-A" in written.error

    reopened = await store.get_attempt(attempt.attempt_id)
    assert reopened is not None
    assert reopened.status is AttemptStatus.CANCELLED
    assert reopened.cancellation_cause is CancellationCause.RECOVERED
    assert reopened.model_dump(mode="json")["cancellation_cause"] == "recovered"


async def _assert_live_lease_returns_none(spine: Any) -> None:
    store, attempt = await _leased_running_attempt(spine, ttl=timedelta(minutes=5))
    lease = attempt.execution_lease
    assert lease is not None and lease.expires_at is not None

    assert (
        await store.reclaim_expired_attempt(
            attempt.attempt_id, now=lease.expires_at - timedelta(seconds=1)
        )
        is None
    )
    still = await store.get_attempt(attempt.attempt_id)
    assert still is not None and still.status is AttemptStatus.RUNNING
    assert still.cancellation_cause is None


async def _assert_already_reclaimed_is_idempotent(spine: Any) -> None:
    store, attempt = await _leased_running_attempt(spine, ttl=timedelta(seconds=30))
    lease = attempt.execution_lease
    assert lease is not None and lease.expires_at is not None
    after = lease.expires_at + timedelta(seconds=1)

    first = await store.reclaim_expired_attempt(attempt.attempt_id, now=after)
    second = await store.reclaim_expired_attempt(attempt.attempt_id, now=after + timedelta(hours=1))

    assert first is not None
    assert first.cancellation_cause is CancellationCause.RECOVERED
    assert second is None
    again = await store.get_attempt(attempt.attempt_id)
    assert again is not None
    assert again.cancellation_cause is CancellationCause.RECOVERED


async def _assert_requested_terminal_is_not_rewritten(spine: Any) -> None:
    store, attempt = await _leased_running_attempt(spine, ttl=timedelta(seconds=30))
    lease = attempt.execution_lease
    assert lease is not None and lease.expires_at is not None
    cancelled = await store.transition_attempt(
        attempt.attempt_id,
        AttemptStatus.CANCELLED,
        fencing_token=lease.fencing_token,
        error="user cancelled",
    )
    assert cancelled.cancellation_cause is None

    assert (
        await store.reclaim_expired_attempt(
            attempt.attempt_id, now=lease.expires_at + timedelta(days=1)
        )
        is None
    )
    still = await store.get_attempt(attempt.attempt_id)
    assert still is not None
    assert still.status is AttemptStatus.CANCELLED
    assert still.cancellation_cause is None
    assert still.error == "user cancelled"


async def _assert_batch_persists_recovered_and_returns_only_new(spine: Any) -> None:
    store, attempt = await _leased_running_attempt(spine, ttl=timedelta(seconds=30))
    lease = attempt.execution_lease
    assert lease is not None and lease.expires_at is not None
    after = lease.expires_at + timedelta(seconds=1)

    first = await store.reclaim_expired_attempts(now=after)
    second = await store.reclaim_expired_attempts(now=after + timedelta(hours=1))

    assert [item.attempt_id for item in first] == [attempt.attempt_id]
    assert first[0].cancellation_cause is CancellationCause.RECOVERED
    assert second == []
    reopened = await store.get_attempt(attempt.attempt_id)
    assert reopened is not None
    assert reopened.cancellation_cause is CancellationCause.RECOVERED


async def _assert_missing_raises(spine: Any) -> None:
    store, _workspace, _project_id = spine
    with pytest.raises(AttemptNotFound):
        await store.reclaim_expired_attempt("no-such-attempt")


async def test_exact_id_reclaim_persists_recovered(spine: Any) -> None:
    await _assert_exact_id_reclaim_persists_recovered(spine)


async def test_exact_id_live_lease_returns_none(spine: Any) -> None:
    await _assert_live_lease_returns_none(spine)


async def test_exact_id_already_reclaimed_returns_none(spine: Any) -> None:
    await _assert_already_reclaimed_is_idempotent(spine)


async def test_exact_id_requested_terminal_is_not_rewritten(spine: Any) -> None:
    await _assert_requested_terminal_is_not_rewritten(spine)


async def test_batch_reclaim_persists_recovered_cause(spine: Any) -> None:
    await _assert_batch_persists_recovered_and_returns_only_new(spine)


async def test_exact_id_missing_raises_attempt_not_found(spine: Any) -> None:
    await _assert_missing_raises(spine)


async def test_batch_reclaim_skips_an_attempt_renewed_between_snapshot_and_write_in_memory(
    memory_spine: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The batch re-check under the write authority skips a raced renewal.

    The snapshot admits the Attempt (expired at ``now``); by write time the
    predicate sees a fresh lease — a concurrent ``renew_lease`` won between
    nominating and writing — so the row must be skipped, not rewritten:
    nothing returned, nothing persisted (#2358 / #232 P2c). The predicate is
    stubbed per call rather than raced on wall-clock timing, which would make
    the test order-dependent on scheduler speed.
    """
    store, attempt = await _leased_running_attempt(memory_spine, ttl=timedelta(seconds=30))
    lease = attempt.execution_lease
    assert lease is not None and lease.expires_at is not None
    after = lease.expires_at + timedelta(seconds=1)

    import maistro.runs.store as runs_store_module

    real = runs_store_module.lease_is_expired
    calls = {"n": 0}

    def _renewed_after_the_snapshot(candidate: Any, now: Any) -> bool:
        calls["n"] += 1
        # Admitted by the doomed snapshot (first read), fresh again by the
        # re-check that guards the write (every later read).
        return real(candidate, now) if calls["n"] == 1 else False

    monkeypatch.setattr(runs_store_module, "lease_is_expired", _renewed_after_the_snapshot)

    reclaimed = await store.reclaim_expired_attempts(now=after)

    assert calls["n"] >= 2  # snapshot admission and the write-time re-check both ran
    assert reclaimed == []
    current = await store.get_attempt(attempt.attempt_id)
    assert current is not None
    assert current.status is AttemptStatus.RUNNING
    assert current.cancellation_cause is None


async def test_exact_id_reclaim_persists_recovered_in_memory(memory_spine: Any) -> None:
    await _assert_exact_id_reclaim_persists_recovered(memory_spine)


async def test_exact_id_live_lease_returns_none_in_memory(memory_spine: Any) -> None:
    await _assert_live_lease_returns_none(memory_spine)


async def test_exact_id_already_reclaimed_returns_none_in_memory(memory_spine: Any) -> None:
    await _assert_already_reclaimed_is_idempotent(memory_spine)


async def test_exact_id_requested_terminal_is_not_rewritten_in_memory(memory_spine: Any) -> None:
    await _assert_requested_terminal_is_not_rewritten(memory_spine)


async def test_batch_reclaim_persists_recovered_cause_in_memory(memory_spine: Any) -> None:
    await _assert_batch_persists_recovered_and_returns_only_new(memory_spine)


async def test_exact_id_missing_raises_attempt_not_found_in_memory(memory_spine: Any) -> None:
    await _assert_missing_raises(memory_spine)


# --- the batch re-check: writers that land between snapshot and re-read -----#


class _SnapshotRaceAttemptMap(dict):
    """`values()` shows the stale snapshot; the first `get()` sees the race."""

    def __init__(self, items: Any, racing: dict[str, Any]) -> None:
        super().__init__(items)
        self._racing = dict(racing)

    def get(self, key: str, default: Any = None) -> Any:
        if key in self._racing:
            return self._racing.pop(key)
        return super().get(key, default)


class _LosesSnapshotRaceStore(InMemoryRunStore):
    """A writer lands between the sort snapshot and each re-read.

    The in-memory batch loop holds no awaits, so this interleaving cannot be
    scheduled for real on one event loop; the attempt map is exactly the seam
    the guard names ("re-check under the same dict authority the write uses").
    Priming an Attempt makes the re-check see it once; priming ``None`` makes
    the re-check see a vanished row.
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._racing_on_recheck: dict[str, Any] = {}

    def prime_snapshot_race(self, attempt_id: str, apparent: Any) -> None:
        self._racing_on_recheck[attempt_id] = apparent

    async def reclaim_expired_attempts(
        self, *, now: Any = None, limit: int = DEFAULT_RECLAIM_BATCH
    ) -> Any:
        original = self._attempts
        self._attempts = _SnapshotRaceAttemptMap(original, self._racing_on_recheck)
        try:
            return await super().reclaim_expired_attempts(now=now, limit=limit)
        finally:
            self._attempts = original


class _RenewedUnderneathStore(SqliteRunStore):
    """The re-read inside the SQLite batch sees what a concurrent renew made true.

    The loop `await`s on the re-read, so unlike the in-memory store this race
    is schedulable for real; priming one Attempt makes exactly one re-read
    return the renewed Attempt, the way a holder's renew landing during the
    batch's own await would.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._renewed_once: Attempt | None = None

    def prime_concurrent_renewal(self, renewed: Attempt) -> None:
        self._renewed_once = renewed

    async def get_attempt(self, attempt_id: str, **kwargs: Any) -> Any:
        if self._renewed_once is not None and attempt_id == self._renewed_once.attempt_id:
            renewed, self._renewed_once = self._renewed_once, None
            return renewed
        return await super().get_attempt(attempt_id, **kwargs)


async def _snapshot_race_memory_spine() -> Any:
    """The `memory_spine` shape, on the race-simulating store subclass."""
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("workspace-1")
    project = await projects.create(
        workspace_id="workspace-1", parent_project_id=root.project_id, name="Durable"
    )
    return _LosesSnapshotRaceStore(project_store=projects), "workspace-1", project.project_id


async def test_batch_reclaim_skips_an_attempt_removed_after_the_snapshot_in_memory() -> None:
    """A row that vanishes between snapshot and re-read is skipped, not fatal.

    `current is None` under the re-check means another authority removed the
    Attempt; rewriting a row that is gone would resurrect state nothing owns.
    """
    store, workspace, project_id = await _snapshot_race_memory_spine()
    spine = (store, workspace, project_id)
    store_inner, attempt = await _leased_running_attempt(spine, ttl=timedelta(seconds=30))
    lease = attempt.execution_lease
    assert lease is not None and lease.expires_at is not None
    after = lease.expires_at + timedelta(seconds=1)
    store_inner.prime_snapshot_race(attempt.attempt_id, None)

    reclaimed = await store_inner.reclaim_expired_attempts(now=after)

    assert reclaimed == []
    reopened = await store_inner.get_attempt(attempt.attempt_id)
    assert reopened is not None
    assert reopened.status is AttemptStatus.RUNNING


async def test_batch_reclaim_skips_an_attempt_renewed_underneath_it_in_sqlite() -> None:
    """The SQLite re-read is awaited, so a real interleaving lands there.

    The re-check observes the renewed lease and leaves the persisted row as
    the renew wrote it — the batch neither crashes nor rewrites a live holder.
    """
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("workspace-1")
    project = await projects.create(
        workspace_id="workspace-1", parent_project_id=root.project_id, name="Durable"
    )
    conn = await aiosqlite.connect(":memory:")
    store = _RenewedUnderneathStore(conn, project_store=projects)
    await store.ensure_schema()
    try:
        spine = (store, "workspace-1", project.project_id)
        store_inner, attempt = await _leased_running_attempt(spine, ttl=timedelta(seconds=30))
        lease = attempt.execution_lease
        assert lease is not None and lease.expires_at is not None
        after = lease.expires_at + timedelta(seconds=1)
        renewed = renew_attempt_lease(
            attempt,
            fencing_token=lease.fencing_token,
            ttl=timedelta(hours=1),
            at=after - timedelta(seconds=2),
        )
        assert renewed.execution_lease is not None
        store_inner.prime_concurrent_renewal(renewed)

        reclaimed = await store_inner.reclaim_expired_attempts(now=after)

        assert reclaimed == []
        reopened = await store_inner.get_attempt(attempt.attempt_id)
        assert reopened is not None
        assert reopened.status is AttemptStatus.RUNNING
        assert reopened.cancellation_cause is None
        assert reopened.execution_lease is not None
        assert reopened.execution_lease.expires_at == lease.expires_at, (
            "nothing was rewritten: the persisted row keeps the renew's answer"
        )
    finally:
        await conn.close()
