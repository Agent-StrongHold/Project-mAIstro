"""Promotion evidence rules (M4-B3): no learning promotes on popularity alone.

Covers `evidence.promotion_blockers` — the one verdict shared by the promoter,
the approval gate and both SQL twins — plus the end-to-end rule through
`InMemoryLearningStore.check_auto_promotions` and the RCA extractor: an
LLM-distilled claim lands INFERRED and cannot promote until a real Run or
evaluation backs it. Distillation may shape the wording; it is never the
warrant.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.memory.learnings.evidence import (
    DEFAULT_MIN_PROMOTION_CONFIDENCE,
    has_source_evidence,
    outcome_confidence,
    promotion_blockers,
)
from maistro.memory.exposure import MemoryExposureMode
from maistro.memory.learnings.extractor import RCAExtractor
from maistro.memory.learnings.promoter import LearningPromoter
from maistro.memory.learnings.store import InMemoryLearningStore
from maistro.types.memory import EpistemicType, Learning

# The whole module pins the promotion boundary verdict ADR-100126-5445
# declares: no learning crosses from `active` to `promoted` without evidence.
pytestmark = [pytest.mark.contract("boundary")]


def _evidenced(**overrides: Any) -> Learning:
    """A learning carrying the minimum promotable evidence set."""
    base: dict[str, Any] = {
        "trigger_keys": ["deploy"],
        "learning": "snapshot before deploy",
        "run_id": "run-1",
        "confidence": 0.9,
        "hit_count": 5,
    }
    base.update(overrides)
    return Learning(**base)


class TestPromotionBlockers:
    @pytest.mark.ac("SPEC-100126-5445/AC-3")
    def test_fully_evidenced_learning_has_no_blockers(self) -> None:
        assert promotion_blockers(_evidenced()) == []

    @pytest.mark.ac("SPEC-100126-5445/AC-3")
    def test_no_source_evidence_blocks_even_when_confident(self) -> None:
        """A claimed confidence with no Run/evaluation behind it is not evidence."""
        blockers = promotion_blockers(_evidenced(run_id="", confidence=1.0))
        assert blockers == ["no_source_run_or_evaluation_ids"]

    @pytest.mark.ac("SPEC-100126-5445/AC-3")
    def test_producer_run_id_counts_as_source_evidence(self) -> None:
        assert has_source_evidence(_evidenced(evidence_run_ids=[], evaluation_ids=[]))
        assert not has_source_evidence(_evidenced(run_id="", confidence=0.9))

    @pytest.mark.ac("SPEC-100126-5445/AC-3")
    def test_unmeasured_confidence_blocks(self) -> None:
        """None means never measured — a blocker, not a pass (ADR-083026-a91e)."""
        assert promotion_blockers(_evidenced(confidence=None)) == ["confidence_unmeasured"]

    @pytest.mark.ac("SPEC-100126-5445/AC-3")
    def test_confidence_below_floor_blocks(self) -> None:
        blockers = promotion_blockers(_evidenced(confidence=0.2))
        assert blockers == ["confidence_below_threshold"]

    @pytest.mark.ac("SPEC-100126-5445/AC-3")
    def test_tied_evidence_at_floor_blocks(self) -> None:
        """1 success / 1 failure is a tie, not a strict majority — it may not promote."""
        blockers = promotion_blockers(_evidenced(confidence=0.5))
        assert blockers == ["confidence_below_threshold"]

    @pytest.mark.ac("SPEC-100126-5445/AC-3")
    def test_min_confidence_is_configurable(self) -> None:
        assert promotion_blockers(_evidenced(confidence=0.7), min_confidence=0.8) == [
            "confidence_below_threshold"
        ]

    @pytest.mark.ac("SPEC-100126-5445/AC-4")
    def test_counterfactual_requires_an_evaluation(self) -> None:
        """Only an evaluation can test what *would have* happened."""
        cf = _evidenced(epistemic_type=EpistemicType.COUNTERFACTUAL)
        assert "counterfactual_without_evaluation" in promotion_blockers(cf)
        validated = _evidenced(
            epistemic_type=EpistemicType.COUNTERFACTUAL, evaluation_ids=["eval-9"]
        )
        assert promotion_blockers(validated) == []

    @pytest.mark.ac("SPEC-100126-5445/AC-4")
    def test_inferred_needs_only_ordinary_evidence(self) -> None:
        inferred = _evidenced(
            epistemic_type=EpistemicType.INFERRED,
            run_id="",
            evaluation_ids=["eval-3"],
            evidence_run_ids=[],
        )
        assert promotion_blockers(inferred) == []

    def test_default_floor_is_strict_majority(self) -> None:
        assert DEFAULT_MIN_PROMOTION_CONFIDENCE == 0.5


class TestOutcomeConfidence:
    @pytest.mark.ac("SPEC-100126-5445/AC-3")
    def test_no_outcomes_is_unmeasured(self) -> None:
        assert outcome_confidence(0, 0) is None

    @pytest.mark.ac("SPEC-100126-5445/AC-3")
    def test_ratio_of_successes(self) -> None:
        assert outcome_confidence(3, 1) == pytest.approx(0.75)


class TestDistillationIsNotEvidence:
    @pytest.mark.ac("SPEC-100126-5445/AC-5")
    async def test_rca_learning_is_inferred_and_cannot_self_promote(self) -> None:
        """The LLM wrote the diagnosis; hits do not turn it into evidence."""
        llm = _FakeLLM("CATEGORY: rate_limit\nROOT CAUSE: cap\nPREVENTION: back off")
        extractor = RCAExtractor(llm_client=llm, rca_model="fast")
        learning = await extractor.extract_rca(
            "call the api", [{"tool_name": "api", "arguments": {}, "result": "Error: 429"}]
        )
        assert learning is not None
        # Reconciled member name (ADR-100126-8c2d): an RCA diagnosis is
        # INFERENTIAL — the same distillation-is-not-evidence reading as
        # M4-B3's INFERRED, named for its RCA source.
        assert learning.epistemic_type == EpistemicType.INFERENTIAL

        store = InMemoryLearningStore(exposure_mode=MemoryExposureMode.AGENT_MANAGED)
        await store.store(learning)
        for _ in range(10):
            await store.mark_used([learning.id])
        assert await store.check_auto_promotions(threshold=5) == []
        # Still active, and the blocker is the missing evidence, not the hits.
        stored = (await store.list_all())[0]
        assert stored.status == "active"
        assert "no_source_run_or_evaluation_ids" in promotion_blockers(stored)

    @pytest.mark.ac("SPEC-100126-5445/AC-5")
    async def test_inferred_learning_promotes_once_a_run_backs_it(self) -> None:
        """The same distilled claim, once measured: wording from the LLM,
        warrant from the outcome counters."""
        llm = _FakeLLM("CATEGORY: rate_limit\nROOT CAUSE: cap\nPREVENTION: back off")
        extractor = RCAExtractor(llm_client=llm, rca_model="fast")
        learning = await extractor.extract_rca(
            "call the api", [{"tool_name": "api", "arguments": {}, "result": "Error: 429"}]
        )
        assert learning is not None
        learning.run_id = "run-7"
        store = InMemoryLearningStore(exposure_mode=MemoryExposureMode.AGENT_MANAGED)
        await store.store(learning)
        await store.mark_used([learning.id])
        await store.mark_outcome([learning.id], success=True)
        promoted = await store.check_auto_promotions(threshold=1)
        assert [lr.id for lr in promoted] == [learning.id]
        assert learning.confidence == 1.0


class TestStoreGate:
    @pytest.mark.ac("SPEC-100126-5445/AC-3")
    async def test_hits_alone_do_not_promote(self) -> None:
        store = InMemoryLearningStore(exposure_mode=MemoryExposureMode.AGENT_MANAGED)
        bare = _evidenced(run_id="", confidence=None)
        await store.store(bare)
        for _ in range(6):
            await store.mark_used([bare.id])
        assert await store.check_auto_promotions(threshold=5) == []
        assert bare.status == "active"

    @pytest.mark.ac("SPEC-100126-5445/AC-3")
    async def test_min_confidence_flows_through(self) -> None:
        store = InMemoryLearningStore(exposure_mode=MemoryExposureMode.AGENT_MANAGED)
        learning = _evidenced(confidence=0.7)
        await store.store(learning)
        assert await store.check_auto_promotions(threshold=5, min_confidence=0.8) == []
        assert await store.check_auto_promotions(threshold=5, min_confidence=0.6) != []

    async def test_promoter_gate_skips_unevidenced_candidates(self) -> None:
        """With an approval gate, unevidenced candidates never reach the queue."""
        from maistro.memory.learnings.approval import LearningApprovalGate

        store = InMemoryLearningStore(exposure_mode=MemoryExposureMode.AGENT_MANAGED)
        bare = _evidenced(run_id="", confidence=None)
        backed = _evidenced(trigger_keys=["rollback"], learning="rollback first")
        await store.store(bare)
        await store.store(backed)

        gate = LearningApprovalGate()
        promoter = LearningPromoter(store, threshold=5, approval_gate=gate)
        await promoter.check_and_promote()

        assert [a.learning_id for a in gate.get_pending()] == [backed.id]


class _FakeLLM:
    def __init__(self, content: str) -> None:
        self._content = content

    async def complete(self, **_kwargs: Any) -> dict[str, Any]:
        return {"choices": [{"message": {"content": self._content}}]}

    def stream(self, *_args: Any, **_kwargs: Any) -> Any:  # pragma: no cover - unused
        raise NotImplementedError
