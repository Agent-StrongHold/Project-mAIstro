"""The canonical promotion contract (SPEC-100126-a9c4 / ADR-100126-a9c4).

One scenario per acceptance criterion, plus the fence edges the criteria
name. These tests are the contract's only enforcement — the module is a
value layer, so the tests are what makes a fence firing "an audit answer"
rather than "an opinion".
"""

from __future__ import annotations

import dataclasses
from datetime import datetime

import pytest

from maistro.governance.promotion import (
    AlreadyReversed,
    CandidateChange,
    DuplicateEffect,
    DuplicatePromotion,
    EffectMeasurement,
    EvaluationEvidence,
    IncompleteEvidence,
    PromotionApproval,
    PromotionContract,
    PromotionLedger,
    PromotionRefused,
    PromotionScope,
    ProtectedConstituentEdit,
    SelfApprovedPromotion,
    StaleCandidate,
    UnchangedCandidate,
)

#: A classification a host could write down: the code scope keeps its own
#: judge (the containment surface) out of candidate hands; the other scopes
#: carry the explicit "no protected constituents" decision the constructor
#: demands.
PROTECTED = {
    PromotionScope.PROMPT: frozenset(),
    PromotionScope.SKILL: frozenset(),
    PromotionScope.TEMPLATE: frozenset({"graph/templates.py"}),
    PromotionScope.POLICY: frozenset(),
    PromotionScope.ROUTING_CONFIG: frozenset(),
    PromotionScope.CODE: frozenset({"maistro_rsi/", "quality/", ".github/", "maistro/security/"}),
}


def evidence(
    run_ids: tuple[str, ...] = ("run-eval-1",),
    evaluators: dict[str, str] | None = None,
) -> EvaluationEvidence:
    return EvaluationEvidence(
        evaluation_run_ids=run_ids,
        evaluator_versions=evaluators if evaluators is not None else {"regression-judge": "v3"},
    )


def candidate(
    *,
    scope: PromotionScope = PromotionScope.CODE,
    subject: str = "patch-42",
    changed_refs: tuple[str, ...] = ("packages/maistro-core/src/maistro/router/engine.py",),
    author: str = "rsi",
    base_version: int = 1,
    base_hash: str = "hash-v1",
    proposed_hash: str = "hash-v2",
    ev: EvaluationEvidence | None = None,
) -> CandidateChange:
    return CandidateChange(
        scope=scope,
        subject=subject,
        base_version=base_version,
        base_content_hash=base_hash,
        proposed_content_hash=proposed_hash,
        changed_refs=changed_refs,
        author=author,
        evidence=ev or evidence(),
    )


def approval(authority: str = "human:op-1") -> PromotionApproval:
    return PromotionApproval(
        approver="release-owner",
        reason="benchmarks cleared, diff reviewed",
        authority=authority,
        policy_id="rsi-adversarial-review",
    )


def contract(**overrides: object) -> PromotionContract:
    return PromotionContract(dict(PROTECTED, **overrides), PromotionLedger())  # type: ignore[arg-type]


class TestAC1CandidacyIsInert:
    @pytest.mark.ac("SPEC-100126-a9c4/AC-1")
    def test_evaluate_records_nothing_and_mutates_nothing(self):
        c = contract()
        cand = candidate()
        before = dataclasses.replace(cand)

        record = c.evaluate(cand, approval(), current_version=1, current_content_hash="hash-v1")

        assert c.ledger.latest_version(PromotionScope.CODE, "patch-42") is None
        assert c.ledger.records() == ()
        assert cand == before, "gating must not touch the candidate value"
        assert record.new_version == 2
        assert record.scope is PromotionScope.CODE

    def test_promote_is_the_only_path_that_appends(self):
        c = contract()
        record = c.promote(
            candidate(), approval(), current_version=1, current_content_hash="hash-v1"
        )
        assert [r.record_id for r in c.ledger.records()] == [record.record_id]


class TestAC2ExplicitVersionAndImmutableHistory:
    @pytest.mark.ac("SPEC-100126-a9c4/AC-2")
    def test_promotion_mints_next_version_and_cites_prior(self):
        c = contract()
        record = c.promote(
            candidate(), approval(), current_version=1, current_content_hash="hash-v1"
        )
        assert record.prior_version == 1
        assert record.new_version == 2
        assert record.prior_content_hash == "hash-v1"
        assert record.content_hash == "hash-v2"

    def test_rollback_and_repromote_never_reuses_a_number(self):
        c = contract()
        c.promote(candidate(), approval(), current_version=1, current_content_hash="hash-v1")
        # The store rolls back to v1; the same candidate is re-promoted.
        record = c.promote(
            candidate(), approval(), current_version=1, current_content_hash="hash-v1"
        )
        assert record.new_version == 3, "v2 must not be reassigned after a rollback"

    def test_stale_base_is_refused_by_number_and_by_hash(self):
        c = contract()
        with pytest.raises(StaleCandidate):
            c.evaluate(
                candidate(base_version=1, base_hash="hash-v1"),
                approval(),
                current_version=2,
                current_content_hash="hash-v1",
            )
        with pytest.raises(StaleCandidate):
            c.evaluate(
                candidate(base_version=1, base_hash="stale-hash"),
                approval(),
                current_version=1,
                current_content_hash="hash-v1",
            )

    def test_duplicate_version_record_is_refused(self):
        c = contract()
        record = c.promote(
            candidate(), approval(), current_version=1, current_content_hash="hash-v1"
        )
        with pytest.raises(DuplicatePromotion):
            c.ledger.append(record)


class TestAC3RecordCompleteness:
    @pytest.mark.ac("SPEC-100126-a9c4/AC-3")
    def test_record_carries_every_governed_field(self):
        c = contract()
        record = c.promote(
            candidate(
                scope=PromotionScope.PROMPT,
                subject="agent.planner",
                base_version=4,
                base_hash="prompt-hash-4",
            ),
            approval(),
            current_version=4,
            current_content_hash="prompt-hash-4",
        )
        assert record.scope is PromotionScope.PROMPT
        assert record.subject == "agent.planner"
        assert (record.prior_version, record.new_version) == (4, 5)
        assert record.evidence.evaluation_run_ids == ("run-eval-1",)
        assert record.evidence.evaluator_versions == {"regression-judge": "v3"}
        assert record.approval.approver == "release-owner"
        assert record.approval.reason == "benchmarks cleared, diff reviewed"
        assert record.approval.authority == "human:op-1"
        assert record.approval.policy_id == "rsi-adversarial-review"
        assert record.rollback.rollback_target_version == 4
        assert record.rollback.reversible is True
        assert record.rollback.mechanism
        assert isinstance(record.promoted_at, datetime)

    def test_record_is_frozen(self):
        c = contract()
        record = c.promote(
            candidate(), approval(), current_version=1, current_content_hash="hash-v1"
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            record.new_version = 99  # type: ignore[misc]


class TestAC4OwnConstituentFence:
    @pytest.mark.ac("SPEC-100126-a9c4/AC-4")
    @pytest.mark.contract("behavioral")
    def test_candidate_cannot_edit_its_own_judge_or_constitution(self):
        c = contract()
        for protected_ref in (
            "quality/wiring-reads-baseline.json",
            ".github/workflows/rsi-harvest.yml",
        ):
            with pytest.raises(ProtectedConstituentEdit):
                c.promote(
                    candidate(changed_refs=(protected_ref,)),
                    approval(),
                    current_version=1,
                    current_content_hash="hash-v1",
                )

    def test_constituent_edit_refused_even_under_external_approval(self):
        c = contract()
        with pytest.raises(ProtectedConstituentEdit):
            c.promote(
                candidate(changed_refs=("maistro/security/sentinel/rlphd.py",)),
                approval(authority="human:chief-security-officer"),
                current_version=1,
                current_content_hash="hash-v1",
            )

    def test_unrelated_refs_still_promote(self):
        c = contract()
        record = c.promote(
            candidate(changed_refs=("packages/maistro-core/src/maistro/router/engine.py",)),
            approval(),
            current_version=1,
            current_content_hash="hash-v1",
        )
        assert record.new_version == 2

    def test_unclassified_scope_refuses_construction(self):
        incomplete = {k: v for k, v in PROTECTED.items() if k is not PromotionScope.POLICY}
        with pytest.raises(ValueError, match="policy"):
            PromotionContract(incomplete)  # type: ignore[arg-type]

    def test_template_scope_carries_its_own_constituents(self):
        c = contract()
        with pytest.raises(ProtectedConstituentEdit):
            c.promote(
                candidate(
                    scope=PromotionScope.TEMPLATE,
                    subject="tpl",
                    changed_refs=("graph/templates.py",),
                ),
                approval(),
                current_version=1,
                current_content_hash="hash-v1",
            )


class TestAC5NoSelfApproval:
    @pytest.mark.ac("SPEC-100126-a9c4/AC-5")
    @pytest.mark.contract("behavioral")
    def test_author_cannot_be_the_deciding_authority(self):
        c = contract()
        with pytest.raises(SelfApprovedPromotion):
            c.promote(
                candidate(author="rsi"),
                approval(authority="rsi"),
                current_version=1,
                current_content_hash="hash-v1",
            )

    def test_approver_is_the_effective_authority_when_none_is_named(self):
        c = contract()
        with pytest.raises(SelfApprovedPromotion):
            c.promote(
                candidate(author="release-owner"),
                PromotionApproval(approver="release-owner", reason="self-signed"),
                current_version=1,
                current_content_hash="hash-v1",
            )

    def test_external_authority_passes(self):
        c = contract()
        record = c.promote(
            candidate(author="rsi"),
            approval(authority="human:op-1"),
            current_version=1,
            current_content_hash="hash-v1",
        )
        assert record.new_version == 2


class TestAC6Traceability:
    @pytest.mark.ac("SPEC-100126-a9c4/AC-6")
    def test_trace_returns_record_effects_and_reversals(self):
        c = contract()
        record = c.promote(
            candidate(), approval(), current_version=1, current_content_hash="hash-v1"
        )
        effect = EffectMeasurement(
            measurement_id="effect-1",
            run_ids=("run-effect-9",),
            summary="p50 latency after promotion",
        )
        c.ledger.attach_effect(record.record_id, effect)
        c.ledger.mark_reversed(record.record_id, actor="human:op-2", reason="regression in prod")

        trace = c.ledger.trace(PromotionScope.CODE, "patch-42", 2)
        assert trace is not None
        assert trace.record.record_id == record.record_id
        assert trace.record.evidence.evaluation_run_ids == ("run-eval-1",)
        assert trace.effects == (effect,)
        assert trace.reversals[0].actor == "human:op-2"

    def test_unknown_record_and_duplicate_measurement_are_refused(self):
        c = contract()
        record = c.promote(
            candidate(), approval(), current_version=1, current_content_hash="hash-v1"
        )
        with pytest.raises(KeyError):
            c.ledger.attach_effect("no-such-record", EffectMeasurement("e1", ("r",)))
        c.ledger.attach_effect(record.record_id, EffectMeasurement("effect-1", ("run-effect-1",)))
        with pytest.raises(DuplicateEffect):
            c.ledger.attach_effect(
                record.record_id, EffectMeasurement("effect-1", ("run-effect-2",))
            )

    def test_double_reversal_is_refused_and_record_stays_intact(self):
        c = contract()
        record = c.promote(
            candidate(), approval(), current_version=1, current_content_hash="hash-v1"
        )
        c.ledger.mark_reversed(record.record_id, actor="a", reason="first reversal")
        with pytest.raises(AlreadyReversed):
            c.ledger.mark_reversed(record.record_id, actor="b", reason="again")
        trace = c.ledger.trace(PromotionScope.CODE, "patch-42", 2)
        assert trace is not None and len(trace.reversals) == 1
        assert record.content_hash == "hash-v2", "reversal must not rewrite the record"

    def test_effect_measurement_must_cite_runs(self):
        with pytest.raises(ValueError):
            EffectMeasurement("effect-1", ())


class TestFenceEdges:
    def test_evidence_without_runs_or_evaluator_versions_is_refused(self):
        c = contract()
        for bad in (
            evidence(run_ids=()),
            evidence(run_ids=(" ",)),
            evidence(evaluators={}),
            evidence(evaluators={"judge": " "}),
        ):
            with pytest.raises(IncompleteEvidence):
                c.promote(
                    candidate(ev=bad), approval(), current_version=1, current_content_hash="hash-v1"
                )

    def test_noop_promotion_is_refused(self):
        c = contract()
        with pytest.raises(UnchangedCandidate):
            c.promote(
                candidate(proposed_hash="hash-v1"),
                approval(),
                current_version=1,
                current_content_hash="hash-v1",
            )

    def test_every_issue_family_is_a_scope(self):
        assert {scope.value for scope in PromotionScope} == {
            "prompt",
            "skill",
            "template",
            "policy",
            "routing_config",
            "code",
        }

    def test_promotion_refused_names_its_rule(self):
        c = contract()
        with pytest.raises(PromotionRefused) as caught:
            c.promote(
                candidate(author="rsi"),
                approval(authority="rsi"),
                current_version=1,
                current_content_hash="hash-v1",
            )
        assert caught.value.rule == "self-approval"


class TestAC7OneApprovalType:
    @pytest.mark.ac("SPEC-100126-a9c4/AC-7")
    @pytest.mark.contract("boundary")
    def test_template_family_uses_the_canonical_type(self):
        from maistro.graph.templates import PromotionApproval as TemplateApproval

        assert TemplateApproval is PromotionApproval

    def test_template_construction_stays_source_compatible(self):
        gate = PromotionApproval(approver="release-owner", reason="topology reviewed")
        assert gate.effective_authority == "release-owner"
        assert gate.policy_id == PromotionApproval(approver="a", reason="b").policy_id
        with pytest.raises(ValueError):
            PromotionApproval(approver="  ", reason="x")
        with pytest.raises(ValueError):
            PromotionApproval(approver="a", reason="")
