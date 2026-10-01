"""The one governed promotion contract shared by every reusable definition family.

Promotion semantics existed here before this module, but as siblings rather
than as one contract: templates hold a ``candidate -> promoting -> active``
lifecycle with a required ``PromotionApproval`` (ADR-082926-65bf), genomes
gate on ``approved_for_promotion`` behind ``promote_audited`` (#342), RSI
patches are reviewed at checkpoint time by RLPHD (``maistro_rsi
.promotion_review``), skills raise trust tier only through an authenticated
promotion step, prompts move a label, and learnings auto-promote on a hit
count. Each kept the same promises -- a candidate is not an active thing,
promotion is explicit and audited, history does not change -- but each stated
them in its own vocabulary, so nothing could check the promises *once*.

This module is the single statement of those promises (M4-A9, #116;
SPEC-100126-a9c4). It defines, for every family that can be improved:

* :class:`PromotionScope` -- the six families the contract covers;
* :class:`CandidateChange` -- a proposed improvement that is by construction
  *not* an active version (creating one changes no resolution anywhere);
* :class:`PromotionApproval` -- the policy decision that permits one
  promotion, with a named approval policy and a deciding authority;
* :class:`PromotionContract` -- the gate every promotion passes, refusing
  incomplete evidence, self-approval, edits to the candidate's own
  evaluator/security constitution, stale bases and no-op content;
* :class:`PromotionRecord` / :class:`PromotionLedger` -- the immutable record
  of a promotion (scope, evidence, evaluator versions, approval policy,
  rollback/reversal metadata) and the traceability that ties every promoted
  version to its evaluation Runs and later effect measurements.

The contract is deliberately *not* an executor. Activation stays where it is
today -- ``maistro.graph.templates.promote_audited`` for templates,
``maistro_evolve``'s ``promote_audited`` for genomes, the harvest/review path
for code -- and each family maps onto this record; the stores own versions
and resolution, the contract owns the decision record. ``current_version``
and ``current_content_hash`` are the calling store's statement about now,
which is what lets the contract refuse a stale candidate without owning a
store.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class PromotionScope(StrEnum):
    """The definition families one promotion contract governs.

    Every family that an improvement path (RSI, Evolve, learning, a human
    editor) can propose a change to maps to exactly one of these. Adding a
    family means adding a member here *and* a ``protected_refs`` entry at
    every contract construction site -- the constructor refuses a mapping
    that does not cover all of them, so a new family cannot silently skip
    the fences.
    """

    PROMPT = "prompt"
    SKILL = "skill"
    TEMPLATE = "template"
    POLICY = "policy"
    ROUTING_CONFIG = "routing_config"
    CODE = "code"


#: The approval policy recorded when an approval names no other. A family
#: whose review path predates the contract (templates today) promotes under
#: this policy until its store names one; the field is never empty, because
#: a promotion record that cannot say what policy allowed it cannot be
#: audited against anything.
DEFAULT_APPROVAL_POLICY = "direct-approval"


@dataclass(frozen=True)
class PromotionApproval:
    """The policy decision that permits one promotion.

    History this type carries forward: the template family's first
    ``promote_audited`` had no gate at all — it recorded audit entries and
    activated, so any caller could promote and a successful audit write was
    being treated as policy approval (Codex #589). Recording that a thing
    happened is not deciding that it may (SPEC-081226-bb3a AC-11's third
    clause). The approval is a required argument rather than a mutable
    field, so there is no state to overwrite and no default that could be
    permissive.

    ``approver`` and ``reason`` must both be non-empty: an approval with
    nobody behind it and no stated grounds is the shrug this type exists to
    prevent.

    ``policy_id`` names the approval policy the decision was made under, so
    a promotion record can be audited against the policy rather than against
    a bare name. ``authority`` is *who decided*, as distinct from who signed:
    a delegated decision records the deciding principal here. An empty
    ``authority`` means the approver decided for themselves.
    """

    approver: str
    reason: str
    policy_id: str = DEFAULT_APPROVAL_POLICY
    authority: str = ""

    @property
    def effective_authority(self) -> str:
        """The principal whose decision this approval records."""
        return self.authority or self.approver

    def __post_init__(self) -> None:
        if not self.approver.strip():
            raise ValueError("a promotion approval must name its approver")
        if not self.reason.strip():
            raise ValueError("a promotion approval must state its reason")
        if not self.policy_id.strip():
            raise ValueError("a promotion approval must name its approval policy")
        if self.authority and not self.authority.strip():
            raise ValueError("a promotion approval authority must not be blank")


@dataclass(frozen=True)
class EvaluationEvidence:
    """The evaluation Runs and evaluator versions a promotion stands on.

    ``evaluation_run_ids`` are identifiers in the canonical Run ontology
    (``Goal -> Graph -> Run -> NodeRun -> Attempt``): every promoted version
    must be traceable to the Runs that evaluated it, so an empty tuple is a
    refusal, not a default. ``evaluator_versions`` names each evaluator and
    the version of it that produced the evidence, because a score without
    the version of the thing that scored it cannot be reproduced or trusted
    after the evaluator itself evolves.
    """

    evaluation_run_ids: tuple[str, ...]
    evaluator_versions: Mapping[str, str] = field(default_factory=dict)

    def validated(self) -> EvaluationEvidence:
        """Return self after asserting the evidence could support a promotion."""
        if not self.evaluation_run_ids or any(
            not run_id.strip() for run_id in self.evaluation_run_ids
        ):
            raise ValueError(
                "promotion evidence must cite at least one non-empty evaluation Run id"
            )
        if not self.evaluator_versions or any(
            not name.strip() or not version.strip()
            for name, version in self.evaluator_versions.items()
        ):
            raise ValueError("promotion evidence must name the version of every evaluator involved")
        return self


@dataclass(frozen=True)
class CandidateChange:
    """A proposed improvement that is not yet — and may never become — active.

    Creating one of these changes nothing: no version is minted, no label
    moves, no resolution anywhere returns different content. The only path
    from candidate to effect is :meth:`PromotionContract.promote`, which
    mints a *new* explicit version and records it. A candidate carries the
    base it improves on by hash, so promoting it against a base that has
    since moved is refused rather than silently rebased.
    """

    scope: PromotionScope
    subject: str
    base_version: int
    base_content_hash: str
    proposed_content_hash: str
    #: The refs (within the family's own namespace — file paths for code,
    #: definition keys otherwise) this candidate edits. This is what the
    #: evaluator/security-constitution fence reads.
    changed_refs: tuple[str, ...]
    #: The provenance path that authored the candidate ("rsi", "evolve",
    #: "learning", "human:<id>"). The self-approval fence reads this: the
    #: path that produced a candidate cannot also be the authority that
    #: approves it.
    author: str
    evidence: EvaluationEvidence

    def __post_init__(self) -> None:
        if not self.subject.strip():
            raise ValueError("a candidate must name its subject")
        if not self.base_content_hash.strip() or not self.proposed_content_hash.strip():
            raise ValueError("a candidate must carry both base and proposed content hashes")
        if not self.author.strip():
            raise ValueError("a candidate must name the path that authored it")
        if self.base_version < 0:
            raise ValueError("a candidate's base version must not be negative")


@dataclass(frozen=True)
class RollbackMetadata:
    """How a promotion is undone, recorded when the promotion happens.

    Because promotion mints a new version and never edits one in place, the
    prior version is always the rollback target: it remains addressable and
    immutable. ``mechanism`` names the family's sanctioned reversal path
    (``promote_audited`` against the prior version for templates, the
    genome store's ``rollback_audited``, a label move for prompts), so the
    record says how to reverse, not just that one could.
    """

    rollback_target_version: int
    reversible: bool = True
    mechanism: str = "re-promote the recorded prior version"


@dataclass(frozen=True)
class PromotionRecord:
    """The immutable record of one promotion.

    Everything acceptance requires a promotion to record lives here: the
    scope and subject, the explicit new version (and the prior it was
    derived from, with both content hashes), the evaluation evidence with
    evaluator versions, the approval and the policy that allowed it, and
    the rollback metadata. Records are never edited — a reversal appends a
    :class:`ReversalEntry` beside the record.
    """

    record_id: str
    scope: PromotionScope
    subject: str
    prior_version: int
    new_version: int
    prior_content_hash: str
    content_hash: str
    evidence: EvaluationEvidence
    approval: PromotionApproval
    rollback: RollbackMetadata
    promoted_at: datetime


@dataclass(frozen=True)
class EffectMeasurement:
    """A later measurement of a promoted version's effect, tied to Runs.

    "Every promoted version can be traced to evaluation Runs *and later
    effect measurements*" — the second half is recorded here, after
    promotion, against the record id. The measurement cites the Run ids that
    produced it, so the effect claim is as traceable as the evaluation claim.
    """

    measurement_id: str
    run_ids: tuple[str, ...]
    summary: str = ""

    def __post_init__(self) -> None:
        if not self.measurement_id.strip():
            raise ValueError("an effect measurement must carry an id")
        if not self.run_ids or any(not run_id.strip() for run_id in self.run_ids):
            raise ValueError("an effect measurement must cite the Runs that measured it")


@dataclass(frozen=True)
class ReversalEntry:
    """The append-only record that a promotion was reversed."""

    record_id: str
    actor: str
    reason: str
    reversed_at: datetime


@dataclass(frozen=True)
class PromotionTrace:
    """Everything recorded about one promoted version."""

    record: PromotionRecord
    effects: tuple[EffectMeasurement, ...]
    reversals: tuple[ReversalEntry, ...]


class PromotionRefused(ValueError):
    """A promotion did not pass the contract. ``rule`` names the fence."""

    def __init__(self, rule: str, message: str) -> None:
        super().__init__(f"{rule}: {message}")
        self.rule = rule


class IncompleteEvidence(PromotionRefused):
    """Evidence citing no Runs, or evaluators with no versions."""


class ProtectedConstituentEdit(PromotionRefused):
    """A candidate trying to edit its own evaluator/security constitution."""


class SelfApprovedPromotion(PromotionRefused):
    """The authoring path and the deciding authority are the same."""


class StaleCandidate(PromotionRefused):
    """The base the candidate was cut from is no longer the current version."""


class UnchangedCandidate(PromotionRefused):
    """The candidate's content is the base's content — nothing to promote."""


class DuplicatePromotion(PromotionRefused):
    """The version this promotion would mint already has a record."""


class UnknownPromotion(KeyError):
    """No record under that id."""


class DuplicateEffect(PromotionRefused):
    """An effect measurement id already recorded."""


class AlreadyReversed(PromotionRefused):
    """The promotion was already reversed."""


class PromotionLedger:
    """Append-only store of promotion records, effects and reversals.

    Records are frozen and there is no update path — correction happens by
    appending a new record or a reversal entry, which is what makes the
    historical half of the contract true rather than intended.
    """

    def __init__(self) -> None:
        self._records: dict[str, PromotionRecord] = {}
        self._effects: dict[str, list[EffectMeasurement]] = {}
        self._reversals: dict[str, list[ReversalEntry]] = {}

    def latest_version(self, scope: PromotionScope, subject: str) -> int | None:
        """The newest version any record minted for this subject, if any."""
        latest: int | None = None
        for record in self._records.values():
            if record.scope is scope and record.subject == subject:
                latest = record.new_version if latest is None else max(latest, record.new_version)
        return latest

    def append(self, record: PromotionRecord) -> None:
        """Add one record. The sanctioned caller is ``PromotionContract.promote``
        — appending a record that no evaluation minted would record a promotion
        that no gate ever passed, which is precisely the silent mutation the
        contract exists to prevent.
        """
        if record.record_id in self._records:
            raise DuplicatePromotion(
                "explicit-version",
                f"{record.record_id} already has a promotion record; a version "
                "number is never reassigned",
            )
        self._records[record.record_id] = record
        self._effects.setdefault(record.record_id, [])
        self._reversals.setdefault(record.record_id, [])

    def attach_effect(self, record_id: str, effect: EffectMeasurement) -> None:
        """Record a later effect measurement against a promoted version."""
        if record_id not in self._records:
            raise UnknownPromotion(record_id)
        effects = self._effects[record_id]
        if any(effect.measurement_id == existing.measurement_id for existing in effects):
            raise DuplicateEffect(
                "effect-identity",
                f"effect measurement {effect.measurement_id!r} is already recorded "
                f"against {record_id}",
            )
        effects.append(effect)

    def mark_reversed(self, record_id: str, *, actor: str, reason: str) -> ReversalEntry:
        """Record that a promotion was reversed. The record itself is untouched."""
        if record_id not in self._records:
            raise UnknownPromotion(record_id)
        if not actor.strip() or not reason.strip():
            raise ValueError("a reversal must name its actor and its reason")
        reversals = self._reversals[record_id]
        if reversals:
            raise AlreadyReversed(
                "reversal-once",
                f"{record_id} was already reversed by {reversals[-1].actor!r}",
            )
        entry = ReversalEntry(
            record_id=record_id,
            actor=actor,
            reason=reason,
            reversed_at=datetime.now(UTC),
        )
        reversals.append(entry)
        return entry

    def trace(self, scope: PromotionScope, subject: str, version: int) -> PromotionTrace | None:
        """Everything recorded about one promoted version, or None."""
        for record in self._records.values():
            if (
                record.scope is scope
                and record.subject == subject
                and record.new_version == version
            ):
                return PromotionTrace(
                    record=record,
                    effects=tuple(self._effects[record.record_id]),
                    reversals=tuple(self._reversals[record.record_id]),
                )
        return None

    def records(self) -> tuple[PromotionRecord, ...]:
        """Every record, oldest first."""
        return tuple(sorted(self._records.values(), key=lambda record: record.promoted_at))


class PromotionContract:
    """The gate every promotion passes, and the ledger it is recorded in.

    Constructed with the protected-constituent classification for *every*
    scope: a mapping that omits a scope is refused, because an unclassified
    family is an unguarded fence (fail closed — ADR-083126-5e62's doctrine
    that a failure to establish provenance cannot grant less scrutiny).
    Passing an explicit empty set for a scope is the written decision that
    the family has no protected constituents.
    """

    def __init__(
        self,
        protected_refs: Mapping[PromotionScope, Iterable[str]],
        ledger: PromotionLedger | None = None,
    ) -> None:
        missing = [scope for scope in PromotionScope if scope not in protected_refs]
        if missing:
            names = ", ".join(scope.value for scope in missing)
            raise ValueError(
                "protected_refs must classify every promotion scope; unclassified: "
                f"{names} — an unclassified scope is an unguarded fence"
            )
        self._protected = {scope: frozenset(refs) for scope, refs in protected_refs.items()}
        self._ledger = ledger if ledger is not None else PromotionLedger()

    @staticmethod
    def _is_protected(ref: str, protected: frozenset[str]) -> bool:
        """Fragment matching, as the containment surface uses it: a protected
        entry ending in "/" covers everything under it, any other entry is an
        exact ref. Exact-membership matching would let "quality/x.json" dodge
        a "quality/" entry — the one-omission-at-a-time failure #303 fixed."""
        return any(
            ref == entry or (entry.endswith("/") and ref.startswith(entry)) for entry in protected
        )

    @property
    def ledger(self) -> PromotionLedger:
        """The append-only record store this contract records into."""
        return self._ledger

    def protected_refs(self, scope: PromotionScope) -> frozenset[str]:
        """The refs whose edits a candidate in this scope may never carry."""
        return self._protected[scope]

    def evaluate(
        self,
        candidate: CandidateChange,
        approval: PromotionApproval,
        *,
        current_version: int,
        current_content_hash: str,
    ) -> PromotionRecord:
        """Gate one candidate and return the record minting its new version.

        Evaluating does not commit: the returned record is not in the ledger
        until :meth:`promote` (which evaluates and appends). Candidates and
        even evaluations leave nothing behind, which is the first acceptance
        criterion's other half.

        The fences, in the order they fire:

        1. **evidence** — at least one evaluation Run id and a version for
           every evaluator involved (``IncompleteEvidence``);
        2. **own-constitution** — no changed ref may be a protected
           constituent of the candidate's own evaluation or security
           governance (``ProtectedConstituentEdit``). A candidate that
           edits its own judge authorizes itself; the evaluator or
           constitution change is a separate candidate in its own scope,
           promoted under its own classification;
        3. **self-approval** — the deciding authority must not be the
           authoring path (``SelfApprovedPromotion``). Generated quality
           evidence is not the judge (ADR-083126-5e62), and the path that
           produced a candidate is not the principal that approves it;
        4. **staleness** — the candidate's base must still be the current
           version by number *and* hash (``StaleCandidate``). Promoting a
           rebased candidate silently would overwrite whatever moved;
        5. **no-op** — content identical to the base is not a promotion
           (``UnchangedCandidate``); a version must be a change.

        The minted version is explicitly new: one past both the calling
        store's current version and any version this contract already
        recorded for the subject, so a rollback-and-repromote never reuses
        a number, and history stays immutable by construction.
        """
        try:
            candidate.evidence.validated()
        except ValueError as exc:
            raise IncompleteEvidence("evidence", str(exc)) from exc

        protected = self._protected[candidate.scope]
        offending = sorted(
            ref for ref in candidate.changed_refs if self._is_protected(ref, protected)
        )
        if offending:
            raise ProtectedConstituentEdit(
                "own-constitution",
                f"candidate for {candidate.scope.value}/{candidate.subject} edits its "
                f"own evaluator/security constitution: {', '.join(offending)} — promote "
                "that change as its own candidate under its own classification",
            )

        if approval.effective_authority == candidate.author:
            raise SelfApprovedPromotion(
                "self-approval",
                f"authority {approval.effective_authority!r} authored the candidate it "
                "is approving — approval must come from outside the authoring path",
            )

        if (
            candidate.base_version != current_version
            or candidate.base_content_hash != current_content_hash
        ):
            raise StaleCandidate(
                "staleness",
                f"candidate base v{candidate.base_version} "
                f"({candidate.base_content_hash[:12]}) is not current "
                f"v{current_version} ({current_content_hash[:12]}) — rebase the "
                "candidate before promoting",
            )

        if candidate.proposed_content_hash == current_content_hash:
            raise UnchangedCandidate(
                "no-op",
                "the candidate's content equals the current content — a promotion "
                "mints a version for a change, not for a re-declaration",
            )

        ledger_latest = self._ledger.latest_version(candidate.scope, candidate.subject)
        new_version = max(current_version, ledger_latest or 0) + 1
        return PromotionRecord(
            record_id=f"{candidate.scope.value}:{candidate.subject}:v{new_version}",
            scope=candidate.scope,
            subject=candidate.subject,
            prior_version=current_version,
            new_version=new_version,
            prior_content_hash=current_content_hash,
            content_hash=candidate.proposed_content_hash,
            evidence=candidate.evidence,
            approval=approval,
            rollback=RollbackMetadata(rollback_target_version=current_version),
            promoted_at=datetime.now(UTC),
        )

    def promote(
        self,
        candidate: CandidateChange,
        approval: PromotionApproval,
        *,
        current_version: int,
        current_content_hash: str,
    ) -> PromotionRecord:
        """Gate a candidate and append its record. The only promotion path."""
        record = self.evaluate(
            candidate,
            approval,
            current_version=current_version,
            current_content_hash=current_content_hash,
        )
        self._ledger.append(record)
        return record
