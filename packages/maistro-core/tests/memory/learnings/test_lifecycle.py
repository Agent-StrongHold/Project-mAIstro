"""Learning pipeline lifecycle semantics (ADR-092, EPIC M4-B #117/#120).

Covers the Memory -> Learning -> Validated -> Repertoire stage ladder, the
reinforce/contradict/decay dynamics, supersession, consolidation, and the
measured-effect read. The store-side application of these rules is covered in
test_learning_lifecycle_store.py; the Gauntlet that authorizes VALIDATED in
test_gauntlet.py.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from maistro.memory.learnings.lifecycle import (
    absorb,
    advance_stage,
    commit_to_repertoire,
    contradict,
    decay,
    effectiveness,
    reinforce,
    supersede,
    trigger_key_overlap,
)
from maistro.types.memory import (
    ANTI_PATTERN_CONFIDENCE_FLOOR,
    DEFAULT_LEARNING_CONFIDENCE,
    VALIDATED_CONFIDENCE_FLOOR,
    EpistemicType,
    Learning,
    LearningStage,
)

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _lr(**overrides: object) -> Learning:
    kwargs: dict[str, object] = {
        "trigger_keys": ["deploy"],
        "learning": "snapshot before deploying",
    }
    kwargs.update(overrides)
    return Learning(**kwargs)  # type: ignore[arg-type]


class TestStageLadder:
    def test_fresh_learning_starts_local_and_empirical(self) -> None:
        lr = _lr()
        assert lr.stage is LearningStage.LEARNING
        assert lr.epistemic_type is EpistemicType.EMPIRICAL
        assert lr.confidence == DEFAULT_LEARNING_CONFIDENCE

    def test_memory_is_source_tier_never_a_destination(self) -> None:
        lr = _lr()
        with pytest.raises(ValueError, match="source tier"):
            advance_stage(lr, LearningStage.MEMORY)

    def test_stage_moves_forward_only(self) -> None:
        lr = _lr()
        advance_stage(lr, LearningStage.VALIDATED, gauntlet_name="g")
        with pytest.raises(ValueError, match="forward"):
            advance_stage(lr, LearningStage.LEARNING)

    def test_stage_cannot_skip_validation(self) -> None:
        lr = _lr()
        with pytest.raises(ValueError, match="skip"):
            commit_to_repertoire(lr)

    def test_validation_records_gauntlet_provenance(self) -> None:
        lr = _lr()
        advance_stage(lr, LearningStage.VALIDATED, gauntlet_name="outcome-evidence", now=NOW)
        assert lr.stage is LearningStage.VALIDATED
        assert lr.validated_by == "outcome-evidence"
        assert lr.validated_at == NOW
        # A validated learning cannot sit below the validation floor: the
        # Gauntlet accepted its evidence.
        assert lr.confidence >= VALIDATED_CONFIDENCE_FLOOR
        # Still a local row: only the repertoire commit promotes it.
        assert lr.status == "active"

    def test_validation_lifts_low_confidence_to_floor(self) -> None:
        lr = _lr(confidence=0.1)
        advance_stage(lr, LearningStage.VALIDATED, gauntlet_name="g")
        assert lr.confidence == VALIDATED_CONFIDENCE_FLOOR

    def test_repertoire_commit_flips_status_to_promoted(self) -> None:
        lr = _lr()
        advance_stage(lr, LearningStage.VALIDATED, gauntlet_name="g")
        commit_to_repertoire(lr, now=NOW)
        assert lr.stage is LearningStage.REPERTOIRE
        # promoted-only readers (get_promoted) must see repertoire entries.
        assert lr.status == "promoted"


class TestReinforceContradict:
    def test_reinforce_counts_and_lifts_confidence(self) -> None:
        lr = _lr()
        reinforce(lr, now=NOW)
        assert lr.reinforcement_count == 1
        assert lr.confidence == pytest.approx(DEFAULT_LEARNING_CONFIDENCE + 0.05)
        assert lr.last_confirmed_at == NOW

    def test_reinforce_caps_at_one(self) -> None:
        lr = _lr(confidence=0.999)
        reinforce(lr)
        assert lr.confidence == 1.0

    def test_contradict_counts_and_lowers_confidence(self) -> None:
        lr = _lr()
        contradict(lr)
        assert lr.contradiction_count == 1
        assert lr.confidence == pytest.approx(DEFAULT_LEARNING_CONFIDENCE - 0.05)

    def test_contradiction_of_anti_pattern_stops_at_floor(self) -> None:
        # Failure knowledge is structurally unforgettable: contradicting an
        # anti-pattern lowers confidence to the floor, never through it.
        lr = _lr(epistemic_type=EpistemicType.ANTI_PATTERN, confidence=0.65)
        contradict(lr, delta=0.3)
        assert lr.confidence == ANTI_PATTERN_CONFIDENCE_FLOOR
        assert lr.contradiction_count == 1


class TestDecay:
    def test_decay_anchors_at_last_confirmation(self) -> None:
        lr = _lr(created_at=NOW - timedelta(days=100))
        reinforce(lr, now=NOW - timedelta(days=1))
        decay(lr, now=NOW)
        # One day past the last confirmation, not 100 past creation: at a
        # 30-day half-life one day costs ~2.3%, not the bulk of the weight.
        assert lr.confidence == pytest.approx(0.55 * 0.5 ** (1 / 30))

    def test_empirical_decay_half_life(self) -> None:
        lr = _lr(created_at=NOW)
        decay(lr, now=NOW + timedelta(days=30))
        assert lr.confidence == pytest.approx(0.25)

    def test_decay_toward_floor_never_through_it(self) -> None:
        lr = _lr(epistemic_type=EpistemicType.ANTI_PATTERN, confidence=0.9, created_at=NOW)
        decay(lr, now=NOW + timedelta(days=10_000))
        # Approaches the floor asymptotically; float64 arrives there.
        assert lr.confidence >= ANTI_PATTERN_CONFIDENCE_FLOOR
        assert lr.confidence == pytest.approx(ANTI_PATTERN_CONFIDENCE_FLOOR, abs=1e-9)

    def test_anti_pattern_decays_on_the_slow_clock(self) -> None:
        fast = _lr(confidence=0.8, created_at=NOW)
        slow = _lr(epistemic_type=EpistemicType.ANTI_PATTERN, confidence=0.8, created_at=NOW)
        moment = NOW + timedelta(days=30)
        decay(fast, now=moment)
        decay(slow, now=moment)
        assert slow.confidence > fast.confidence

    def test_future_or_present_timestamp_is_a_noop(self) -> None:
        lr = _lr(confidence=0.5, created_at=NOW)
        decay(lr, now=NOW)
        assert lr.confidence == 0.5


class TestSupersession:
    def test_supersede_links_both_rows_and_retires_old(self) -> None:
        old = _lr()
        old.id = 7
        new = _lr(learning="snapshot AND verify before deploying")
        new.id = 8
        supersede(old, new)
        assert new.supersedes == 7
        assert old.superseded_by == 8
        assert old.status == "superseded"
        assert new.status == "active"

    def test_supersede_needs_stored_rows(self) -> None:
        old = _lr()
        old.id = None
        new = _lr()
        new.id = 8
        with pytest.raises(ValueError, match="stored"):
            supersede(old, new)


class TestConsolidation:
    def test_absorb_folds_evidence_into_survivor(self) -> None:
        survivor = _lr(
            trigger_keys=["deploy", "prod"],
            hit_count=2,
            success_after_use=3,
            failure_after_use=1,
            reinforcement_count=4,
            contradiction_count=1,
            confidence=0.7,
        )
        absorbed = _lr(
            trigger_keys=["prod", "rollback"],
            hit_count=5,
            success_after_use=2,
            failure_after_use=2,
            reinforcement_count=1,
            contradiction_count=0,
            confidence=0.9,
        )
        survivor.id = 1
        absorbed.id = 2
        absorb(survivor, absorbed)
        assert survivor.trigger_keys == ["deploy", "prod", "rollback"]
        assert survivor.hit_count == 7
        assert survivor.success_after_use == 5
        assert survivor.failure_after_use == 3
        assert survivor.reinforcement_count == 5
        assert survivor.contradiction_count == 1
        assert survivor.confidence == 0.9
        assert absorbed.status == "consolidated"
        assert absorbed.superseded_by == 1


class TestMeasuredEffect:
    def test_effectiveness_none_when_unused(self) -> None:
        # Zero uses is "no measurement", not "no effect".
        assert effectiveness(_lr()) is None

    def test_effectiveness_signed_ratio(self) -> None:
        assert effectiveness(_lr(success_after_use=4, failure_after_use=1)) == pytest.approx(0.6)
        assert effectiveness(_lr(success_after_use=0, failure_after_use=3)) == pytest.approx(-1.0)
        assert effectiveness(_lr(success_after_use=2, failure_after_use=2)) == 0.0


class TestTriggerKeyOverlap:
    def test_jaccard_overlap(self) -> None:
        assert trigger_key_overlap(["a", "b"], ["a", "b"]) == 1.0
        assert trigger_key_overlap(["a", "b"], ["c", "d"]) == 0.0
        assert trigger_key_overlap(["a", "b"], ["b", "c"]) == pytest.approx(1 / 3)

    def test_empty_keys_overlap_zero(self) -> None:
        assert trigger_key_overlap([], ["a"]) == 0.0
        assert trigger_key_overlap([], []) == 0.0
