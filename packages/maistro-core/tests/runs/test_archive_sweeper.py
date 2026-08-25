"""What actually drives the archive sweep, and what keeps it from firing (#273).

`test_archive_sweep.py` holds the *predicate* — which Runs are eligible. These
tests hold the *driver*: the sweep is off unless a deployment names a horizon
(ADR-082226-f436 decision 9), it is inert on a store with no archive tier, it
cannot fail the request it rides on, and it is reached from a production path
rather than only from tests.

The last one is the point. A sweep nothing calls is the "wired but never read"
defect #236 exists to gate, and it is the defect this PR was opened to remove
from `archive_store` — shipping the sweep with the same shape would have been
the joke telling itself.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from maistro.archive.filesystem import FilesystemArchiveStore
from maistro.graph import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.archival import ARCHIVE_DISABLED, ArchivePolicy, RunArchiveSweeper
from maistro.runs.chat_admission import ChatRunAdmitter
from maistro.runs.model import RunStatus
from maistro.runs.store import InMemoryRunStore

NOW = datetime(2026, 8, 25, tzinfo=UTC)
COLD = NOW - timedelta(days=200)
ONE_DAY = timedelta(days=1)


@pytest.fixture
async def spine(tmp_path: Any) -> Any:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("w1")
    archive = FilesystemArchiveStore(str(tmp_path))
    store = InMemoryRunStore(project_store=projects, archive_store=archive)
    return store, archive, root


async def _cold_run(spine: Any) -> Any:
    """A Run that every eligibility rule admits, so only the driver is under test."""
    store, _archive, root = spine
    graph = Graph(
        workspace_id="w1",
        project_id=root.project_id,
        name="graph",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = await store.create_run(graph)
    moved = run.model_copy(
        update={
            "status": RunStatus.COMPLETED,
            "finished_at": COLD,
            "retention_expires_at": None,
        }
    )
    store._runs[run.run_id] = moved
    return moved


async def _keys(archive: FilesystemArchiveStore, scope: str) -> list[Any]:
    return [key async for key in archive.list_scope(scope)]


# --- the policy decides whether anything happens at all -------------------


async def test_the_default_policy_archives_nothing(spine: Any) -> None:
    """Decision 9. Wiring the sweeper in must not change any deployment's
    behaviour until an operator picks a horizon.

    The Run here is cold by every measure, and an archive store is configured.
    The only thing standing between it and the bucket is that nobody asked."""
    store, archive, root = spine
    await _cold_run(spine)
    sweeper = RunArchiveSweeper(store)

    assert sweeper.policy is ARCHIVE_DISABLED
    assert await sweeper.maybe_sweep(now=NOW) == 0
    assert await _keys(archive, root.project_id) == []


async def test_a_named_horizon_turns_it_on(spine: Any) -> None:
    store, archive, root = spine
    await _cold_run(spine)
    sweeper = RunArchiveSweeper(store, ArchivePolicy(archive_after=ONE_DAY))

    assert await sweeper.maybe_sweep(now=NOW) == 1
    assert len(await _keys(archive, root.project_id)) == 1


async def test_a_negative_sweep_interval_is_refused() -> None:
    with pytest.raises(ValueError, match="sweep_interval_seconds cannot be negative"):
        ArchivePolicy(archive_after=ONE_DAY, sweep_interval_seconds=-1)


async def test_a_non_positive_batch_limit_is_refused() -> None:
    """A limit of zero would be a sweeper that runs forever and moves nothing."""
    with pytest.raises(ValueError, match="batch_limit must be positive"):
        ArchivePolicy(archive_after=ONE_DAY, batch_limit=0)


async def test_a_horizon_of_zero_is_refused() -> None:
    """`None` means "archive nothing"; a zero horizon would mean "archive work
    the instant it finishes", which is a different thing that nobody wants and
    is one keystroke away from the setting that disables the tier."""
    with pytest.raises(ValueError, match="archive_after must be positive"):
        ArchivePolicy(archive_after=timedelta(0))


# --- inert where it cannot work ------------------------------------------


async def test_a_store_that_cannot_archive_is_not_an_error() -> None:
    """The SQLite twin has no archive columns, and a deployment on it must not
    have to special-case the sweeper at the call site.

    Constructed against an object with no `archive_cold_runs` at all — the
    capability check is `isinstance` against the protocol, so a store that
    grows the method later starts working with no change here."""

    class _NoArchiveTier:
        pass

    sweeper = RunArchiveSweeper(_NoArchiveTier(), ArchivePolicy(archive_after=ONE_DAY))  # type: ignore[arg-type]
    assert await sweeper.maybe_sweep(now=NOW) == 0


async def test_a_failing_archive_never_fails_the_caller() -> None:
    """Housekeeping rides on a request path. An unreachable bucket is an
    operational problem; a refused chat turn is a user-visible outage, and the
    second must not be caused by the first."""

    class _BrokenArchiver:
        async def archive_cold_runs(self, **_: Any) -> int:
            raise ConnectionError("bucket unreachable")

    sweeper = RunArchiveSweeper(_BrokenArchiver(), ArchivePolicy(archive_after=ONE_DAY))  # type: ignore[arg-type]
    assert await sweeper.maybe_sweep(now=NOW) == 0


# --- the throttle ---------------------------------------------------------


async def test_a_second_sweep_inside_the_interval_does_nothing(spine: Any) -> None:
    """Otherwise every admission on a busy deployment is a full scan."""
    store, _archive, _root = spine
    await _cold_run(spine)
    sweeper = RunArchiveSweeper(
        store, ArchivePolicy(archive_after=ONE_DAY, sweep_interval_seconds=3600)
    )

    assert await sweeper.maybe_sweep(now=NOW) == 1
    await _cold_run(spine)
    assert await sweeper.maybe_sweep(now=NOW) == 0


async def test_a_zero_interval_sweeps_every_time(spine: Any) -> None:
    """The throttle is a cost control, not a correctness rule, so a deployment
    that wants continuous sweeping may have it."""
    store, _archive, _root = spine
    await _cold_run(spine)
    sweeper = RunArchiveSweeper(
        store, ArchivePolicy(archive_after=ONE_DAY, sweep_interval_seconds=0)
    )

    assert await sweeper.maybe_sweep(now=NOW) == 1
    await _cold_run(spine)
    assert await sweeper.maybe_sweep(now=NOW) == 1


# --- the production path --------------------------------------------------


async def test_admitting_a_chat_turn_drives_the_sweep(spine: Any) -> None:
    """The caller that makes this reachable in production.

    Without this test the sweep is dead code that passes its own unit tests —
    exactly the state `exact-debt-ledger` flagged, and the reason it is wired
    to a real seam rather than banked as debt.
    """
    store, archive, root = spine
    cold = await _cold_run(spine)
    admitter = ChatRunAdmitter(
        store,
        workspace_id="w1",
        project_id=root.project_id,
        archive=ArchivePolicy(archive_after=ONE_DAY),
    )

    await admitter.admit([{"role": "user", "content": "what broke?"}])

    (key,) = await _keys(archive, root.project_id)
    assert json.loads(await archive.get(key))["run_id"] == cold.run_id


async def test_a_chat_turns_own_run_is_never_the_one_archived(spine: Any) -> None:
    """Admission is the clock, not the subject.

    A chat Run carries a retention deadline, which makes it purge-eligible and
    therefore never archive-eligible (decision 10). If a later refactor ever
    lets the tier reach into deadline-bearing Runs, this is where it shows up:
    the turn admitted a line above would follow itself into the bucket.
    """
    store, archive, root = spine
    admitter = ChatRunAdmitter(
        store,
        workspace_id="w1",
        project_id=root.project_id,
        archive=ArchivePolicy(archive_after=timedelta(microseconds=1)),
    )

    run = await admitter.admit([{"role": "user", "content": "what broke?"}])

    assert run.retention_expires_at is not None, "a chat Run is supposed to carry a deadline"
    assert await _keys(archive, root.project_id) == []


async def test_chat_admission_leaves_the_tier_off_by_default(spine: Any) -> None:
    """The wiring is present; the behaviour is not, until asked for."""
    store, archive, root = spine
    await _cold_run(spine)
    admitter = ChatRunAdmitter(store, workspace_id="w1", project_id=root.project_id)

    await admitter.admit([{"role": "user", "content": "what broke?"}])

    assert await _keys(archive, root.project_id) == []


async def test_only_one_of_two_concurrent_sweeps_runs(spine: Any) -> None:
    """A burst of admissions produces one sweep, not a queue of them.

    Without the in-flight check every concurrent chat turn on a busy
    deployment would queue behind the same scan, and the sweep would go from
    housekeeping to the slowest thing on the request path.
    """
    store, archive, root = spine
    await _cold_run(spine)
    sweeper = RunArchiveSweeper(
        store, ArchivePolicy(archive_after=ONE_DAY, sweep_interval_seconds=0)
    )

    swept = await asyncio.gather(sweeper.maybe_sweep(now=NOW), sweeper.maybe_sweep(now=NOW))

    assert sorted(swept) == [0, 1]
    assert len(await _keys(archive, root.project_id)) == 1
