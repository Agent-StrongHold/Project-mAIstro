"""Canonical derivation of a parent Run from its logical NodeRun frontier.

This module owns only the fold. Whether more work is still owed belongs to
the execution substrate that knows routing/traversal. Once that substrate says
the logical frontier is complete, every product gets the same deterministic
Run outcome rather than inventing its own lifecycle mapping (#237).
"""

from __future__ import annotations

from collections.abc import Sequence

from maistro.runs.lifecycle import latest_node_runs
from maistro.runs.model import TERMINAL_RUN_STATUSES, NodeRun, RunStatus

# A definite logical failure outranks a deadline, which outranks cancellation;
# success is earned only when no stronger terminal outcome exists. External
# Run-level causes (a requested cancellation, a traversal deadline/fold error)
# remain authoritative by terminalizing the Run before this fold is applied.
RUN_TERMINAL_PRECEDENCE: tuple[RunStatus, ...] = (
    RunStatus.FAILED,
    RunStatus.TIMED_OUT,
    RunStatus.CANCELLED,
    RunStatus.COMPLETED,
)


def derive_run_terminal_status(
    node_runs: Sequence[NodeRun],
    *,
    work_owed: bool = False,
) -> RunStatus | None:
    """Derive one terminal Run status when the complete logical frontier is terminal.

    ``work_owed`` is deliberately supplied by the caller. A generic Run store can
    see NodeRuns but cannot know that a conditional Graph branch was not selected;
    GraphExecutionState can. Keeping that fact outside the fold prevents the spine
    from treating an absent NodeRun as an intentionally skipped branch. If the
    authoritative caller says no work is owed and there are no NodeRuns at all,
    the empty logical frontier is successfully complete.
    """
    if work_owed:
        return None
    latest = tuple(latest_node_runs(list(node_runs)).values())
    if not latest:
        return RunStatus.COMPLETED
    if any(node_run.status not in TERMINAL_RUN_STATUSES for node_run in latest):
        return None
    statuses = {node_run.status for node_run in latest}
    return next((status for status in RUN_TERMINAL_PRECEDENCE if status in statuses), None)


def terminal_run_payload(
    node_runs: Sequence[NodeRun],
    target: RunStatus,
) -> tuple[object | None, str | None]:
    """Carry the newest NodeRun evidence matching the derived parent outcome."""
    latest = sorted(latest_node_runs(list(node_runs)).values(), key=lambda item: item.ordinal)
    matching = [node_run for node_run in latest if node_run.status is target]
    if not matching:
        return None, None
    chosen = matching[-1]
    if target is RunStatus.COMPLETED:
        return chosen.result, None
    return None, chosen.error


__all__ = [
    "RUN_TERMINAL_PRECEDENCE",
    "derive_run_terminal_status",
    "terminal_run_payload",
]
