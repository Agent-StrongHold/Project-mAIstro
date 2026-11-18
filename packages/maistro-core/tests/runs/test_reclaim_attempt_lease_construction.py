"""P2a: reclaim_attempt is the expired-lease RECOVERED writer (#2354 / #232).

Construction only — no store protocol, Graph adapter, or activation changes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from maistro.runs.lifecycle import (
    InvalidLifecycleTransition,
    is_reclaimed_attempt,
    reclaim_attempt,
    transition_attempt,
)
from maistro.runs.model import (
    Attempt,
    AttemptStatus,
    CancellationCause,
    ExecutionLease,
)


def _t(offset_s: int = 0) -> datetime:
    return datetime(2026, 10, 25, 18, 0, 0, tzinfo=UTC) + timedelta(seconds=offset_s)


def _running_with_lease(
    *,
    issued_at: datetime,
    expires_at: datetime | None,
    holder: str = "worker-1",
    result: object | None = None,
    metrics: dict[str, object] | None = None,
) -> Attempt:
    created = Attempt(node_run_id="nr-1", ordinal=1, created_at=issued_at)
    running = transition_attempt(created, AttemptStatus.RUNNING, at=issued_at)
    values = running.model_dump(mode="python")
    values["execution_lease"] = ExecutionLease(
        node_run_id=running.node_run_id,
        attempt_id=running.attempt_id,
        lease_epoch=1,
        holder=holder,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    if result is not None:
        values["result"] = result
    if metrics is not None:
        values["metrics"] = metrics
    return Attempt.model_validate(values)


class TestReclaimExpiredLeaseWritesRecoveredCause:
    def test_expired_finite_lease_commits_cancelled_recovered_and_preserves_result(
        self,
    ) -> None:
        prior = {"partial": True}
        metrics = {"tokens": 3}
        leased = _running_with_lease(
            issued_at=_t(0),
            expires_at=_t(5),
            result=prior,
            metrics=metrics,
        )

        reclaimed = reclaim_attempt(leased, at=_t(5))

        assert reclaimed.status is AttemptStatus.CANCELLED
        assert reclaimed.cancellation_cause is CancellationCause.RECOVERED
        assert reclaimed.finished_at == _t(5)
        assert reclaimed.result == prior
        assert reclaimed.metrics == metrics
        assert reclaimed.error is not None and "worker-1" in reclaimed.error
        assert is_reclaimed_attempt(reclaimed)
        assert reclaimed.model_dump(mode="json")["cancellation_cause"] == "recovered"

    def test_expiry_equal_to_moment_qualifies(self) -> None:
        leased = _running_with_lease(issued_at=_t(0), expires_at=_t(10))
        reclaimed = reclaim_attempt(leased, at=_t(10))
        assert reclaimed.cancellation_cause is CancellationCause.RECOVERED


class TestReclaimRefusals:
    def test_live_lease_is_refused(self) -> None:
        leased = _running_with_lease(issued_at=_t(0), expires_at=_t(10))
        with pytest.raises(InvalidLifecycleTransition, match="still live"):
            reclaim_attempt(leased, at=_t(9))

    def test_no_lease_is_refused(self) -> None:
        running = transition_attempt(
            Attempt(node_run_id="nr-1", ordinal=1, created_at=_t(0)),
            AttemptStatus.RUNNING,
            at=_t(0),
        )
        with pytest.raises(InvalidLifecycleTransition, match="no execution lease"):
            reclaim_attempt(running, at=_t(10))

    def test_infinite_lease_is_refused(self) -> None:
        leased = _running_with_lease(issued_at=_t(0), expires_at=None)
        with pytest.raises(InvalidLifecycleTransition, match="infinite lease"):
            reclaim_attempt(leased, at=_t(10_000))

    def test_terminal_attempt_is_refused(self) -> None:
        leased = _running_with_lease(issued_at=_t(0), expires_at=_t(5))
        done = transition_attempt(leased, AttemptStatus.COMPLETED, at=_t(3), result={"ok": 1})
        with pytest.raises(InvalidLifecycleTransition, match="terminal"):
            reclaim_attempt(done, at=_t(10))

    def test_created_with_expired_lease_still_reclaims(self) -> None:
        """CREATED is active for reclaim; only terminal statuses are refused."""
        created = Attempt(node_run_id="nr-1", ordinal=1, created_at=_t(0))
        leased = Attempt.model_validate(
            {
                **created.model_dump(mode="python"),
                "execution_lease": ExecutionLease(
                    node_run_id=created.node_run_id,
                    attempt_id=created.attempt_id,
                    lease_epoch=1,
                    holder="prelaunch",
                    issued_at=_t(0),
                    expires_at=_t(2),
                ),
            }
        )
        reclaimed = reclaim_attempt(leased, at=_t(2))
        assert reclaimed.status is AttemptStatus.CANCELLED
        assert reclaimed.cancellation_cause is CancellationCause.RECOVERED


class TestGenericTransitionStillRejectsRecovered:
    def test_transition_attempt_does_not_take_a_recovered_argument(self) -> None:
        """P2a must not grow a RECOVERED kwarg on the generic transition."""
        import inspect

        params = inspect.signature(transition_attempt).parameters
        assert "cancellation_cause" not in params
