"""P4b: recover_leaseless_orphaned_attempt refusal + happy construction (#232)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum

import pytest

from maistro.runs.lifecycle import (
    InvalidLifecycleTransition,
    recover_leaseless_orphaned_attempt,
    transition_attempt,
)
from maistro.runs.model import (
    Attempt,
    AttemptStatus,
    CancellationCause,
    ExecutionLease,
)


class _BogusAttemptStatus(StrEnum):
    """Not a real AttemptStatus — exercises the defensive non-CREATED/RUNNING guard."""

    PENDING = "pending"


def _t(offset_s: int = 0) -> datetime:
    return datetime(2026, 11, 20, 12, 0, 0, tzinfo=UTC) + timedelta(seconds=offset_s)


def _leaseless_running() -> Attempt:
    created = Attempt(node_run_id="nr-1", ordinal=1, created_at=_t(0))
    return transition_attempt(created, AttemptStatus.RUNNING, at=_t(1))


class TestRecoverLeaselessHappyPath:
    def test_leaseless_running_commits_cancelled_recovered(self) -> None:
        running = _leaseless_running()
        settled = recover_leaseless_orphaned_attempt(running, at=_t(2), error="process lost")

        assert settled.status is AttemptStatus.CANCELLED
        assert settled.cancellation_cause is CancellationCause.RECOVERED
        assert settled.finished_at == _t(2)
        assert settled.error == "process lost"
        assert settled.execution_lease is None

    def test_leaseless_created_uses_default_error(self) -> None:
        created = Attempt(node_run_id="nr-1", ordinal=1, created_at=_t(0))
        settled = recover_leaseless_orphaned_attempt(created, at=_t(1))

        assert settled.status is AttemptStatus.CANCELLED
        assert settled.cancellation_cause is CancellationCause.RECOVERED
        assert "orphaned" in (settled.error or "")


class TestRecoverLeaselessRefusals:
    def test_terminal_status_is_refused(self) -> None:
        running = _leaseless_running()
        done = transition_attempt(running, AttemptStatus.COMPLETED, at=_t(2), result={"ok": 1})
        with pytest.raises(InvalidLifecycleTransition, match="terminal"):
            recover_leaseless_orphaned_attempt(done, at=_t(3))

    def test_non_created_non_running_status_is_refused(self) -> None:
        """Defensive guard for statuses outside the CREATED/RUNNING pair.

        Every current AttemptStatus is either CREATED/RUNNING or terminal, so
        the construction bypasses validation with a synthetic status enum.
        """
        weird = Attempt.model_construct(
            attempt_id="att-weird",
            node_run_id="nr-1",
            ordinal=1,
            status=_BogusAttemptStatus.PENDING,  # type: ignore[arg-type]
            created_at=_t(0),
            started_at=None,
            finished_at=None,
            execution_lease=None,
            cancellation_cause=None,
            runtime_id="python",
            executor_id="",
            metrics={},
        )
        with pytest.raises(InvalidLifecycleTransition, match="CREATED or RUNNING"):
            recover_leaseless_orphaned_attempt(weird, at=_t(1))

    def test_still_holding_a_lease_is_refused(self) -> None:
        running = _leaseless_running()
        leased = Attempt.model_validate(
            {
                **running.model_dump(mode="python"),
                "execution_lease": ExecutionLease(
                    node_run_id=running.node_run_id,
                    attempt_id=running.attempt_id,
                    lease_epoch=1,
                    holder="worker-1",
                    issued_at=_t(1),
                    expires_at=_t(30),
                ),
            }
        )
        with pytest.raises(InvalidLifecycleTransition, match="still holds a lease"):
            recover_leaseless_orphaned_attempt(leased, at=_t(2))

    def test_already_carrying_cancellation_cause_is_refused(self) -> None:
        """Non-terminal + cause is invalid shape; bypass validators to hit the guard."""
        tainted = Attempt.model_construct(
            attempt_id="att-tainted",
            node_run_id="nr-1",
            ordinal=1,
            status=AttemptStatus.RUNNING,
            created_at=_t(0),
            started_at=_t(1),
            finished_at=None,
            execution_lease=None,
            cancellation_cause=CancellationCause.REQUESTED,
            runtime_id="python",
            executor_id="",
            metrics={},
        )
        with pytest.raises(InvalidLifecycleTransition, match="already carries"):
            recover_leaseless_orphaned_attempt(tainted, at=_t(2))
