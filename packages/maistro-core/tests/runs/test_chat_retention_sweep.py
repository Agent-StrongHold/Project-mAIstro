"""Chat retention has a durable half, and something calls it (#132).

`ChatRunAdmitter` keeps a per-process window of the Runs it admitted and
deletes the oldest terminal ones above it. That window starts empty after a
restart, so on a durable store a chat Run admitted by a process that has since
exited is one nothing would ever sweep — `chat_admission.py`'s own docstring
names that gap and assigns it here.

The fix is two halves and both have to be present: the Run carries a deadline
on the row, and something drives `purge_expired_runs` against it. A policy
object with no caller would satisfy neither, which is what these hold.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.chat_admission import ChatRunAdmitter
from maistro.runs.model import RunStatus
from maistro.runs.retention import UNBOUNDED_RETENTION, RetentionPolicy
from maistro.runs.store import InMemoryRunStore


@pytest.fixture
async def wired():
    projects = InMemoryProjectScopeStore()
    await projects.create_root("w1")
    runs = InMemoryRunStore(project_store=projects)
    return runs, projects


def _admitter(runs, projects, **kwargs) -> ChatRunAdmitter:
    return ChatRunAdmitter(runs, workspace_id="w1", project_store=projects, **kwargs)


async def test_an_admitted_chat_run_carries_a_retention_deadline(wired) -> None:
    """The durable half. Without this the sweep has nothing to select on."""
    runs, projects = wired
    admitter = _admitter(runs, projects)

    run = await admitter.admit([{"role": "user", "content": "hello"}])

    assert run.retention_expires_at is not None
    assert run.retention_expires_at > datetime.now(UTC)


async def test_opting_out_leaves_the_deadline_unset(wired) -> None:
    """`None` is what every Run outside this policy already carries, so it is
    the setting that returns a deployment to today's behaviour exactly."""
    runs, projects = wired
    admitter = _admitter(runs, projects, retention=UNBOUNDED_RETENTION)

    run = await admitter.admit([{"role": "user", "content": "hello"}])

    assert run.retention_expires_at is None


async def test_admission_sweeps_a_run_this_process_never_admitted(wired) -> None:
    """The restart case, which the in-process window cannot reach.

    The stale Run is created directly against the store and never enters any
    admitter's window — exactly the state a previous process leaves behind.
    """
    runs, projects = wired
    short = RetentionPolicy(ttl_seconds=1, sweep_interval_seconds=0)
    stale = await _admitter(runs, projects, retention=short).admit(
        [{"role": "user", "content": "old"}]
    )
    await runs.transition_run(stale.run_id, RunStatus.QUEUED)
    await runs.transition_run(stale.run_id, RunStatus.RUNNING)
    await runs.transition_run(stale.run_id, RunStatus.COMPLETED)

    # A second admitter: a fresh process, with an empty window.
    restarted = _admitter(runs, projects, retention=short)
    assert restarted.retained == 0
    await restarted.sweeper.sweep_now(now=datetime.now(UTC) + timedelta(hours=1))

    assert await runs.get_run(stale.run_id) is None


async def test_a_live_run_past_its_deadline_keeps_its_identity(wired) -> None:
    """The deadline is a floor, not a ceiling: deleting the execution identity
    of work still running is worse than the storage it reclaims."""
    runs, projects = wired
    admitter = _admitter(
        runs, projects, retention=RetentionPolicy(ttl_seconds=1, sweep_interval_seconds=0)
    )
    run = await admitter.admit([{"role": "user", "content": "still going"}])
    await runs.transition_run(run.run_id, RunStatus.QUEUED)
    await runs.transition_run(run.run_id, RunStatus.RUNNING)

    await admitter.sweeper.sweep_now(now=datetime.now(UTC) + timedelta(hours=1))

    assert await runs.get_run(run.run_id) is not None


async def test_a_sweep_failure_never_refuses_the_turn(wired) -> None:
    """Retention is housekeeping. A database hiccup during a sweep must not
    turn into a user's chat turn being refused."""
    runs, projects = wired
    admitter = _admitter(
        runs, projects, retention=RetentionPolicy(ttl_seconds=1, sweep_interval_seconds=0)
    )

    async def _explode(**_kwargs: object) -> int:
        raise RuntimeError("the database went away")

    runs.purge_expired_runs = _explode  # type: ignore[method-assign]

    run = await admitter.admit([{"role": "user", "content": "hello"}])

    assert run.run_id
    assert isinstance(admitter.sweeper.last_error, RuntimeError)
