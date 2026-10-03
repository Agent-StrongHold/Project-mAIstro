"""Knowledge-stage ladder semantics (M4-B1 / ADR-103): rules and in-memory runs.

The ladder is MEMORY -> LEARNING -> VALIDATED -> REPERTOIRE on the one
``Learning`` record. These tests pin the transition rules themselves
(forward-only, single-step, actor-attributed, status flip on repertoire
commit) and the audit trail the in-memory store keeps, so the semantics the
SQL twins persist are the semantics a caller actually gets.
"""

from __future__ import annotations

import dataclasses

import pytest

from maistro.memory.learnings.lifecycle import (
    InvalidStageTransition,
    plan_advance,
)
from maistro.memory.learnings.store import InMemoryLearningStore
from maistro.types.memory import Learning, LearningStage

# The behavioral contract ADR-103 claims: the ladder's transition semantics
# (forward-only, single-step, actor-attributed, status flip on repertoire
# commit) are the contract, and this module is the evidence listed in the
# ADR's `tests:` front matter.
pytestmark = pytest.mark.contract("behavioral")

ORG = "org-a"


def make_learning(**overrides: object) -> Learning:
    defaults: dict[str, object] = {
        "tool_name": "bash",
        "trigger_keys": ["timeout"],
        "learning": "retry once on timeout",
        "org_id": ORG,
    }
    defaults.update(overrides)
    return Learning(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# plan_advance: the pure rule set both stores inherit
# ---------------------------------------------------------------------------


def test_a_fresh_learning_starts_at_memory() -> None:
    """Memory = remembered evidence/context; it is the bottom rung."""
    assert Learning().stage is LearningStage.MEMORY


def test_memory_to_learning_records_the_claim() -> None:
    updated, transition = plan_advance(
        make_learning(), to_stage=LearningStage.LEARNING, actor="planner"
    )
    assert updated.stage is LearningStage.LEARNING
    assert updated.validated_by == ""
    assert transition.from_stage is LearningStage.MEMORY
    assert transition.to_stage is LearningStage.LEARNING
    assert transition.actor == "planner"


def test_learning_to_validated_stamps_the_evaluator() -> None:
    claim = dataclasses.replace(make_learning(), stage=LearningStage.LEARNING)
    updated, transition = plan_advance(claim, to_stage=LearningStage.VALIDATED, actor="gauntlet-7")
    # Validated Learning = a claim that survived independent evaluation, and
    # the evaluation is attributed: blank would mean "nobody evaluated this".
    assert updated.stage is LearningStage.VALIDATED
    assert updated.validated_by == "gauntlet-7"
    assert transition.to_stage is LearningStage.VALIDATED


def test_validated_to_repertoire_flips_status_for_promoted_only_readers() -> None:
    validated = dataclasses.replace(
        make_learning(), stage=LearningStage.VALIDATED, validated_by="gauntlet-7"
    )
    updated, _ = plan_advance(validated, to_stage=LearningStage.REPERTOIRE, actor="curator")
    assert updated.stage is LearningStage.REPERTOIRE
    assert updated.promoted_by == "curator"
    # The one behavioural side effect: `get_promoted` and prompt injection
    # select on `status`, so a repertoire commit that did not flip it would
    # promote nothing.
    assert updated.status == "promoted"


def test_backward_transitions_are_rejected() -> None:
    """A demotion would rewrite history the ledger already recorded."""
    for to_stage in LearningStage:
        if to_stage is LearningStage.MEMORY:
            continue
        learning = dataclasses.replace(make_learning(), stage=to_stage)
        with pytest.raises(InvalidStageTransition, match="forward-only"):
            plan_advance(learning, to_stage=LearningStage.MEMORY, actor="x")


def test_skipping_a_rung_is_rejected() -> None:
    """VALIDATED without the LEARNING step would detach the claim from its evidence."""
    with pytest.raises(InvalidStageTransition, match="single-step"):
        plan_advance(make_learning(), to_stage=LearningStage.VALIDATED, actor="x")


def test_the_top_of_the_ladder_cannot_be_advanced() -> None:
    repertoire = dataclasses.replace(
        make_learning(), stage=LearningStage.REPERTOIRE, status="promoted"
    )
    with pytest.raises(InvalidStageTransition, match="top of the ladder"):
        plan_advance(repertoire, to_stage=LearningStage.REPERTOIRE, actor="x")


def test_an_anonymous_actor_is_rejected() -> None:
    """Provenance without an actor is not provenance."""
    with pytest.raises(InvalidStageTransition, match="actor"):
        plan_advance(make_learning(), to_stage=LearningStage.LEARNING, actor="   ")


def test_an_unknown_stage_value_is_rejected() -> None:
    with pytest.raises(InvalidStageTransition, match="unknown learning stage"):
        plan_advance(make_learning(), to_stage="enlightened", actor="x")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# InMemoryLearningStore: the ladder on the dev/test backend
# ---------------------------------------------------------------------------


@pytest.fixture
async def store() -> InMemoryLearningStore:
    return InMemoryLearningStore()


@pytest.mark.asyncio
async def test_the_full_ladder_runs_one_rung_at_a_time(
    store: InMemoryLearningStore,
) -> None:
    lid = await store.store(make_learning())
    for to_stage, actor in (
        (LearningStage.LEARNING, "planner"),
        (LearningStage.VALIDATED, "gauntlet-7"),
        (LearningStage.REPERTOIRE, "curator"),
    ):
        learning = await store.advance_stage(lid, to_stage=to_stage, actor=actor, org_id=ORG)
        assert learning.stage is to_stage
    assert learning.status == "promoted"
    assert (await store.get_promoted(org_id=ORG))[0].id == lid


@pytest.mark.asyncio
async def test_every_transition_is_recorded_in_order(
    store: InMemoryLearningStore,
) -> None:
    lid = await store.store(make_learning())
    await store.advance_stage(lid, to_stage=LearningStage.LEARNING, actor="planner", org_id=ORG)
    await store.advance_stage(lid, to_stage=LearningStage.VALIDATED, actor="gauntlet", org_id=ORG)

    history = await store.stage_history(lid, org_id=ORG)
    assert [(t.from_stage, t.to_stage, t.actor) for t in history] == [
        (LearningStage.MEMORY, LearningStage.LEARNING, "planner"),
        (LearningStage.LEARNING, LearningStage.VALIDATED, "gauntlet"),
    ]
    # A learning nobody advanced has an empty trail, not a fabricated one.
    lid2 = await store.store(make_learning(trigger_keys=["other"]))
    assert await store.stage_history(lid2, org_id=ORG) == []


@pytest.mark.asyncio
async def test_an_illegal_transition_is_rejected_without_a_ledger_row(
    store: InMemoryLearningStore,
) -> None:
    """A transition that did not happen must not appear in the audit trail."""
    lid = await store.store(make_learning())
    with pytest.raises(InvalidStageTransition):
        await store.advance_stage(lid, to_stage=LearningStage.REPERTOIRE, actor="x", org_id=ORG)
    learning = (await store.list_all(org_id=ORG))[0]
    assert learning.stage is LearningStage.MEMORY
    assert await store.stage_history(lid, org_id=ORG) == []


@pytest.mark.asyncio
async def test_another_org_cannot_advance_or_read_a_learning(
    store: InMemoryLearningStore,
) -> None:
    """Stage moves are scope-bound writes, like every other learning write."""
    lid = await store.store(make_learning())
    with pytest.raises(KeyError):
        await store.advance_stage(lid, to_stage=LearningStage.LEARNING, actor="x", org_id="org-b")
    with pytest.raises(KeyError):
        await store.stage_history(lid, org_id="org-b")
