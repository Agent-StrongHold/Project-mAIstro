"""Exhaustive precedence proof for canonical Run terminal derivation (#237)."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from itertools import combinations

import pytest

from maistro.runs.aggregation import RUN_TERMINAL_PRECEDENCE, derive_run_terminal_status
from maistro.runs.model import NodeRun, RunStatus


def _terminal_node_runs(statuses: tuple[RunStatus, ...]) -> list[NodeRun]:
    finished_at = datetime.now(UTC)
    return [
        NodeRun(
            run_id="run-precedence",
            node_id=f"node-{index}",
            ordinal=1,
            status=status,
            finished_at=finished_at,
        )
        for index, status in enumerate(statuses, start=1)
    ]


@pytest.mark.ac("ADR-082526-237d/AC-3")
def test_terminal_precedence_is_total_and_order_independent() -> None:
    """Every terminal mixture follows FAILED > TIMED_OUT > CANCELLED > COMPLETED."""
    precedence = RUN_TERMINAL_PRECEDENCE

    for size in range(1, len(precedence) + 1):
        for subset in combinations(precedence, size):
            expected = next(status for status in precedence if status in subset)
            for ordered in (subset, tuple(reversed(subset))):
                assert (
                    derive_run_terminal_status(_terminal_node_runs(ordered), work_owed=False)
                    is expected
                )


def test_work_owed_has_no_default_so_a_caller_cannot_forget_it() -> None:
    """#1188: a permissive default let an empty frontier silently derive COMPLETED.

    Removing the default from the shared derivation boundary means a new
    caller that has not decided whether work is owed gets a `TypeError` at the
    call site, not a wrong answer at runtime.
    """
    parameter = inspect.signature(derive_run_terminal_status).parameters["work_owed"]
    assert parameter.default is inspect.Parameter.empty
    with pytest.raises(TypeError):
        derive_run_terminal_status([])


def test_an_empty_frontier_with_work_owed_is_not_yet_terminal() -> None:
    """Zero observed NodeRuns is not evidence of completion when work is owed.

    A caller that knows more NodeRuns are coming (an active traversal
    frontier, an unresolved fan-in) must not have that fact overridden by
    "nothing has reported yet" looking exactly like "there was never
    anything to report."
    """
    assert derive_run_terminal_status([], work_owed=True) is None


def test_an_empty_frontier_with_no_work_owed_is_deliberately_complete() -> None:
    """Zero NodeRuns is only COMPLETED when the caller affirmatively says so."""
    assert derive_run_terminal_status([], work_owed=False) is RunStatus.COMPLETED


def test_a_partial_observation_is_never_terminal_regardless_of_work_owed() -> None:
    """A NodeRun still in flight blocks derivation whether or not more are owed."""
    in_flight = [
        NodeRun(run_id="run-partial", node_id="node-1", ordinal=1, status=RunStatus.RUNNING),
    ]
    mixed = [
        *in_flight,
        NodeRun(
            run_id="run-partial",
            node_id="node-2",
            ordinal=1,
            status=RunStatus.FAILED,
            finished_at=datetime.now(UTC),
        ),
    ]

    assert derive_run_terminal_status(in_flight, work_owed=False) is None
    assert derive_run_terminal_status(in_flight, work_owed=True) is None
    assert derive_run_terminal_status(mixed, work_owed=False) is None
    assert derive_run_terminal_status(mixed, work_owed=True) is None
