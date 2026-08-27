"""Exhaustive precedence proof for canonical Run terminal derivation (#237)."""

from __future__ import annotations

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
                assert derive_run_terminal_status(_terminal_node_runs(ordered)) is expected
