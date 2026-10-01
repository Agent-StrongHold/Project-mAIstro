"""Independent Gauntlet validation before collective promotion (M4-B #118),
anti-pattern capture (#121), and the promoter integration of both.

Key property under test: the Gauntlet judges *recorded outcome evidence of
later Runs*, never the producer's enthusiasm and never hit_count -- a learning
recalled constantly and followed by failures must fail, which is exactly the
case hit-count promotion alone waves through.
"""

from __future__ import annotations

from typing import Any

from maistro.memory.learnings.gauntlet import (
    ChainedGauntlet,
    OutcomeEvidenceGauntlet,
    evidence_of,
)
from maistro.memory.learnings.promoter import LearningPromoter
from maistro.memory.learnings.store import InMemoryLearningStore
from maistro.memory.types import Learning
from maistro.types.memory import (
    ANTI_PATTERN_CONFIDENCE_FLOOR,
    EpistemicType,
    LearningStage,
)


class _StubForge:
    def __init__(self, result: dict[str, Any]) -> None:
        self._result = result
        self.calls: list[tuple[str, Learning]] = []

    async def mutate(self, skill_name: str, learning: Learning) -> dict[str, Any]:
        self.calls.append((skill_name, learning))
        return self._result


def _used_learning(**overrides: object) -> Learning:
    """A learning with good evidence: 4 successes out of 5 recorded outcomes."""
    kwargs: dict[str, object] = {
        "trigger_keys": ["deploy"],
        "learning": "snapshot first",
        "run_id": "run-1",
        "success_after_use": 4,
        "failure_after_use": 1,
    }
    kwargs.update(overrides)
    return Learning(**kwargs)  # type: ignore[arg-type]


class TestEvidenceProjection:
    def test_evidence_counts_uses_not_hits(self) -> None:
        # hit_count is deliberately absent from the projection: recall
        # frequency says nothing about whether following the learning helped.
        lr = _used_learning(hit_count=999)
        ev = evidence_of(lr)
        assert ev.uses == 5
        assert ev.successes == 4
        assert ev.failures == 1
        assert ev.producer_run_id == "run-1"

    def test_unattributed_learning_names_no_producer(self) -> None:
        assert evidence_of(_used_learning(run_id="")).producer_run_id == ""


class TestOutcomeEvidenceGauntlet:
    async def test_good_evidence_passes(self) -> None:
        lr = _used_learning()
        verdict = await OutcomeEvidenceGauntlet().evaluate(lr, evidence=evidence_of(lr))
        assert verdict.ok
        assert verdict.gauntlet == "outcome-evidence"

    async def test_insufficient_uses_fail(self) -> None:
        lr = _used_learning(success_after_use=2, failure_after_use=0)
        verdict = await OutcomeEvidenceGauntlet().evaluate(lr, evidence=evidence_of(lr))
        assert not verdict.ok
        assert "min_uses" in verdict.failed_checks

    async def test_high_hits_with_failing_outcomes_fail(self) -> None:
        # The case hit-count promotion alone would wave through.
        lr = _used_learning(hit_count=50, success_after_use=1, failure_after_use=4)
        verdict = await OutcomeEvidenceGauntlet().evaluate(lr, evidence=evidence_of(lr))
        assert not verdict.ok
        assert "success_rate" in verdict.failed_checks

    async def test_contradictions_outweighing_reinforcements_fail(self) -> None:
        lr = _used_learning(contradiction_count=3, reinforcement_count=0)
        verdict = await OutcomeEvidenceGauntlet().evaluate(lr, evidence=evidence_of(lr))
        assert not verdict.ok
        assert "contradictions" in verdict.failed_checks

    async def test_decayed_confidence_fails(self) -> None:
        lr = _used_learning(confidence=0.1)
        verdict = await OutcomeEvidenceGauntlet().evaluate(lr, evidence=evidence_of(lr))
        assert not verdict.ok
        assert "confidence" in verdict.failed_checks

    async def test_unattributed_producer_fails(self) -> None:
        # Nothing can be checked against an execution that is not named.
        lr = _used_learning(run_id="")
        verdict = await OutcomeEvidenceGauntlet().evaluate(lr, evidence=evidence_of(lr))
        assert not verdict.ok
        assert "producer" in verdict.failed_checks

    async def test_producer_requirement_can_be_relaxed(self) -> None:
        lr = _used_learning(run_id="")
        gauntlet = OutcomeEvidenceGauntlet(require_producer=False)
        verdict = await gauntlet.evaluate(lr, evidence=evidence_of(lr))
        assert verdict.ok


class TestChainedGauntlet:
    async def test_all_members_must_pass(self) -> None:
        lr = _used_learning()
        strict = OutcomeEvidenceGauntlet(name="strict", min_uses=10)
        chain = ChainedGauntlet(OutcomeEvidenceGauntlet(), strict)
        verdict = await chain.evaluate(lr, evidence=evidence_of(lr))
        assert not verdict.ok
        assert "strict" in verdict.reason

    async def test_passing_chain_reports_member_names(self) -> None:
        lr = _used_learning()
        chain = ChainedGauntlet(
            OutcomeEvidenceGauntlet(name="g1"),
            OutcomeEvidenceGauntlet(name="g2", min_uses=5),
        )
        verdict = await chain.evaluate(lr, evidence=evidence_of(lr))
        assert verdict.ok
        assert verdict.gauntlet == "gauntlet-chain"

    def test_empty_chain_is_a_configuration_error(self) -> None:
        try:
            ChainedGauntlet()
        except ValueError as exc:
            assert "member" in str(exc)
        else:
            raise AssertionError("empty chain must raise")


class TestPromoterWithGauntlet:
    async def test_validated_learning_joins_repertoire(self) -> None:
        store = InMemoryLearningStore()
        lr = _used_learning(hit_count=10)
        await store.store(lr)

        promoter = LearningPromoter(store, threshold=5, gauntlet=OutcomeEvidenceGauntlet())
        promoted = await promoter.check_and_promote()

        assert [p.id for p in promoted] == [lr.id]
        assert lr.stage is LearningStage.REPERTOIRE
        assert lr.status == "promoted"
        assert lr.validated_by == "outcome-evidence"
        assert lr.validated_at is not None
        # promoted-only readers see repertoire entries.
        assert [p.id for p in await store.get_promoted()] == [lr.id]

    async def test_rejected_learning_stays_local_and_active(self) -> None:
        store = InMemoryLearningStore()
        lr = _used_learning(hit_count=10, success_after_use=0, failure_after_use=1)
        await store.store(lr)

        promoter = LearningPromoter(store, threshold=5, gauntlet=OutcomeEvidenceGauntlet())
        promoted = await promoter.check_and_promote()

        assert promoted == []
        assert lr.stage is LearningStage.LEARNING
        assert lr.status == "active"
        assert lr.validated_by == ""
        assert await store.get_promoted() == []

    async def test_below_threshold_candidate_is_never_judged(self) -> None:
        store = InMemoryLearningStore()
        lr = _used_learning(hit_count=2)
        await store.store(lr)

        promoter = LearningPromoter(store, threshold=5, gauntlet=OutcomeEvidenceGauntlet())
        assert await promoter.check_and_promote() == []
        assert lr.stage is LearningStage.LEARNING

    async def test_gauntlet_gates_skill_mutation(self) -> None:
        store = InMemoryLearningStore()
        good = _used_learning(hit_count=10, tool_name="shell")
        bad = _used_learning(
            trigger_keys=["deploy", "verify"],
            learning="the other one",
            hit_count=10,
            tool_name="shell2",
            success_after_use=0,
            failure_after_use=5,
        )
        await store.store(good)
        await store.store(bad)

        forge = _StubForge({"status": "mutated", "old_hash": "a", "new_hash": "b"})
        promoter = LearningPromoter(
            store,
            threshold=5,
            skill_forge=forge,
            gauntlet=OutcomeEvidenceGauntlet(),
        )
        promoted = await promoter.check_and_promote()

        assert [p.id for p in promoted] == [good.id]
        assert [name for name, _ in forge.calls] == ["shell"]

    async def test_gauntlet_takes_precedence_over_approval_gate(self) -> None:
        # With a Gauntlet wired, a learning never waits in a human queue: the
        # machine validation decides, and the legacy gate path is not entered.
        from maistro.memory.learnings.approval import LearningApprovalGate

        store = InMemoryLearningStore()
        lr = _used_learning(hit_count=10)
        await store.store(lr)

        promoter = LearningPromoter(
            store,
            threshold=5,
            approval_gate=LearningApprovalGate(),
            gauntlet=OutcomeEvidenceGauntlet(),
        )
        promoted = await promoter.check_and_promote()
        assert [p.id for p in promoted] == [lr.id]
        assert lr.status == "promoted"

    async def test_anti_pattern_failure_knowledge_is_promotable(self) -> None:
        # #121: failure knowledge follows the same validated road to the
        # repertoire as any other learning -- no separate door, none barred.
        store = InMemoryLearningStore()
        lr = _used_learning(
            epistemic_type=EpistemicType.ANTI_PATTERN,
            learning="never force-push to main",
            hit_count=10,
            success_after_use=5,
            failure_after_use=0,
            confidence=ANTI_PATTERN_CONFIDENCE_FLOOR,
        )
        await store.store(lr)

        promoter = LearningPromoter(store, threshold=5, gauntlet=OutcomeEvidenceGauntlet())
        promoted = await promoter.check_and_promote()
        assert [p.id for p in promoted] == [lr.id]
        assert lr.stage is LearningStage.REPERTOIRE
        assert lr.epistemic_type is EpistemicType.ANTI_PATTERN

    async def test_legacy_path_unchanged_without_gauntlet(self) -> None:
        store = InMemoryLearningStore()
        lr = _used_learning(hit_count=10, run_id="")
        await store.store(lr)

        promoter = LearningPromoter(store, threshold=5)
        promoted = await promoter.check_and_promote()
        assert [p.id for p in promoted] == [lr.id]
        assert lr.status == "promoted"


class TestCaptureAntiPatterns:
    async def test_ineffective_learnings_become_anti_patterns(self) -> None:
        store = InMemoryLearningStore()
        lr = _used_learning(success_after_use=0, failure_after_use=4)
        await store.store(lr)

        promoter = LearningPromoter(store)
        captured = await promoter.capture_anti_patterns(min_uses=3)

        assert [c.id for c in captured] == [lr.id]
        assert lr.epistemic_type is EpistemicType.ANTI_PATTERN
        # Retained near-permanently: confidence lifted to the floor.
        assert lr.confidence == ANTI_PATTERN_CONFIDENCE_FLOOR
        # Reclassification is not validation: still local, still promotable.
        assert lr.status == "active"
        assert lr.stage is LearningStage.LEARNING

    async def test_effective_and_unmeasured_learnings_are_left_alone(self) -> None:
        store = InMemoryLearningStore()
        effective = _used_learning()  # 4/5 successes
        unmeasured = _used_learning(trigger_keys=["fresh"], learning="no outcomes yet")
        await store.store(effective)
        await store.store(unmeasured)

        captured = await LearningPromoter(store).capture_anti_patterns(min_uses=3)
        assert captured == []
        assert effective.epistemic_type is EpistemicType.EMPIRICAL
        assert unmeasured.epistemic_type is EpistemicType.EMPIRICAL

    async def test_org_scoping_and_double_capture(self) -> None:
        store = InMemoryLearningStore()
        org1 = _used_learning(org_id="org-1", success_after_use=0, failure_after_use=4)
        org2 = _used_learning(org_id="org-2", success_after_use=0, failure_after_use=4)
        await store.store(org1)
        await store.store(org2)

        promoter = LearningPromoter(store)
        captured = await promoter.capture_anti_patterns("org-1", min_uses=3)
        assert [c.id for c in captured] == [org1.id]
        assert org2.epistemic_type is EpistemicType.EMPIRICAL

        # Already-captured rows are not reprocessed.
        assert await promoter.capture_anti_patterns("org-1", min_uses=3) == []

    async def test_store_without_ineffective_read_yields_nothing(self) -> None:
        class NoIneffectiveStore:
            async def list_all(self, org_id: str = "", limit: int = 200) -> list[Learning]:
                return []

        promoter = LearningPromoter(NoIneffectiveStore())  # type: ignore[arg-type]
        assert await promoter.capture_anti_patterns() == []

    async def test_captured_anti_pattern_can_then_be_validated(self) -> None:
        # The full #121 path: a captured anti-pattern with good later-Run
        # evidence joins the repertoire through the same Gauntlet.
        store = InMemoryLearningStore()
        lr = _used_learning(
            run_id="",
            success_after_use=0,
            failure_after_use=4,
        )
        await store.store(lr)
        promoter = LearningPromoter(store, gauntlet=OutcomeEvidenceGauntlet())

        await promoter.capture_anti_patterns(min_uses=3)
        assert lr.epistemic_type is EpistemicType.ANTI_PATTERN

        # Later Runs avoid the anti-pattern and succeed.
        lr.run_id = "run-42"
        lr.success_after_use = 4
        lr.failure_after_use = 0
        lr.hit_count = 10
        promoted = await promoter.check_and_promote()
        assert [p.id for p in promoted] == [lr.id]
        assert lr.stage is LearningStage.REPERTOIRE
