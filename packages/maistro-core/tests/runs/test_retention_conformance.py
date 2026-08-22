"""One retention policy, three Run stores (#131, ADR-082226-c126).

The bound only means something if every backend enforces it the same way. The
in-memory store's `MAX_IN_MEMORY_RUNS` eviction was never the policy — it is a
last-resort cap on a store that is not the system of record. This is the policy,
and it has to hold on the durable one too, or "chat Runs are bounded" is a claim
about the store nobody runs in production.

Four rules, each with its own case on all three backends:

  - expired *and terminal* is deleted;
  - expired but still running is not (a deadline is a floor, not a ceiling);
  - no deadline is never deleted (which is every Run that predates this);
  - a Run something else descends from is not deleted, however expired.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from maistro.graph import Graph, Node
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.store import DEFAULT_PURGE_BATCH, is_purgeable

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
EXPIRED = NOW - timedelta(seconds=1)
FUTURE = NOW + timedelta(days=7)


def _graph(workspace: str, project_id: str, *, node_ids: tuple[str, ...] = ("node-1",)) -> Graph:
    return Graph(
        workspace_id=workspace,
        project_id=project_id,
        name="Retention graph",
        nodes=[Node(node_id=node_id, node_type="agent") for node_id in node_ids],
    )


async def _run(spine: Any, *, expires_at: datetime | None) -> Any:
    store, workspace, project_id = spine
    return await store.create_run(_graph(workspace, project_id), retention_expires_at=expires_at)


async def _terminal_run(spine: Any, *, expires_at: datetime | None) -> Any:
    """A Run walked all the way to COMPLETED — the only state retention sweeps."""
    store, _workspace, _project_id = spine
    run = await _run(spine, expires_at=expires_at)
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    return await store.transition_run(run.run_id, RunStatus.COMPLETED)


# ── the deadline round-trips ──────────────────────────────────────


async def test_a_deadline_survives_the_round_trip(spine: Any) -> None:
    store, _workspace, _project_id = spine
    run = await _run(spine, expires_at=FUTURE)

    reloaded = await store.get_run(run.run_id)

    assert reloaded is not None
    assert reloaded.retention_expires_at == FUTURE


async def test_no_deadline_is_the_default(spine: Any) -> None:
    """`None` is what every Run recorded before retention existed carries, so
    the default has to be the setting that changes nothing."""
    store, workspace, project_id = spine

    run = await store.create_run(_graph(workspace, project_id))

    reloaded = await store.get_run(run.run_id)
    assert reloaded is not None
    assert reloaded.retention_expires_at is None


async def test_the_deadline_survives_transitions(spine: Any) -> None:
    """Retention is set once at admission and never transitioned. If a
    lifecycle step dropped it, a Run would become immortal by being used."""
    store, _workspace, _project_id = spine
    run = await _terminal_run(spine, expires_at=FUTURE)

    reloaded = await store.get_run(run.run_id)

    assert reloaded is not None
    assert reloaded.retention_expires_at == FUTURE


# ── what the sweep deletes ────────────────────────────────────────


async def test_an_expired_terminal_run_is_purged(spine: Any) -> None:
    store, _workspace, _project_id = spine
    run = await _terminal_run(spine, expires_at=EXPIRED)

    purged = await store.purge_expired_runs(now=NOW)

    assert purged == 1
    assert await store.get_run(run.run_id) is None


async def test_an_unexpired_terminal_run_survives(spine: Any) -> None:
    store, _workspace, _project_id = spine
    run = await _terminal_run(spine, expires_at=FUTURE)

    purged = await store.purge_expired_runs(now=NOW)

    assert purged == 0
    assert await store.get_run(run.run_id) is not None


async def test_a_run_with_no_deadline_is_never_purged(spine: Any) -> None:
    store, _workspace, _project_id = spine
    run = await _terminal_run(spine, expires_at=None)

    purged = await store.purge_expired_runs(now=NOW)

    assert purged == 0
    assert await store.get_run(run.run_id) is not None


@pytest.mark.parametrize(
    "status", [RunStatus.CREATED, RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.PAUSED]
)
async def test_a_live_run_past_its_deadline_is_not_purged(spine: Any, status: RunStatus) -> None:
    """The rule that costs storage and is worth it: the deadline is a floor.
    Deleting the execution identity of work still running loses the only handle
    a recovery, a retry or a resumed HITL pause has on it."""
    store, _workspace, _project_id = spine
    run = await _run(spine, expires_at=EXPIRED)
    for step in (RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.PAUSED):
        if run.status is status:
            break
        run = await store.transition_run(run.run_id, step)

    purged = await store.purge_expired_runs(now=NOW)

    assert purged == 0
    assert await store.get_run(run.run_id) is not None


async def test_purging_a_run_takes_its_node_runs_and_attempts(spine: Any) -> None:
    """Leaving them would keep the larger half of the storage while removing
    the index into it — a leak that is also unreachable."""
    store, _workspace, _project_id = spine
    run = await _run(spine, expires_at=EXPIRED)
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    attempt = await store.create_attempt(node_run.node_run_id)
    await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
    await store.transition_attempt(attempt.attempt_id, AttemptStatus.COMPLETED)
    # The NodeRun is left where it is on purpose: accepting an outcome onto it
    # needs evidence this test has no opinion about, and the cascade must work
    # regardless of where the children stopped.
    await store.transition_run(run.run_id, RunStatus.COMPLETED)

    assert await store.purge_expired_runs(now=NOW) == 1

    assert await store.get_run(run.run_id) is None
    assert await store.get_node_run(node_run.node_run_id) is None
    assert await store.get_attempt(attempt.attempt_id) is None


async def test_a_parent_run_is_not_purged_while_a_child_exists(spine: Any) -> None:
    """The spine's foreign keys are ON DELETE RESTRICT by design; retention
    must not be the thing that discovers that. The child here has no deadline,
    so it is not a candidate itself — only the parent is, and it must be
    skipped rather than attempted and failed."""
    store, workspace, project_id = spine
    parent = await _terminal_run(spine, expires_at=EXPIRED)
    await store.create_run(_graph(workspace, project_id), parent_run_id=parent.run_id)

    purged = await store.purge_expired_runs(now=NOW)

    assert purged == 0
    assert await store.get_run(parent.run_id) is not None


async def test_a_run_whose_node_run_a_child_descends_from_is_not_purged(spine: Any) -> None:
    store, workspace, project_id = spine
    parent = await _run(spine, expires_at=EXPIRED)
    await store.transition_run(parent.run_id, RunStatus.QUEUED)
    await store.transition_run(parent.run_id, RunStatus.RUNNING)
    node_run = await store.create_node_run(parent.run_id, node_id="node-1")
    await store.create_run(
        _graph(workspace, project_id),
        parent_run_id=parent.run_id,
        parent_node_run_id=node_run.node_run_id,
    )
    await store.transition_run(parent.run_id, RunStatus.COMPLETED)

    purged = await store.purge_expired_runs(now=NOW)

    assert purged == 0
    assert await store.get_run(parent.run_id) is not None


# ── the batch is a bound, not a suggestion ────────────────────────


async def test_the_batch_limit_is_honoured(spine: Any) -> None:
    store, _workspace, _project_id = spine
    for _ in range(5):
        await _terminal_run(spine, expires_at=EXPIRED)

    first = await store.purge_expired_runs(now=NOW, limit=2)

    assert first == 2


async def test_repeated_sweeps_drain_a_backlog(spine: Any) -> None:
    """A backlog larger than one batch is not stuck — it drains over several
    sweeps. Which is why the limit can be a hard bound rather than a hint."""
    store, _workspace, _project_id = spine
    for _ in range(5):
        await _terminal_run(spine, expires_at=EXPIRED)

    total = 0
    for _ in range(10):
        swept = await store.purge_expired_runs(now=NOW, limit=2)
        total += swept
        if swept == 0:
            break

    assert total == 5


async def test_a_non_positive_limit_is_refused(spine: Any) -> None:
    """Zero would be a silent no-op sweep, which is the failure mode this whole
    policy exists to remove."""
    store, _workspace, _project_id = spine

    with pytest.raises(ValueError):
        await store.purge_expired_runs(now=NOW, limit=0)


async def test_a_sweep_with_nothing_to_do_reports_nothing(spine: Any) -> None:
    store, _workspace, _project_id = spine

    assert await store.purge_expired_runs(now=NOW) == 0


async def test_the_sweep_defaults_to_now(spine: Any) -> None:
    """`now` exists for the tests; production passes nothing and must still
    sweep against the real clock."""
    store, _workspace, _project_id = spine
    run = await _terminal_run(spine, expires_at=datetime.now(UTC) - timedelta(hours=1))

    assert await store.purge_expired_runs() == 1
    assert await store.get_run(run.run_id) is None


# ── concurrency: two sweepers divide the work, they do not double-count ──


async def test_concurrent_sweeps_do_not_double_count(spine: Any) -> None:
    store, _workspace, _project_id = spine
    for _ in range(6):
        await _terminal_run(spine, expires_at=EXPIRED)

    results = await asyncio.gather(
        store.purge_expired_runs(now=NOW, limit=6),
        store.purge_expired_runs(now=NOW, limit=6),
        return_exceptions=True,
    )
    swept = [r for r in results if isinstance(r, int)]

    # Whatever the split, the total cannot exceed what existed — a store that
    # reported 6 + 6 would be counting rows it did not delete.
    assert sum(swept) <= 6
    assert await store.purge_expired_runs(now=NOW) == 6 - sum(swept)


# ── the predicate itself ──────────────────────────────────────────


def test_is_purgeable_needs_all_three_conditions() -> None:
    """Exercised directly because two of the three backends consult it and the
    third re-expresses it in SQL; the cases above prove they agree, this one
    says what they agree *on*."""
    from maistro.runs.model import GraphSnapshot, Run

    def _make(status: RunStatus, expires_at: datetime | None) -> Run:
        graph = _graph("w", "p")
        return Run(
            workspace_id="w",
            project_id="p",
            graph=GraphSnapshot.from_graph(graph),
            status=status,
            finished_at=NOW if status is RunStatus.COMPLETED else None,
            retention_expires_at=expires_at,
        )

    assert is_purgeable(_make(RunStatus.COMPLETED, EXPIRED), NOW)
    assert not is_purgeable(_make(RunStatus.COMPLETED, FUTURE), NOW)
    assert not is_purgeable(_make(RunStatus.COMPLETED, None), NOW)
    assert not is_purgeable(_make(RunStatus.RUNNING, EXPIRED), NOW)
    # Exactly at the deadline counts as expired: a Run promised "until T" has
    # had until T.
    assert is_purgeable(_make(RunStatus.COMPLETED, NOW), NOW)


def test_the_default_batch_is_a_real_bound() -> None:
    assert DEFAULT_PURGE_BATCH > 0
