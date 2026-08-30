"""The yield path's edges, which the happy path never reaches (#545).

`ExecutionYielded.as_result` and `_pause_node_run`'s guards are both reachable
only from states the consumer's own tests do not produce: evidence that is not
a mapping, and a NodeRun that is already parked or was never running. They are
the branches a later change would break silently, so they get direct tests
rather than coverage borrowed from the paths above them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from maistro.runs.execution import ExecutionYielded
from maistro.runs.model import (
    PAUSE_AWAITS_HUMAN,
    Attempt,
    AttemptStatus,
    NodeRun,
    RunStatus,
)
from maistro.runs.reconciliation import AttemptLifecycleReconciler
from maistro.runs.store import RunIntegrityError

FINISHED = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


class TestAsResult:
    """What a yielded Attempt records, for each shape the evidence can take."""

    def test_a_mapping_is_merged_beside_the_pause_flag(self) -> None:
        yielded = ExecutionYielded(awaits_human=True, evidence={"resume_at": "x"})

        assert yielded.as_result() == {PAUSE_AWAITS_HUMAN: True, "resume_at": "x"}

    def test_a_non_mapping_is_kept_under_its_own_key(self) -> None:
        """Merging a non-mapping would raise; dropping it would lose the record."""
        yielded = ExecutionYielded(awaits_human=False, evidence="waiting on a person")

        assert yielded.as_result() == {
            PAUSE_AWAITS_HUMAN: False,
            "evidence": "waiting on a person",
        }

    def test_absent_evidence_leaves_only_the_pause_flag(self) -> None:
        assert ExecutionYielded().as_result() == {PAUSE_AWAITS_HUMAN: False}


class _OneNodeRunStore:
    """The narrowest store the guard needs: one NodeRun, and a recorded write."""

    def __init__(self, node_run: NodeRun) -> None:
        self.node_run = node_run
        self.transitions: list[tuple[str, RunStatus]] = []

    async def get_node_run(self, node_run_id: str) -> NodeRun | None:
        return self.node_run if node_run_id == self.node_run.node_run_id else None

    async def transition_node_run(self, node_run_id: str, status: RunStatus, **_: Any) -> NodeRun:
        self.transitions.append((node_run_id, status))
        return self.node_run.model_copy(update={"status": status})


def _attempt(node_run_id: str, *, awaits_human: bool) -> Attempt:
    return Attempt(
        node_run_id=node_run_id,
        ordinal=1,
        status=AttemptStatus.YIELDED,
        result={PAUSE_AWAITS_HUMAN: awaits_human},
        finished_at=FINISHED,
    )


class TestPauseGuards:
    """A pause must not re-park what is already parked, or park what never ran."""

    @pytest.mark.parametrize(
        "status", [RunStatus.WAITING, RunStatus.PAUSED, RunStatus.COMPLETED, RunStatus.FAILED]
    )
    async def test_an_already_settled_node_run_is_returned_untouched(
        self, status: RunStatus
    ) -> None:
        terminal = status not in {RunStatus.WAITING, RunStatus.PAUSED}
        node_run = NodeRun(
            run_id="r",
            node_id="n",
            ordinal=1,
            status=status,
            # The model refuses a terminal NodeRun with no finish time, so the
            # fixture has to be a state the store could really hold.
            finished_at=FINISHED if terminal else None,
        )
        store = _OneNodeRunStore(node_run)
        reconciler = AttemptLifecycleReconciler(store)  # type: ignore[arg-type]

        settled = await reconciler._pause_node_run(
            node_run, _attempt(node_run.node_run_id, awaits_human=True)
        )

        assert settled is node_run
        assert store.transitions == []

    async def test_a_node_run_that_never_ran_is_an_integrity_error(self) -> None:
        """CREATED means no physical try was ever prepared for it."""
        node_run = NodeRun(run_id="r", node_id="n", ordinal=1, status=RunStatus.CREATED)
        store = _OneNodeRunStore(node_run)
        reconciler = AttemptLifecycleReconciler(store)  # type: ignore[arg-type]

        with pytest.raises(RunIntegrityError, match="running logical NodeRun"):
            await reconciler._pause_node_run(
                node_run, _attempt(node_run.node_run_id, awaits_human=False)
            )
        assert store.transitions == []
