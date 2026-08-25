"""One archive tier, two Run stores (#273, ADR-082226-f436).

`test_archive_sweep.py` proves the predicate against the in-memory reference
store, which keeps the Run resident after archiving because it is already
bounded by eviction — it is the reference implementation of the *protocol*, not
a tier that saves bytes. That leaves the load-bearing half untested: on
PostgreSQL the payload column really is set to NULL, and everything downstream
of a read has to keep working anyway.

So these run on both backends and assert the contract rather than the
mechanism:

  - a cold Run kept indefinitely moves, and one with a deletion date never does
    (decisions 2 and 10 — the two populations are disjoint);
  - a read afterwards still returns the record, equal to what went in
    (decision 6 — a silent None is indistinguishable from deletion);
  - the Run's identity, scope and children survive, which is the whole reason
    decision 2 calls archiving safe where deleting would not be;
  - non-finite evidence survives the move, because the archive must not become
    the one place a NaN quietly became null;
  - the tier is off without an archive store (decision 9).

The PostgreSQL leg is the one that can actually fail. It skips without
`MAISTRO_TEST_PG_DSN`, and `scripts/ac_outcome_plugin.py` counts a skip as no
evidence — so a criterion proven here has to be marked on a memory-pinned
fixture, not on `archive_spine`.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from maistro.graph import Graph, Node
from maistro.runs.model import AttemptStatus, RunStatus

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
COLD = NOW - timedelta(days=200)
RECENT = NOW - timedelta(days=2)
NINETY_DAYS = timedelta(days=90)


def _graph(workspace: str, project_id: str) -> Graph:
    return Graph(
        workspace_id=workspace,
        project_id=project_id,
        name="Archive graph",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )


async def _finished_run(
    archive_spine: Any,
    *,
    at: datetime,
    expires_at: datetime | None = None,
    status: RunStatus = RunStatus.COMPLETED,
) -> Any:
    """A Run walked to a terminal state at a chosen instant.

    Walked rather than constructed: `at` reaches the promoted `finished_at`
    column only through the store's own write path, so a Run this helper
    produces is one the sweep would really find.
    """
    store, _archive, workspace, project_id = archive_spine
    run = await store.create_run(_graph(workspace, project_id), retention_expires_at=expires_at)
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    return await store.transition_run(run.run_id, status, at=at)


async def _keys(archive: Any, scope: str) -> list[Any]:
    return [key async for key in archive.list_scope(scope)]


# ── which Runs move ───────────────────────────────────────────────


async def test_a_cold_run_kept_indefinitely_is_archived(archive_spine: Any) -> None:
    store, archive, _workspace, project_id = archive_spine
    await _finished_run(archive_spine, at=COLD)

    assert await store.archive_cold_runs(now=NOW, archive_after=NINETY_DAYS) == 1
    assert len(await _keys(archive, project_id)) == 1


async def test_a_run_with_a_deletion_date_is_never_archived(archive_spine: Any) -> None:
    """Decision 2, on the backend where it costs something.

    This Run is cold by every other measure. What disqualifies it is that
    somebody chose a date to delete it on, which makes it purge-eligible — and
    archiving it would convert that deletion decision into a storage one. The
    obvious implementation hooks the sweep into `purge_expired_runs`; this is
    the test that fails when someone does.
    """
    store, archive, _workspace, project_id = archive_spine
    await _finished_run(archive_spine, at=COLD, expires_at=NOW + timedelta(days=1))

    assert await store.archive_cold_runs(now=NOW, archive_after=NINETY_DAYS) == 0
    assert await _keys(archive, project_id) == []


async def test_a_recent_run_is_not_archived(archive_spine: Any) -> None:
    store, _archive, _workspace, _project_id = archive_spine
    await _finished_run(archive_spine, at=RECENT)

    assert await store.archive_cold_runs(now=NOW, archive_after=NINETY_DAYS) == 0


async def test_live_work_is_not_archived(archive_spine: Any) -> None:
    """A Run still running keeps its payload where it can be read without a
    network round trip, for the same reason retention never purges live work."""
    store, _archive, workspace, project_id = archive_spine
    run = await store.create_run(_graph(workspace, project_id))
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)

    assert await store.archive_cold_runs(now=NOW, archive_after=NINETY_DAYS) == 0


async def test_a_run_is_not_archived_twice(archive_spine: Any) -> None:
    """`PgRunStore` selects on `archive_key IS NULL`; the reference store keeps
    the same record in a dict. The put is idempotent either way — keys are
    content-addressed — but a count that reported the same Run as newly
    archived every pass would be useless for telling whether a backlog is
    draining."""
    store, archive, _workspace, project_id = archive_spine
    await _finished_run(archive_spine, at=COLD)

    assert await store.archive_cold_runs(now=NOW, archive_after=NINETY_DAYS) == 1
    assert await store.archive_cold_runs(now=NOW, archive_after=NINETY_DAYS) == 0
    assert len(await _keys(archive, project_id)) == 1


async def test_the_tier_is_off_without_an_archive_store(archive_spine: Any) -> None:
    """Decision 9. Off is today's behaviour, not a degraded mode."""
    store, _archive, _workspace, _project_id = archive_spine
    await _finished_run(archive_spine, at=COLD)
    unconfigured = _without_archive(store)

    assert await unconfigured.archive_cold_runs(now=NOW, archive_after=NINETY_DAYS) == 0


async def test_a_non_positive_limit_is_refused(archive_spine: Any) -> None:
    """A limit of zero would sweep forever and move nothing, and a negative one
    is a `LIMIT -1` the database reads as unbounded — the opposite of what a
    batch limit is for."""
    store, _archive, _workspace, _project_id = archive_spine

    with pytest.raises(ValueError, match="limit must be positive"):
        await store.archive_cold_runs(now=NOW, limit=0)


async def test_the_batch_limit_bounds_one_sweep(archive_spine: Any) -> None:
    """Sweeping is opportunistic: a backlog drains over several sweeps rather
    than one unbounded transaction holding row locks the whole time."""
    store, archive, _workspace, project_id = archive_spine
    for _ in range(3):
        await _finished_run(archive_spine, at=COLD)

    assert await store.archive_cold_runs(now=NOW, archive_after=NINETY_DAYS, limit=2) == 2
    assert len(await _keys(archive, project_id)) == 2


# ── what survives the move ────────────────────────────────────────


async def test_a_read_after_archiving_still_returns_the_run(archive_spine: Any) -> None:
    """Decision 6, and the reason `_payload` reads the tombstone beside the column.

    On PostgreSQL the payload really is NULL after this, so a store that did
    not read through would return `None` here — indistinguishable from
    deletion by every caller, which turns a cost optimisation into data loss at
    the API boundary.
    """
    store, _archive, _workspace, _project_id = archive_spine
    original = await _finished_run(archive_spine, at=COLD)

    await store.archive_cold_runs(now=NOW, archive_after=NINETY_DAYS)

    found = await store.get_run(original.run_id)
    assert found is not None, "archiving must not make a Run unreadable"
    assert found == original


async def test_identity_and_scope_outlive_the_payload(archive_spine: Any) -> None:
    """Why decision 2 calls archiving safe where deleting would not be.

    Only the payload moves. The row stays, so every foreign key into the spine
    still points at something and the Project still knows it has Runs.
    """
    store, _archive, _workspace, project_id = archive_spine
    run = await _finished_run(archive_spine, at=COLD)

    await store.archive_cold_runs(now=NOW, archive_after=NINETY_DAYS)

    assert await store.has_runs_in_project(project_id) is True
    found = await store.get_run(run.run_id)
    assert found is not None
    assert (found.run_id, found.project_id, found.status) == (
        run.run_id,
        project_id,
        RunStatus.COMPLETED,
    )


async def test_the_attempt_evidence_moves_and_still_reads_back(
    archive_spine: Any,
) -> None:
    """The half the tier exists for, and the half that is easy to skip.

    A Run's own payload is a graph snapshot and a result. The rows underneath
    are one per physical try, each carrying whatever the executor returned, and
    on a Run that retried they are most of the bytes — archiving the Run alone
    would move the index and leave the book.

    So the tree goes cold together, and reading down from the Run still works:
    an audit reads `list_node_runs` then `list_attempts`, and a list that
    silently dropped archived rows would report a Run as having had fewer
    tries than it did.
    """
    store, archive, workspace, project_id = archive_spine
    run = await store.create_run(_graph(workspace, project_id))
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    attempt = await store.create_attempt(node_run.node_run_id, lease_holder="worker-a")
    token = attempt.execution_lease.fencing_token
    await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING, fencing_token=token)
    await store.transition_attempt(attempt.attempt_id, AttemptStatus.COMPLETED, fencing_token=token)
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    await store.transition_run(run.run_id, RunStatus.COMPLETED, at=COLD)

    assert await store.archive_cold_runs(now=NOW, archive_after=NINETY_DAYS) == 1

    # Three records moved, not one: the Run, its NodeRun, its Attempt.
    assert len(await _keys(archive, project_id)) == 3

    assert [n.node_run_id for n in await store.list_node_runs(run.run_id)] == [node_run.node_run_id]
    found = await store.list_attempts(node_run.node_run_id)
    assert [a.attempt_id for a in found] == [attempt.attempt_id]
    assert found[0].status is AttemptStatus.COMPLETED
    assert await store.get_attempt(attempt.attempt_id) == found[0]


async def test_non_finite_evidence_survives_the_move(archive_spine: Any) -> None:
    """The archive must not become the one place a NaN quietly became null.

    `evidence_json` exists because pydantic's default serialiser writes
    non-finite floats as `null`, and the three backends may not disagree about
    what was recorded. Archiving is a fourth place the payload is serialised,
    so it gets the same encoder or it reintroduces the bug on a longer delay.
    """
    store, _archive, workspace, project_id = archive_spine
    run = await store.create_run(_graph(workspace, project_id))
    await store.transition_run(run.run_id, RunStatus.QUEUED)
    await store.transition_run(run.run_id, RunStatus.RUNNING)
    await store.transition_run(run.run_id, RunStatus.COMPLETED, at=COLD, result={"score": math.nan})

    assert await store.archive_cold_runs(now=NOW, archive_after=NINETY_DAYS) == 1

    found = await store.get_run(run.run_id)
    assert found is not None
    assert isinstance(found.result, dict)
    assert math.isnan(found.result["score"]), "a NaN result came back as something else"


def _without_archive(store: Any) -> Any:
    """The same store, same database, no archive tier configured."""
    from maistro.runs.pg_store import PgRunStore
    from maistro.runs.store import InMemoryRunStore

    if isinstance(store, PgRunStore):
        return PgRunStore(store._pool, project_store=store._project_store)
    assert isinstance(store, InMemoryRunStore)
    twin = InMemoryRunStore(project_store=store._project_store)
    twin._runs = store._runs
    return twin


async def test_an_archived_row_without_a_tier_says_so_rather_than_vanishing(
    archive_spine: Any,
) -> None:
    """The operator mistake decision 6 has to survive: the tier was configured,
    Runs were archived, and then the archive URL went away.

    Returning `None` would be the forbidden case, and `RunNotFound` would say
    the opposite of what is true. The record exists; what is missing is the
    tier it was moved to, and reconfiguring it makes the read work again.
    """
    from maistro.runs.pg_store import PgRunStore
    from maistro.runs.store import ArchivedPayloadUnavailable

    store, _archive, _workspace, _project_id = archive_spine
    if not isinstance(store, PgRunStore):
        pytest.skip("only a store that really moves the payload can lose it")
    run = await _finished_run(archive_spine, at=COLD)
    await store.archive_cold_runs(now=NOW, archive_after=NINETY_DAYS)

    with pytest.raises(ArchivedPayloadUnavailable, match="still exists in the tier"):
        await _without_archive(store).get_run(run.run_id)
