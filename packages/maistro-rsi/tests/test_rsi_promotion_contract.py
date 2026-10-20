"""RSI promotions gated through the shared M4 promotion contract (#116 / #552).

The fences RSI promotions must pass are the same ones every definition family
passes: evidence-bound (canonical evaluation Runs + evaluator versions),
constitution-safe (no self-edits of the evaluator oracle), never
self-approved, and never a no-op or a promotion of a stale base.
"""

from __future__ import annotations

import pytest

from maistro.governance.promotion import (
    IncompleteEvidence,
    PromotionLedger,
    PromotionRecord,
    PromotionScope,
    ProtectedConstituentEdit,
    SelfApprovedPromotion,
    StaleCandidate,
    UnchangedCandidate,
)
from maistro_rsi.promotion_contract import (
    RSI_CANDIDATE_AUTHOR,
    RSI_MECHANICAL_AUTHORITY,
    candidate_change,
    checkpoint_approval,
    record_kept_promotion,
    rsi_promotion_contract,
)
from maistro_rsi.sensitive_paths import EVALUATOR_ORACLE_PATTERNS

SUBJECT = "rsi-baseline:rsi-baseline"
BASE = "a" * 40
CANDIDATE = "b" * 40
RUN_IDS = ("run-eval-1",)
EVALUATORS = {"evaluator_oracle": "digest-1", "trace_note": "v2"}


def _record(contract=None, **overrides) -> PromotionRecord:
    kwargs: dict = {
        "subject": SUBJECT,
        "base_sha": BASE,
        "candidate_sha": CANDIDATE,
        "touched_paths": ("packages/app/src/thing.py",),
        "evaluation_run_ids": RUN_IDS,
        "evaluator_versions": EVALUATORS,
        "approver": "rsi-checkpoint-reviewer",
        "reason": "checkpoint review keep",
        "mechanical": False,
    }
    kwargs.update(overrides)
    return record_kept_promotion(contract or rsi_promotion_contract(), **kwargs)


def _record_on(contract, **overrides) -> PromotionRecord:
    return _record(contract, **overrides)


class TestContractClassification:
    def test_code_scope_carries_the_evaluator_oracle_patterns(self):
        contract = rsi_promotion_contract()
        assert contract.protected_refs(PromotionScope.CODE) == frozenset(EVALUATOR_ORACLE_PATTERNS)
        # Every other family carries the written "no protected constituents"
        # decision, which is also the truth for an RSI candidate.
        for scope in PromotionScope:
            if scope is not PromotionScope.CODE:
                assert contract.protected_refs(scope) == frozenset()

    def test_a_shared_ledger_can_be_injected(self):
        ledger = PromotionLedger()
        contract = rsi_promotion_contract(ledger=ledger)
        assert contract is not None


class TestKeptPromotion:
    def test_keep_is_gated_and_minted_with_evidence(self):
        record = _record()
        assert record.scope is PromotionScope.CODE
        assert record.subject == SUBJECT
        assert record.new_version == 1
        assert record.evidence.evaluation_run_ids == RUN_IDS
        assert record.evidence.evaluator_versions == EVALUATORS
        assert record.approval.policy_id == "rsi-checkpoint-review-v1"

    def test_mechanical_authority_is_the_policy_never_the_author(self):
        approval = checkpoint_approval(
            approver="rsi-mechanical-policy", reason="mechanical floor met", mechanical=True
        )
        assert approval.authority == RSI_MECHANICAL_AUTHORITY
        assert approval.effective_authority != RSI_CANDIDATE_AUTHOR
        record = _record(mechanical=True, approver="rsi-mechanical-policy")
        assert record.approval.effective_authority == RSI_MECHANICAL_AUTHORITY

    def test_refuses_promotion_without_canonical_evaluation_runs(self):
        with pytest.raises(IncompleteEvidence):
            _record(evaluation_run_ids=())

    def test_refuses_promotion_without_evaluator_versions(self):
        with pytest.raises(IncompleteEvidence):
            _record(evaluator_versions={})

    def test_refuses_edits_to_the_evaluator_oracle(self):
        protected = EVALUATOR_ORACLE_PATTERNS[0]
        with pytest.raises(ProtectedConstituentEdit):
            _record(touched_paths=(protected, "packages/app/src/thing.py"))

    def test_refuses_self_approval(self):
        # An approval whose deciding authority collapses into the authoring
        # path ("rsi") is a self-approved promotion, whichever field carries it.
        import dataclasses

        contract = rsi_promotion_contract()
        change = candidate_change(
            subject=SUBJECT,
            base_sha=BASE,
            candidate_sha=CANDIDATE,
            touched_paths=("x.py",),
            evaluation_run_ids=RUN_IDS,
            evaluator_versions=EVALUATORS,
        )
        assert change.author == RSI_CANDIDATE_AUTHOR
        base_approval = checkpoint_approval(approver="op", reason="x", mechanical=False)
        self_approved = dataclasses.replace(base_approval, authority=RSI_CANDIDATE_AUTHOR)
        assert self_approved.effective_authority == RSI_CANDIDATE_AUTHOR
        with pytest.raises(SelfApprovedPromotion):
            contract.promote(change, self_approved, current_version=0, current_content_hash=BASE)
        # And the mechanical policy's authority is not the authoring path —
        # the default wiring can never trip this fence.
        assert RSI_MECHANICAL_AUTHORITY != RSI_CANDIDATE_AUTHOR

    def test_refuses_unchanged_candidate(self):
        with pytest.raises(UnchangedCandidate):
            _record(candidate_sha=BASE)

    def test_refuses_stale_base(self):
        # One contract, one subject: v1 minted at CANDIDATE. A second
        # promotion claiming its base was BASE (not what the ledger minted
        # for v1) is stale — two mutually-consistent caller claims cannot
        # both be true.
        contract = rsi_promotion_contract()
        _record_on(contract)  # version 1 minted at CANDIDATE
        with pytest.raises(StaleCandidate):
            record_kept_promotion(
                contract,
                subject=SUBJECT,
                base_sha=BASE,
                candidate_sha="d" * 40,
                touched_paths=("x.py",),
                evaluation_run_ids=RUN_IDS,
                evaluator_versions=EVALUATORS,
                approver="rsi-checkpoint-reviewer",
                reason="checkpoint review keep",
                mechanical=False,
                current_version=1,
            )

    def test_versioned_chain_on_one_subject(self):
        contract = rsi_promotion_contract()
        first = _record_on(contract, candidate_sha="c" * 40)
        second = _record_on(
            contract,
            base_sha="c" * 40,
            candidate_sha="d" * 40,
            current_version=first.new_version,
        )
        assert second.new_version == first.new_version + 1
