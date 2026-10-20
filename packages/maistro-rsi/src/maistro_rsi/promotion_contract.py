"""RSI promotions through the shared M4 promotion contract (#116).

Epic #552's exit criteria require RSI's promotion path to *consume* the
shared M4 candidate/evaluation/promotion contract rather than keeping a
private record shape. ``maistro.governance.promotion`` is that contract
(M4-A9, #116): one gate and one append-only ledger for every definition
family, with ``PromotionScope.CODE`` naming RSI's patch promotions
explicitly. Before this module, RSI's promotion path consumed only
``ImprovementKind`` from maistro-evolve and wrote its own private
``PromotionRecord`` — the shared contract's fences never ran for RSI.

What RSI keeps: the checkpoint-time RLPHD review (``promotion_review.py``)
and the mechanical/judgment split (#110) stay exactly where they are — the
contract's own docstring says activation stays with each family. What
changes: every kept promotion is now *gated and minted* through the shared
contract, so a promotion that RSI records is

* **evidence-bound** — it must cite the canonical evaluation Runs
  (``EvaluationEvidence.evaluation_run_ids``) and the version of every
  evaluator that produced the evidence; no Run ids, no shared record
  (fail-closed, never fabricated);
* **constitution-safe** — the candidate may not edit its own evaluator,
  scenario corpus, or ratchet artifacts: the CODE scope's protected
  constituents are exactly ``EVALUATOR_ORACLE_PATTERNS`` (#109), one list in
  one place;
* **not self-approved** — the authoring path (``"rsi"``) can never be the
  approving authority; the mechanical path's authority is the recorded
  mechanical policy, and a human review names the human;
* **reproducible** — the minted ``PromotionRecord`` carries the policy ids,
  hashes, evidence, and rollback mechanism in the shared ledger shape.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from maistro.governance.promotion import (
    CandidateChange,
    EvaluationEvidence,
    PromotionApproval,
    PromotionContract,
    PromotionLedger,
    PromotionRecord,
    PromotionScope,
)
from maistro_rsi.sensitive_paths import EVALUATOR_ORACLE_PATTERNS

#: The provenance path that authors an RSI candidate, verbatim from the
#: shared contract's vocabulary ("rsi", "evolve", "learning", "human:<id>").
RSI_CANDIDATE_AUTHOR = "rsi"

#: Approval policy id for the checkpoint review path (RLPHD-gated
#: mechanical/judgment split, #110 / SPEC-248).
RSI_CHECKPOINT_REVIEW_POLICY = "rsi-checkpoint-review-v1"

#: The deciding authority a *mechanical* keep records. Deliberately not the
#: authoring path: the shared contract refuses a promotion whose authority
#: is its own author, and that fence is the point of consuming it — the
#: mechanical path's authority is the recorded policy, not "rsi".
RSI_MECHANICAL_AUTHORITY = "rsi-mechanical-policy-v1"


def rsi_promotion_contract(
    *,
    code_protected_refs: Sequence[str] = EVALUATOR_ORACLE_PATTERNS,
    ledger: PromotionLedger | None = None,
) -> PromotionContract:
    """The shared promotion contract, classified for RSI's use.

    Every scope must be classified (the constructor fails closed otherwise).
    RSI promotes only code: the CODE scope's protected constituents are the
    evaluator/scenario/ratchet artifacts (#109's ``EVALUATOR_ORACLE_PATTERNS``
    — the same single list the in-loop oracle veto reads), and every other
    family gets the written decision "no protected constituents", which is
    also the truth: an RSI candidate never carries refs in those families.
    """
    return PromotionContract(
        protected_refs={
            scope: (tuple(code_protected_refs) if scope is PromotionScope.CODE else ())
            for scope in PromotionScope
        },
        ledger=ledger,
    )


def candidate_change(
    *,
    subject: str,
    base_sha: str,
    candidate_sha: str,
    touched_paths: Sequence[str],
    evaluation_run_ids: Sequence[str],
    evaluator_versions: Mapping[str, str],
    base_version: int = 0,
) -> CandidateChange:
    """One RSI patch promotion as a shared-contract candidate.

    ``subject`` names the promoted line (e.g. ``"rsi-baseline:<branch>"``);
    the content hashes are the base/candidate commit shas, so the contract's
    staleness and no-op fences compare exactly what git would.
    """
    return CandidateChange(
        scope=PromotionScope.CODE,
        subject=subject,
        base_version=base_version,
        base_content_hash=base_sha,
        proposed_content_hash=candidate_sha,
        changed_refs=tuple(touched_paths),
        author=RSI_CANDIDATE_AUTHOR,
        evidence=EvaluationEvidence(
            evaluation_run_ids=tuple(evaluation_run_ids),
            evaluator_versions=dict(evaluator_versions),
        ),
    )


def checkpoint_approval(
    *,
    approver: str,
    reason: str,
    mechanical: bool,
) -> PromotionApproval:
    """The approval a checkpoint review's keep records.

    A mechanical keep's deciding authority is the recorded mechanical policy
    (never the authoring path); a judgment keep names the human reviewer as
    both approver and authority.
    """
    return PromotionApproval(
        approver=approver,
        reason=reason,
        policy_id=RSI_CHECKPOINT_REVIEW_POLICY,
        authority=RSI_MECHANICAL_AUTHORITY if mechanical else "",
    )


def record_kept_promotion(
    contract: PromotionContract,
    *,
    subject: str,
    base_sha: str,
    candidate_sha: str,
    touched_paths: Sequence[str],
    evaluation_run_ids: Sequence[str],
    evaluator_versions: Mapping[str, str],
    approver: str,
    reason: str,
    mechanical: bool,
    current_version: int = 0,
) -> PromotionRecord:
    """Gate and mint one kept RSI promotion in the shared contract.

    Raises the contract's own refusals — ``IncompleteEvidence`` without
    canonical evaluation Runs, ``ProtectedConstituentEdit`` when the
    candidate edits its own oracle (#109), ``SelfApprovedPromotion`` when
    the approval collapses into the authoring path, ``StaleCandidate`` /
    ``UnchangedCandidate`` for a base that moved or a no-op — so the fences
    RSI promotions pass are the same fences every family passes.
    """
    return contract.promote(
        candidate_change(
            subject=subject,
            base_sha=base_sha,
            candidate_sha=candidate_sha,
            touched_paths=touched_paths,
            evaluation_run_ids=evaluation_run_ids,
            evaluator_versions=evaluator_versions,
            base_version=current_version,
        ),
        checkpoint_approval(approver=approver, reason=reason, mechanical=mechanical),
        current_version=current_version,
        current_content_hash=base_sha,
    )
