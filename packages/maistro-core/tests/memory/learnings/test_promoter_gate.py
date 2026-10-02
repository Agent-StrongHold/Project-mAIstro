"""Tests for gate-based learning promotion (LearningPromoter + approval gate).

Pins the behavior that, with an approval gate configured, eligible learnings
are enumerated and queued into pending_approval — and that approved learnings
are subsequently promoted. Regression guard for the find_relevant("") bug,
where an empty query scored 0 for every learning so the candidate list was
always empty and nothing ever reached pending_approval.
"""

from __future__ import annotations

import pytest

from maistro.memory.learnings.approval import LearningApprovalGate
from maistro.memory.learnings.promoter import LearningPromoter
from maistro.memory.learnings.store import InMemoryLearningStore
from maistro.memory.types import Learning


@pytest.mark.asyncio
async def test_gate_queues_eligible_learning_for_approval() -> None:
    """A learning at/over threshold must enter pending_approval via the gate.

    With the find_relevant("") bug present, candidates is always empty so no
    approval request is ever created — this asserts otherwise.
    """
    store = InMemoryLearningStore()
    learning = Learning(
        trigger_keys=["deploy", "rollback"],
        learning="Always snapshot before deploy",
        hit_count=7,
        status="active",
        run_id="run-1",
        confidence=1.0,
    )
    await store.store(learning)

    gate = LearningApprovalGate()
    promoter = LearningPromoter(store, threshold=5, approval_gate=gate)

    promoted = await promoter.check_and_promote()

    # Nothing is approved yet, so nothing is promoted on this pass.
    assert promoted == []
    pending = gate.get_pending()
    assert len(pending) == 1
    assert pending[0].learning_id == learning.id
    assert pending[0].hit_count == 7


@pytest.mark.asyncio
async def test_below_threshold_learning_not_queued() -> None:
    """A learning under threshold must NOT be queued for approval."""
    store = InMemoryLearningStore()
    await store.store(
        Learning(trigger_keys=["x"], learning="too fresh", hit_count=2, status="active")
    )

    gate = LearningApprovalGate()
    promoter = LearningPromoter(store, threshold=5, approval_gate=gate)

    await promoter.check_and_promote()

    assert gate.get_pending() == []


@pytest.mark.asyncio
async def test_approved_learning_gets_promoted_on_next_pass() -> None:
    """Once an admin approves, the next check promotes the learning."""
    store = InMemoryLearningStore()
    learning = Learning(
        trigger_keys=["deploy"],
        learning="snapshot first",
        hit_count=10,
        status="active",
        run_id="run-1",
        confidence=1.0,
    )
    lid = await store.store(learning)

    gate = LearningApprovalGate()
    promoter = LearningPromoter(store, threshold=5, approval_gate=gate)

    # First pass: queue it.
    await promoter.check_and_promote()
    assert len(gate.get_pending()) == 1

    # Admin approves.
    gate.approve(lid, reviewer="admin")

    # Second pass: it gets promoted.
    promoted = await promoter.check_and_promote()
    assert [p.id for p in promoted] == [lid]
    assert gate.get_approved_ids() == []  # moved to 'promoted' state


@pytest.mark.asyncio
async def test_stale_approval_not_promoted_after_confidence_drops() -> None:
    """An approval must not bypass the evidence rule at consumption time.

    Outcomes recorded while a request sat pending can sink measured confidence
    below the promotion floor; the approved-processing pass re-runs the
    candidate rule, so the stale approval is not promoted or mutated.
    """
    store = InMemoryLearningStore()
    learning = Learning(
        trigger_keys=["deploy"],
        learning="snapshot first",
        hit_count=10,
        status="active",
        run_id="run-1",
        confidence=1.0,
    )
    lid = await store.store(learning)

    gate = LearningApprovalGate()
    promoter = LearningPromoter(store, threshold=5, approval_gate=gate)

    # First pass: queue it; admin approves while the evidence still passes.
    await promoter.check_and_promote()
    gate.approve(lid, reviewer="admin")

    # While pending, real outcomes measure the claim as unreliable.
    await store.mark_outcome([lid], success=False)
    await store.mark_outcome([lid], success=False)
    await store.mark_outcome([lid], success=True)
    assert (await store.list_all())[0].confidence < promoter._min_confidence

    # Second pass: the approval exists, but promotion must not fire.
    promoted = await promoter.check_and_promote()
    assert promoted == []
    assert gate.get_approved_ids() == [lid]  # still approved, just not consumable


@pytest.mark.asyncio
async def test_org_scoped_candidates_only() -> None:
    """Gate enumeration respects org scoping when an org_id is supplied."""
    store = InMemoryLearningStore()
    await store.store(
        Learning(
            trigger_keys=["a"],
            learning="org-a",
            hit_count=9,
            org_id="org-a",
            run_id="run-a",
            confidence=1.0,
        )
    )
    await store.store(
        Learning(
            trigger_keys=["b"],
            learning="org-b",
            hit_count=9,
            org_id="org-b",
            run_id="run-b",
            confidence=1.0,
        )
    )

    gate = LearningApprovalGate()
    promoter = LearningPromoter(store, threshold=5, approval_gate=gate)

    await promoter.check_and_promote(org_id="org-a")

    pending = gate.get_pending()
    assert len(pending) == 1
    assert pending[0].org_id == "org-a"
