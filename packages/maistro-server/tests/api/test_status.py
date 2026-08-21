"""Tests for task state machine.

Evidence: Tasks follow a strict lifecycle:
queued → planning → coding → reviewing → testing → completed
with valid back-transitions for review rejection and test failure.
"""

from __future__ import annotations

from maistro.tasks.models import TaskStatus
from maistro.tasks.status import can_transition


class TestTaskStateMachine:
    """Evidence: The state machine defines which transitions are valid.
    Invalid transitions must be rejected to prevent state corruption."""

    def test_queued_to_planning(self) -> None:
        assert can_transition(TaskStatus.QUEUED, TaskStatus.PLANNING)

    def test_planning_to_coding(self) -> None:
        assert can_transition(TaskStatus.PLANNING, TaskStatus.CODING)

    def test_coding_to_reviewing(self) -> None:
        assert can_transition(TaskStatus.CODING, TaskStatus.REVIEWING)

    def test_reviewing_to_testing(self) -> None:
        assert can_transition(TaskStatus.REVIEWING, TaskStatus.TESTING)

    def test_testing_to_completed(self) -> None:
        assert can_transition(TaskStatus.TESTING, TaskStatus.COMPLETED)

    def test_reviewer_rejection_back_to_coding(self) -> None:
        """Evidence: Reviewer can reject → back to coding for retry."""
        assert can_transition(TaskStatus.REVIEWING, TaskStatus.CODING)

    def test_test_failure_back_to_coding(self) -> None:
        """Evidence: Test failures → back to coding for fix."""
        assert can_transition(TaskStatus.TESTING, TaskStatus.CODING)

    def test_any_state_can_cancel(self) -> None:
        """Evidence: Any non-terminal state can be cancelled."""
        for status in [
            TaskStatus.QUEUED,
            TaskStatus.PLANNING,
            TaskStatus.CODING,
            TaskStatus.REVIEWING,
            TaskStatus.TESTING,
        ]:
            assert can_transition(status, TaskStatus.CANCELLED), f"{status} should be cancellable"

    def test_any_active_state_can_fail(self) -> None:
        for status in [
            TaskStatus.PLANNING,
            TaskStatus.CODING,
            TaskStatus.REVIEWING,
            TaskStatus.TESTING,
        ]:
            assert can_transition(status, TaskStatus.FAILED), f"{status} should allow failure"

    def test_terminal_states_have_no_transitions(self) -> None:
        """Evidence: completed, failed, cancelled are terminal — no outgoing transitions."""
        for terminal in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
            for target in TaskStatus:
                if target != terminal:
                    assert not can_transition(terminal, target), (
                        f"{terminal} should not transition to {target}"
                    )

    def test_invalid_skip_transitions(self) -> None:
        """Evidence: Can't skip phases (e.g., queued → completed)."""
        assert not can_transition(TaskStatus.QUEUED, TaskStatus.COMPLETED)
        assert not can_transition(TaskStatus.QUEUED, TaskStatus.CODING)
        assert not can_transition(TaskStatus.PLANNING, TaskStatus.COMPLETED)
        assert not can_transition(TaskStatus.PLANNING, TaskStatus.TESTING)
