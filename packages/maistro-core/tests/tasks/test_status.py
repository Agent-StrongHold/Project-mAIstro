"""Full state x input matrix for the task status machine (tasks/status.py).

The expected edge set below is independently re-derived from the design intent
documented in tasks/status.py's docstring/comments — it does NOT import
TRANSITIONS — so this test can't trivially pass by re-checking the
implementation against itself.
"""

from __future__ import annotations

import itertools

import pytest

from maistro.tasks.models import TaskStatus
from maistro.tasks.status import can_transition

# Independently re-derived expected transitions:
#   QUEUED    -> PLANNING (kicked off) or CANCELLED (aborted before starting)
#   PLANNING  -> CODING (plan ready), or FAILED/CANCELLED
#   CODING    -> REVIEWING (code ready), COMPLETED (no review step needed),
#                or FAILED/CANCELLED
#   REVIEWING -> TESTING (approved), CODING (rejected back for rework),
#                or FAILED/CANCELLED
#   TESTING   -> COMPLETED (passed), CODING (failed tests, back for rework),
#                or FAILED/CANCELLED
#   COMPLETED, FAILED, CANCELLED -> terminal, no further transitions
EXPECTED: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.QUEUED: frozenset({TaskStatus.PLANNING, TaskStatus.CANCELLED}),
    TaskStatus.PLANNING: frozenset({TaskStatus.CODING, TaskStatus.FAILED, TaskStatus.CANCELLED}),
    TaskStatus.CODING: frozenset(
        {
            TaskStatus.REVIEWING,
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.REVIEWING: frozenset(
        {
            TaskStatus.TESTING,
            TaskStatus.CODING,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.TESTING: frozenset(
        {
            TaskStatus.COMPLETED,
            TaskStatus.CODING,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.FAILED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}

TERMINAL_STATES = (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)

ALL_PAIRS = list(itertools.product(TaskStatus, TaskStatus))


@pytest.mark.parametrize(
    "current,target",
    ALL_PAIRS,
    ids=[f"{c.value}->{t.value}" for c, t in ALL_PAIRS],
)
def test_transition_matrix(current: TaskStatus, target: TaskStatus) -> None:
    expected = target in EXPECTED[current]
    assert can_transition(current, target) is expected


class TestTerminalStatesAreAbsorbing:
    @pytest.mark.parametrize("terminal", TERMINAL_STATES)
    def test_no_outgoing_transitions(self, terminal: TaskStatus) -> None:
        for target in TaskStatus:
            assert can_transition(terminal, target) is False

    @pytest.mark.parametrize("terminal", TERMINAL_STATES)
    def test_terminal_cannot_self_transition(self, terminal: TaskStatus) -> None:
        assert can_transition(terminal, terminal) is False


class TestNoSelfTransitions:
    @pytest.mark.parametrize("status", list(TaskStatus))
    def test_no_status_can_self_transition(self, status: TaskStatus) -> None:
        assert can_transition(status, status) is False


class TestReworkLoops:
    """REVIEWING/TESTING can bounce back to CODING — confirm both directions are
    asymmetric (CODING cannot jump forward to REVIEWING/TESTING's downstream
    states without passing through the intermediate phase)."""

    def test_reviewing_rejects_back_to_coding(self) -> None:
        assert can_transition(TaskStatus.REVIEWING, TaskStatus.CODING) is True

    def test_testing_fails_back_to_coding(self) -> None:
        assert can_transition(TaskStatus.TESTING, TaskStatus.CODING) is True

    def test_coding_cannot_skip_to_testing(self) -> None:
        assert can_transition(TaskStatus.CODING, TaskStatus.TESTING) is False

    def test_queued_cannot_skip_to_coding(self) -> None:
        assert can_transition(TaskStatus.QUEUED, TaskStatus.CODING) is False


class TestUnrecognizedCurrentDefaultsClosed:
    """Found via exploratory poking (docs/EXPLORATORY-TESTING.md session log
    2026-06-28-task-status): can_transition's `TRANSITIONS.get(current, set())`
    silently treats any `current` absent from TRANSITIONS as having no valid
    outgoing transitions, rather than raising KeyError. Today every TaskStatus
    member has a TRANSITIONS entry so this never fires in practice — but a
    future status added to the enum without a matching TRANSITIONS entry would
    silently fail closed (no transition allowed) instead of erroring loudly.
    Locked in here so that's a deliberate choice, not a discovered-by-accident
    side effect."""

    def test_value_not_in_transitions_table_has_no_valid_targets(self) -> None:
        assert can_transition("not-a-real-status", TaskStatus.PLANNING) is False
