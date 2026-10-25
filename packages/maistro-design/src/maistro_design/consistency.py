"""Cross-artifact consistency evaluation and targeted refinement (#779).

Unified Creative Production needs one explicit way to judge whether a family
of artifacts still represents the same goal, Persona, Design System and source
truth — and then route only the affected work for refinement. A local poster
defect must not regenerate accepted website copy, while a shared factual
contradiction may invalidate every descendant that consumed the bad shared
decision.

This module is that evaluator. It is deliberately deterministic (pattern
matching over the project snapshot, no model call) so results are the same on
every run and testable without a model; the same stance
:mod:`maistro.agents.brief_interview` takes for the intake conversation.

Design rules pinned here:

- **Proposal, never mutation.** The evaluator reads a frozen
  :class:`CreativeProjectSnapshot` and returns a
  :class:`ConsistencyEvaluation`. It has no write path to any store, so it
  cannot silently change the project — not even a locked artifact. Refinement
  *targets* are proposals; canonical DAG/Run logic decides what actually runs
  under current user locks, control mode and authority.
- **Impact follows real relationships.** Which artifacts a finding affects is
  computed from ``artifact.consumes`` (shared decisions) and
  ``artifact.references`` (sibling/parent artifacts) — never from hard-coded
  artifact-type rules. Two posters where only one consumes the bad decision
  produce exactly one affected branch.
- **Versions are cited, never inferred.** The result carries the exact
  CreativeBrief version, goal revision, decision versions and artifact
  versions that were evaluated, so a historical result stays interpretable
  after later edits.
- **Evidence is distinguished from assertion.** Claims backed by a provided
  evidence item are checked against it; claims that exist only in generated
  content are reported as unverified model assertions, a distinct, weaker
  verdict. This is project-quality evaluation, not a self-improvement
  authority — historical evaluations may later become M4 evidence, but this
  module only evaluates and proposes for the current creative project.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "AccessibilityCheck",
    "AccessibilityConstraint",
    "BriefSnapshot",
    "ChannelRequirement",
    "ClaimRule",
    "ConsistencyDimension",
    "ConsistencyEvaluation",
    "ConsistencyFinding",
    "ContradictionRule",
    "CreativeProjectSnapshot",
    "DimensionResult",
    "EvidenceItem",
    "FamilyArtifact",
    "FindingOrigin",
    "PersonaSnapshot",
    "RefinementProposal",
    "RefinementTarget",
    "RequiredMessage",
    "Severity",
    "SharedDecision",
    "TermRule",
    "evaluate_project_snapshot",
]


# ─── Project snapshot (the frozen input) ─────────────────────────────────────


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class EvidenceItem(_Frozen):
    """A piece of source truth the project was given — not generated."""

    evidence_id: str
    statement: str  # regex, matched case-insensitively against content


class ClaimRule(_Frozen):
    """One claim the brief allows, and where its truth comes from.

    ``source="provided_evidence"`` claims must name the :class:`EvidenceItem`
    that grounds them. ``source="model_asserted"`` claims are tolerated but
    reported as unverified: nobody gave the project that fact.
    """

    claim_id: str
    pattern: str  # regex for the claim as it may appear in artifact content
    source: Literal["provided_evidence", "model_asserted"]
    evidence_id: str | None = None

    # Pydantic invokes this validator on every ClaimRule construction; no
    # scanned call site names it (decorator-driven dispatch).
    @model_validator(mode="after")  # noqa: V105
    def _require_evidence_backing(self) -> ClaimRule:
        if self.source == "provided_evidence" and not self.evidence_id:
            msg = f"claim {self.claim_id!r} cites provided_evidence but names no evidence_id"
            raise ValueError(msg)
        if self.source == "model_asserted" and self.evidence_id is not None:
            msg = f"claim {self.claim_id!r} is model_asserted and cannot cite an evidence_id"
            raise ValueError(msg)
        return self


class ContradictionRule(_Frozen):
    """Two content patterns the brief declares mutually exclusive.

    Deterministic contradiction needs a truth table, so the brief (which owns
    source truth and allowed claims) supplies the conflicting pairs. If one
    artifact — or two siblings — assert both sides, the factual/sibling
    dimensions fail.
    """

    rule_id: str
    description: str
    pattern_a: str
    pattern_b: str


class TermRule(_Frozen):
    """Preferred terminology: the word to use and the aliases it replaces."""

    preferred: str
    banned_aliases: tuple[str, ...]  # regexes, matched case-insensitively


class RequiredMessage(_Frozen):
    """A message/CTA that must appear in the artifacts the brief names."""

    message_id: str
    pattern: str  # regex, matched case-insensitively
    required_in: tuple[str, ...] = ("*",)  # artifact kinds; ("*",) = every artifact


class ChannelRequirement(_Frozen):
    """Channel-specific required/forbidden elements for one artifact kind."""

    artifact_kind: str
    required_elements: tuple[str, ...] = ()  # regexes that must be present
    forbidden_elements: tuple[str, ...] = ()  # regexes that must not be present


AccessibilityCheck = Literal["image_alt_text", "html_lang_declared"]
"""Deterministic, honest accessibility checks.

Only checks that can be evaluated truthfully from artifact text live here;
browser-level checks (contrast, focus) belong to the rendered-product
surfaces and are deliberately not faked from source text.
"""


class AccessibilityConstraint(_Frozen):
    constraint_id: str
    check: AccessibilityCheck


class SharedDecision(_Frozen):
    """A versioned decision shared by a family of artifacts.

    Decisions are the upstream nodes of the creative DAG: artifacts declare
    consumption through :attr:`FamilyArtifact.consumes`, which is the only
    route by which a decision defect spreads to descendants.
    """

    decision_id: str
    version: int
    kind: str  # free labelling only — impact logic never branches on it
    statement: str
    status: Literal["accepted", "proposed", "superseded"] = "accepted"
    locked: bool = False


class FamilyArtifact(_Frozen):
    """One artifact of the family, with its real graph relationships.

    ``consumes`` names shared decisions this artifact was built from;
    ``references`` names sibling/parent artifacts it derives from. These two
    edge sets are the dependency truth the refinement router walks.
    """

    artifact_id: str
    version: int
    kind: str  # free labelling only — impact logic never branches on it
    title: str
    content: str
    status: Literal["draft", "accepted"] = "draft"
    locked: bool = False
    consumes: tuple[str, ...] = ()
    references: tuple[str, ...] = ()


class PersonaSnapshot(_Frozen):
    """The guiding Persona's voice, as checkable markers."""

    persona_id: str
    name: str
    required_markers: tuple[str, ...] = ()  # regexes that should appear
    banned_markers: tuple[str, ...] = ()  # regexes that must not appear


class DesignSystemSnapshot(_Frozen):
    """The brand-system facts that are checkable from artifact text."""

    slug: str
    palette_hex: tuple[str, ...] = ()  # allowed colours, e.g. "#1a2b3c"
    banned_fonts: tuple[str, ...] = ()  # font-family names that must not appear


class BriefSnapshot(_Frozen):
    """The CreativeBrief version being evaluated against (#774 state).

    ``brief_version`` and ``goal_revision`` are cited verbatim in every
    result so evaluations remain interpretable after later edits.
    """

    brief_id: str
    version: int
    goal_revision: str
    audience: str = ""
    objective: str = ""
    objective_keywords: tuple[str, ...] = ()  # regexes that should appear
    allowed_claims: tuple[ClaimRule, ...] = ()
    contradiction_rules: tuple[ContradictionRule, ...] = ()
    terminology: tuple[TermRule, ...] = ()
    required_messages: tuple[RequiredMessage, ...] = ()
    channel_requirements: tuple[ChannelRequirement, ...] = ()
    accessibility_constraints: tuple[AccessibilityConstraint, ...] = ()


class CreativeProjectSnapshot(_Frozen):
    """Frozen view of one creative project at evaluation time.

    The evaluator reads this and nothing else; it cannot reach a store, so it
    cannot observe or mutate anything the caller did not hand it.
    """

    project_id: str
    brief: BriefSnapshot
    persona: PersonaSnapshot | None = None
    design_system: DesignSystemSnapshot | None = None
    decisions: tuple[SharedDecision, ...] = ()
    artifacts: tuple[FamilyArtifact, ...] = ()
    evidence: tuple[EvidenceItem, ...] = ()


# ─── Result contract ─────────────────────────────────────────────────────────


class FindingOrigin(StrEnum):
    """Whether a defect is local to one branch or originates upstream."""

    LOCAL = "local"
    SHARED = "shared"


class ConsistencyDimension(StrEnum):
    PERSONA_VOICE = "persona_voice"
    DESIGN_SYSTEM_COMPLIANCE = "design_system_compliance"
    FACTUAL_CLAIMS = "factual_claims"
    AUDIENCE_OBJECTIVE_ALIGNMENT = "audience_objective_alignment"
    TERMINOLOGY = "terminology"
    MESSAGE_COVERAGE = "message_coverage"
    SIBLING_CONTRADICTION = "sibling_contradiction"
    CHANNEL_REQUIREMENTS = "channel_requirements"
    ACCESSIBILITY = "accessibility"
    LOCKED_DECISIONS = "locked_decisions"


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


# The result-contract fields carrying inline vulture ``V107`` markers below are the
# evaluation record's serialization surface: the evaluator writes them once,
# the record is stored via ``model_dump``, and downstream consumers (tests,
# the Design Studio inspection surface, future M4 evidence readers) read them
# back. Vulture cannot see framework-driven serialization reads, so the
# declarations carry inline vulture markers instead of ledger debt; every one
# of them is mandated by the #779 result contract (exact versions cited,
# evidence, affected nodes, proposal identity and root cause).


class ConsistencyFinding(_Frozen):
    """One judged defect (or explicit pass note) with its evidence."""

    finding_id: str
    dimension: ConsistencyDimension
    severity: Severity
    artifact_id: str | None = None
    decision_id: str | None = None
    evidence: str  # human-readable reason, quoting the matched content
    origin: FindingOrigin
    affected_artifact_ids: tuple[str, ...] = ()
    affected_decision_ids: tuple[str, ...] = ()  # noqa: V107
    claim_id: str | None = None
    rule_id: str | None = None
    message_id: str | None = None
    constraint_id: str | None = None


class DimensionResult(_Frozen):
    """Pass/fail for one evaluated dimension, with its findings."""

    dimension: ConsistencyDimension
    passed: bool
    finding_ids: tuple[str, ...] = ()


class RefinementTarget(_Frozen):
    """One artifact proposed for refinement — a proposal, not an action."""

    artifact_id: str
    # The exact artifact version the proposal targets, so canonical Run logic
    # can detect stale proposals after later edits (serialization surface).
    artifact_version: int  # noqa: V107
    reason: str
    finding_ids: tuple[str, ...] = ()
    locked: bool = False
    #: True when the artifact (or an upstream decision it consumes) is locked.
    #: Canonical Run logic must refuse to rewrite such a target until the user
    #: unlocks it; the evaluator itself never writes anything.
    requires_unlock: bool = False  # noqa: V107


class RefinementProposal(_Frozen):
    proposal_id: str  # noqa: V107
    root_cause: FindingOrigin  # noqa: V107
    #: Shared decisions at the root of a shared-origin defect (empty for local).
    shared_decision_ids: tuple[str, ...] = ()
    targets: tuple[RefinementTarget, ...] = ()
    note: str = (
        "Proposal only: canonical DAG/Run logic decides what actually runs "
        "under current user locks, control mode and authority."
    )


class EvaluationProvenance(_Frozen):
    """Exactly which brief/decision/artifact versions were evaluated."""

    brief_id: str
    brief_version: int  # noqa: V107
    goal_revision: str
    persona_id: str | None = None
    design_system_slug: str | None = None
    decision_versions: dict[str, int] = Field(default_factory=dict)  # noqa: V107
    artifact_versions: dict[str, int] = Field(default_factory=dict)  # noqa: V107
    evidence_ids: tuple[str, ...] = ()  # noqa: V107


class ConsistencyEvaluation(_Frozen):
    """The result contract: provenance, per-dimension verdicts, evidence,
    affected nodes, local-vs-shared origin, and a refinement proposal that
    changes nothing by itself."""

    evaluation_id: str  # noqa: V107
    evaluated_at: str  # noqa: V107
    project_id: str
    passed: bool
    provenance: EvaluationProvenance
    dimension_results: tuple[DimensionResult, ...] = ()
    findings: tuple[ConsistencyFinding, ...] = ()
    refinement: RefinementProposal | None = None


# ─── Impact routing (relationship-driven) ────────────────────────────────────


def _decision_consumers(snapshot: CreativeProjectSnapshot) -> dict[str, set[str]]:
    consumers: dict[str, set[str]] = {}
    for artifact in snapshot.artifacts:
        for decision_id in artifact.consumes:
            consumers.setdefault(decision_id, set()).add(artifact.artifact_id)
    return consumers


def _artifact_dependents(snapshot: CreativeProjectSnapshot) -> dict[str, set[str]]:
    dependents: dict[str, set[str]] = {}
    for artifact in snapshot.artifacts:
        for referenced in artifact.references:
            dependents.setdefault(referenced, set()).add(artifact.artifact_id)
    return dependents


def _decision_upstream_of(
    artifact: FamilyArtifact,
    decisions_by_id: dict[str, SharedDecision],
) -> set[str]:
    return {d for d in artifact.consumes if d in decisions_by_id}


def _shared_impact_closure(
    decision_ids: set[str],
    consumers: dict[str, set[str]],
    dependents: dict[str, set[str]],
) -> set[str]:
    """Every artifact touched by defects in ``decision_ids``.

    Direct consumers of each bad decision, plus everything that references a
    consumer, transitively. Walks only declared edges — never artifact kinds.
    """
    affected: set[str] = set()
    frontier: list[str] = []
    for decision_id in decision_ids:
        frontier.extend(consumers.get(decision_id, ()))
    while frontier:
        artifact_id = frontier.pop()
        if artifact_id in affected:
            continue
        affected.add(artifact_id)
        frontier.extend(dependents.get(artifact_id, ()))
    return affected


def _local_impact_closure(
    artifact_id: str,
    dependents: dict[str, set[str]],
) -> set[str]:
    """The artifact itself plus everything downstream of it, transitively."""
    affected: set[str] = set()
    frontier = [artifact_id]
    while frontier:
        current = frontier.pop()
        if current in affected:
            continue
        affected.add(current)
        frontier.extend(dependents.get(current, ()))
    return affected


# ─── Checks ──────────────────────────────────────────────────────────────────


def _contains(pattern: str, text: str) -> bool:
    try:
        return re.search(pattern, text, re.IGNORECASE) is not None
    except re.error:
        return pattern.lower() in text.lower()


_NEGATION_CUES = re.compile(
    r"\b(?:never|not|no|cannot|can't|won't|don't|doesn't|didn't|isn't|aren't"
    r"|wasn't|weren't|shouldn't|mustn't|avoid\w*|prohibit\w*|forbid\w*"
    r"|exclud\w*|instead of|rather than)\b",
    re.IGNORECASE,
)
_NEGATION_WINDOW = 48  # chars of preceding context treated as negation scope


def _mentions_affirmatively(pattern: str, text: str) -> bool:
    """Whether *pattern* occurs in *text* outside any negation scope.

    Origin attribution needs polarity: a decision that says "never an app"
    mentions "app" only to forbid it, so that mention must not brand the
    decision as the origin of an "app" violation (which would wrongly widen
    refinement to every consumer of a correct decision). Defect detection in
    artifact content still uses plain :func:`_contains` — using a banned
    marker is the defect regardless of phrasing.
    """
    try:
        compiled = re.compile(pattern, re.IGNORECASE)
    except re.error:
        compiled = None
    starts: list[int] = []
    if compiled is not None:
        starts = [match.start() for match in compiled.finditer(text)]
    else:
        needle = pattern.lower()
        lowered = text.lower()
        index = lowered.find(needle)
        while index != -1:
            starts.append(index)
            step = len(needle) or 1
            index = lowered.find(needle, index + step)
    for start in starts:
        prefix = text[max(0, start - _NEGATION_WINDOW) : start]
        if not _NEGATION_CUES.search(prefix):
            return True
    return False


def _origin_for(
    artifact: FamilyArtifact,
    marker: str,
    decisions_by_id: dict[str, SharedDecision],
) -> tuple[FindingOrigin, str | None]:
    """A violation is *shared* when an upstream decision itself asserts it.

    Mentions inside a negation scope ("never an app") are prohibitions, not
    assertions, so they do not make the decision the defect's origin.
    """
    for decision_id in _decision_upstream_of(artifact, decisions_by_id):
        statement = decisions_by_id[decision_id].statement
        if _mentions_affirmatively(marker, statement):
            return FindingOrigin.SHARED, decision_id
    return FindingOrigin.LOCAL, None


def _quote(match_text: str, limit: int = 80) -> str:
    collapsed = " ".join(match_text.split())
    return collapsed if len(collapsed) <= limit else f"{collapsed[:limit]}…"


class _Collector:
    """Accumulates findings and hands out stable ids."""

    def __init__(self) -> None:
        self.findings: list[ConsistencyFinding] = []

    def _record(
        self,
        severity: Severity,
        dimension: ConsistencyDimension,
        evidence: str,
        *,
        artifact_id: str | None = None,
        decision_id: str | None = None,
        origin: FindingOrigin = FindingOrigin.LOCAL,
        affected_artifacts: tuple[str, ...] = (),
        affected_decisions: tuple[str, ...] = (),
        **ids: str | None,
    ) -> ConsistencyFinding:
        finding = ConsistencyFinding(
            finding_id=f"find-{uuid.uuid4().hex[:12]}",
            dimension=dimension,
            severity=severity,
            evidence=evidence,
            origin=origin,
            affected_artifact_ids=affected_artifacts,
            affected_decision_ids=affected_decisions,
            artifact_id=artifact_id,
            decision_id=decision_id,
            **ids,
        )
        self.findings.append(finding)
        return finding

    def error(
        self,
        dimension: ConsistencyDimension,
        evidence: str,
        **kwargs: Any,
    ) -> ConsistencyFinding:
        return self._record(Severity.ERROR, dimension, evidence, **kwargs)

    def warn(
        self,
        dimension: ConsistencyDimension,
        evidence: str,
        **kwargs: Any,
    ) -> ConsistencyFinding:
        return self._record(Severity.WARNING, dimension, evidence, **kwargs)


def _check_persona(
    snapshot: CreativeProjectSnapshot,
    decisions_by_id: dict[str, SharedDecision],
    collector: _Collector,
    dependents: dict[str, set[str]],
) -> None:
    persona = snapshot.persona
    if persona is None:
        return
    consumers = _decision_consumers(snapshot)
    for artifact in snapshot.artifacts:
        for marker in persona.banned_markers:
            if not _contains(marker, artifact.content):
                continue
            origin, decision_id = _origin_for(artifact, marker, decisions_by_id)
            if origin is FindingOrigin.SHARED and decision_id is not None:
                affected = _shared_impact_closure({decision_id}, consumers, dependents)
            else:
                affected = _local_impact_closure(artifact.artifact_id, dependents)
            quoted = _quote(marker)
            collector.error(
                ConsistencyDimension.PERSONA_VOICE,
                f"persona '{persona.name}' bans {marker!r}; found in "
                f"'{artifact.artifact_id}' content: \"{quoted}\"",
                artifact_id=artifact.artifact_id,
                decision_id=decision_id,
                origin=origin,
                affected_artifacts=tuple(sorted(affected)),
                affected_decisions=(decision_id,) if decision_id else (),
            )
        for marker in persona.required_markers:
            if not _contains(marker, artifact.content):
                affected = _local_impact_closure(artifact.artifact_id, dependents)
                collector.warn(
                    ConsistencyDimension.PERSONA_VOICE,
                    f"persona '{persona.name}' expects voice marker {marker!r}; "
                    f"missing from '{artifact.artifact_id}'",
                    artifact_id=artifact.artifact_id,
                    origin=FindingOrigin.LOCAL,
                    affected_artifacts=tuple(sorted(affected)),
                )


def _check_terminology(
    snapshot: CreativeProjectSnapshot,
    decisions_by_id: dict[str, SharedDecision],
    collector: _Collector,
    dependents: dict[str, set[str]],
) -> None:
    for artifact in snapshot.artifacts:
        for rule in snapshot.brief.terminology:
            for alias in rule.banned_aliases:
                if not _contains(alias, artifact.content):
                    continue
                origin, decision_id = _origin_for(artifact, alias, decisions_by_id)
                if origin is FindingOrigin.SHARED and decision_id is not None:
                    consumers = _decision_consumers(snapshot)
                    affected = _shared_impact_closure({decision_id}, consumers, dependents)
                else:
                    affected = _local_impact_closure(artifact.artifact_id, dependents)
                collector.error(
                    ConsistencyDimension.TERMINOLOGY,
                    f"brief requires '{rule.preferred}' but banned alias {alias!r} appears in "
                    f"'{artifact.artifact_id}': \"{_quote(alias)}\"",
                    artifact_id=artifact.artifact_id,
                    decision_id=decision_id,
                    origin=origin,
                    affected_artifacts=tuple(sorted(affected)),
                    affected_decisions=(decision_id,) if decision_id else (),
                )


def _impact_of_pattern(
    snapshot: CreativeProjectSnapshot,
    artifact: FamilyArtifact,
    pattern: str,
    decisions_by_id: dict[str, SharedDecision],
    dependents: dict[str, set[str]],
) -> tuple[FindingOrigin, str | None, tuple[str, ...]]:
    """Impact closure for a matched pattern: the shared-origin closure when the
    pattern comes from a shared decision, the local one otherwise."""
    origin, decision_id = _origin_for(artifact, pattern, decisions_by_id)
    if origin is FindingOrigin.SHARED and decision_id is not None:
        consumers = _decision_consumers(snapshot)
        affected = _shared_impact_closure({decision_id}, consumers, dependents)
    else:
        affected = _local_impact_closure(artifact.artifact_id, dependents)
    return origin, decision_id, tuple(sorted(affected))


def _judge_allowed_claim(
    snapshot: CreativeProjectSnapshot,
    artifact: FamilyArtifact,
    claim: ClaimRule,
    evidence_by_id: dict[str, EvidenceItem],
    decisions_by_id: dict[str, SharedDecision],
    dependents: dict[str, set[str]],
    collector: _Collector,
) -> None:
    """Judge one allowed-claim occurrence the artifact actually carries."""
    if claim.source == "model_asserted":
        # Distinct, weaker verdict: an assertion nobody provided
        # evidence for is not a contradiction, but it is not truth.
        origin, decision_id, affected = _impact_of_pattern(
            snapshot, artifact, claim.pattern, decisions_by_id, dependents
        )
        collector.warn(
            ConsistencyDimension.FACTUAL_CLAIMS,
            f"claim '{claim.claim_id}' in '{artifact.artifact_id}' is a "
            f"model-generated assertion with no provided evidence backing",
            artifact_id=artifact.artifact_id,
            decision_id=decision_id,
            origin=origin,
            affected_artifacts=affected,
            affected_decisions=(decision_id,) if decision_id else (),
            claim_id=claim.claim_id,
        )
        return
    evidence = evidence_by_id.get(claim.evidence_id or "")
    if evidence is None:
        collector.error(
            ConsistencyDimension.FACTUAL_CLAIMS,
            f"claim '{claim.claim_id}' cites evidence "
            f"'{claim.evidence_id}' which the project snapshot does not contain",
            artifact_id=artifact.artifact_id,
            origin=FindingOrigin.LOCAL,
            affected_artifacts=tuple(
                sorted(_local_impact_closure(artifact.artifact_id, dependents))
            ),
            claim_id=claim.claim_id,
        )
    elif not _contains(claim.pattern, evidence.statement):
        # The cited evidence merely existing is not backing: the
        # claim is truth only if the provided statement actually
        # states it (e.g. a "24-hour delivery" claim citing a
        # "48-hour turnaround" item must not pass as backed).
        origin, decision_id, affected = _impact_of_pattern(
            snapshot, artifact, claim.pattern, decisions_by_id, dependents
        )
        collector.error(
            ConsistencyDimension.FACTUAL_CLAIMS,
            f"claim '{claim.claim_id}' in '{artifact.artifact_id}' cites "
            f"evidence '{claim.evidence_id}' whose statement does not "
            f'contain it: "{_quote(claim.pattern)}" not found in '
            f'"{_quote(evidence.statement)}"',
            artifact_id=artifact.artifact_id,
            decision_id=decision_id,
            origin=origin,
            affected_artifacts=affected,
            affected_decisions=(decision_id,) if decision_id else (),
            claim_id=claim.claim_id,
        )


def _check_factual_claims(
    snapshot: CreativeProjectSnapshot,
    decisions_by_id: dict[str, SharedDecision],
    collector: _Collector,
    dependents: dict[str, set[str]],
) -> None:
    """Allowed-claim and contradiction dimensions for every artifact."""
    brief = snapshot.brief
    evidence_by_id = {e.evidence_id: e for e in snapshot.evidence}
    for artifact in snapshot.artifacts:
        for claim in brief.allowed_claims:
            if not _contains(claim.pattern, artifact.content):
                continue
            _judge_allowed_claim(
                snapshot,
                artifact,
                claim,
                evidence_by_id,
                decisions_by_id,
                dependents,
                collector,
            )
        for rule in brief.contradiction_rules:
            has_a = _contains(rule.pattern_a, artifact.content)
            has_b = _contains(rule.pattern_b, artifact.content)
            if has_a and has_b:
                origin, decision_id, affected = _impact_of_pattern(
                    snapshot, artifact, rule.pattern_a, decisions_by_id, dependents
                )
                collector.error(
                    ConsistencyDimension.FACTUAL_CLAIMS,
                    f"'{artifact.artifact_id}' asserts both sides of contradiction "
                    f"'{rule.rule_id}' ({rule.description}): \"{_quote(rule.pattern_a)}\" vs "
                    f'"{_quote(rule.pattern_b)}"',
                    artifact_id=artifact.artifact_id,
                    decision_id=decision_id,
                    origin=origin,
                    affected_artifacts=affected,
                    affected_decisions=(decision_id,) if decision_id else (),
                    rule_id=rule.rule_id,
                )


def _check_decision_evidence_contradictions(
    snapshot: CreativeProjectSnapshot,
    decisions_by_id: dict[str, SharedDecision],
    collector: _Collector,
    dependents: dict[str, set[str]],
) -> None:
    """A shared decision that contradicts provided evidence invalidates every
    artifact that consumed it — the descendants come from the consumption
    edges, so all of them are identified, not just the artifact that happens
    to be inspected first."""
    evidence = snapshot.evidence
    for decision in snapshot.decisions:
        if decision.status == "superseded":
            continue
        for rule in snapshot.brief.contradiction_rules:
            pairs = ((rule.pattern_a, rule.pattern_b), (rule.pattern_b, rule.pattern_a))
            for decision_side, evidence_side in pairs:
                if not _contains(decision_side, decision.statement):
                    continue
                if not any(_contains(evidence_side, e.statement) for e in evidence):
                    continue
                consumers = _decision_consumers(snapshot)
                affected = _shared_impact_closure({decision.decision_id}, consumers, dependents)
                collector.error(
                    ConsistencyDimension.FACTUAL_CLAIMS,
                    f"shared decision '{decision.decision_id}' v{decision.version} asserts "
                    f'"{_quote(decision_side)}" which contradicts provided evidence: '
                    f'"{_quote(evidence_side)}" ({rule.rule_id}: {rule.description})',
                    artifact_id=None,
                    decision_id=decision.decision_id,
                    origin=FindingOrigin.SHARED,
                    affected_artifacts=tuple(sorted(affected)),
                    affected_decisions=(decision.decision_id,),
                    rule_id=rule.rule_id,
                )


def _check_sibling_contradictions(
    snapshot: CreativeProjectSnapshot,
    decisions_by_id: dict[str, SharedDecision],
    collector: _Collector,
    dependents: dict[str, set[str]],
) -> None:
    artifacts = snapshot.artifacts
    for i, left in enumerate(artifacts):
        for right in artifacts[i + 1 :]:
            for rule in snapshot.brief.contradiction_rules:
                left_a = _contains(rule.pattern_a, left.content)
                left_b = _contains(rule.pattern_b, left.content)
                right_a = _contains(rule.pattern_a, right.content)
                right_b = _contains(rule.pattern_b, right.content)
                if not ((left_a and right_b) or (left_b and right_a)):
                    continue
                # Shared origin when a consumed decision carries either side.
                # Pair each artifact with the side it actually carries: the
                # predicate above can match in either orientation, and the
                # origin check must probe the pattern present on that side.
                if left_a and right_b:
                    sides = ((left, rule.pattern_a), (right, rule.pattern_b))
                else:
                    sides = ((left, rule.pattern_b), (right, rule.pattern_a))
                origin = FindingOrigin.LOCAL
                decision_id = None
                for artifact, pattern in sides:
                    o, d = _origin_for(artifact, pattern, decisions_by_id)
                    if o is FindingOrigin.SHARED and d is not None:
                        origin, decision_id = o, d
                        break
                if origin is FindingOrigin.SHARED and decision_id is not None:
                    consumers = _decision_consumers(snapshot)
                    affected = _shared_impact_closure({decision_id}, consumers, dependents)
                else:
                    affected = _local_impact_closure(
                        left.artifact_id, dependents
                    ) | _local_impact_closure(right.artifact_id, dependents)
                collector.error(
                    ConsistencyDimension.SIBLING_CONTRADICTION,
                    f"siblings '{left.artifact_id}' and '{right.artifact_id}' contradict "
                    f"each other on '{rule.rule_id}' ({rule.description})",
                    artifact_id=left.artifact_id,
                    decision_id=decision_id,
                    origin=origin,
                    affected_artifacts=tuple(sorted(affected)),
                    affected_decisions=(decision_id,) if decision_id else (),
                    rule_id=rule.rule_id,
                )


def _check_message_coverage(
    snapshot: CreativeProjectSnapshot,
    collector: _Collector,
    dependents: dict[str, set[str]],
) -> None:
    for artifact in snapshot.artifacts:
        for message in snapshot.brief.required_messages:
            applies = "*" in message.required_in or artifact.kind in message.required_in
            if not applies or _contains(message.pattern, artifact.content):
                continue
            affected = _local_impact_closure(artifact.artifact_id, dependents)
            collector.error(
                ConsistencyDimension.MESSAGE_COVERAGE,
                f"required message '{message.message_id}' is missing from "
                f"'{artifact.artifact_id}' ({artifact.kind})",
                artifact_id=artifact.artifact_id,
                origin=FindingOrigin.LOCAL,
                affected_artifacts=tuple(sorted(affected)),
                message_id=message.message_id,
            )


def _check_channel_requirements(
    snapshot: CreativeProjectSnapshot,
    collector: _Collector,
    dependents: dict[str, set[str]],
) -> None:
    by_kind: dict[str, list[ChannelRequirement]] = {}
    for requirement in snapshot.brief.channel_requirements:
        by_kind.setdefault(requirement.artifact_kind, []).append(requirement)
    for artifact in snapshot.artifacts:
        for requirement in by_kind.get(artifact.kind, ()):
            for element in requirement.required_elements:
                if _contains(element, artifact.content):
                    continue
                affected = _local_impact_closure(artifact.artifact_id, dependents)
                collector.error(
                    ConsistencyDimension.CHANNEL_REQUIREMENTS,
                    f"channel '{artifact.kind}' requires {element!r}; missing from "
                    f"'{artifact.artifact_id}'",
                    artifact_id=artifact.artifact_id,
                    origin=FindingOrigin.LOCAL,
                    affected_artifacts=tuple(sorted(affected)),
                )
            for element in requirement.forbidden_elements:
                if not _contains(element, artifact.content):
                    continue
                affected = _local_impact_closure(artifact.artifact_id, dependents)
                collector.error(
                    ConsistencyDimension.CHANNEL_REQUIREMENTS,
                    f"channel '{artifact.kind}' forbids {element!r}; found in "
                    f"'{artifact.artifact_id}'",
                    artifact_id=artifact.artifact_id,
                    origin=FindingOrigin.LOCAL,
                    affected_artifacts=tuple(sorted(affected)),
                )


def _check_accessibility(
    snapshot: CreativeProjectSnapshot,
    collector: _Collector,
    dependents: dict[str, set[str]],
) -> None:
    for artifact in snapshot.artifacts:
        for constraint in snapshot.brief.accessibility_constraints:
            violated: str | None = None
            if constraint.check == "image_alt_text":
                for match in re.finditer(r"<img\b[^>]*>", artifact.content, re.IGNORECASE):
                    if not re.search(r"\balt\s*=", match.group(0), re.IGNORECASE):
                        violated = _quote(match.group(0))
                        break
            elif (
                constraint.check == "html_lang_declared"
                and re.search(r"<html\b", artifact.content, re.IGNORECASE)
                and not re.search(r"<html\b[^>]*\blang\s*=", artifact.content, re.IGNORECASE)
            ):
                violated = "<html> without lang attribute"
            if violated is None:
                continue
            affected = _local_impact_closure(artifact.artifact_id, dependents)
            collector.error(
                ConsistencyDimension.ACCESSIBILITY,
                f"accessibility constraint '{constraint.constraint_id}' "
                f"({constraint.check}) violated in '{artifact.artifact_id}': {violated}",
                artifact_id=artifact.artifact_id,
                origin=FindingOrigin.LOCAL,
                affected_artifacts=tuple(sorted(affected)),
                constraint_id=constraint.constraint_id,
            )


def _check_design_system(
    snapshot: CreativeProjectSnapshot,
    collector: _Collector,
    dependents: dict[str, set[str]],
) -> None:
    system = snapshot.design_system
    if system is None:
        return
    palette = {c.lower() for c in system.palette_hex}
    for artifact in snapshot.artifacts:
        for match in re.finditer(r"#[0-9a-fA-F]{6}\b", artifact.content):
            if match.group(0).lower() in palette:
                continue
            affected = _local_impact_closure(artifact.artifact_id, dependents)
            collector.warn(
                ConsistencyDimension.DESIGN_SYSTEM_COMPLIANCE,
                f"colour {match.group(0)} in '{artifact.artifact_id}' is outside the "
                f"'{system.slug}' palette",
                artifact_id=artifact.artifact_id,
                origin=FindingOrigin.LOCAL,
                affected_artifacts=tuple(sorted(affected)),
            )
        for font in system.banned_fonts:
            if not _contains(font, artifact.content):
                continue
            affected = _local_impact_closure(artifact.artifact_id, dependents)
            collector.error(
                ConsistencyDimension.DESIGN_SYSTEM_COMPLIANCE,
                f"font '{font}' is banned by design system '{system.slug}' but used in "
                f"'{artifact.artifact_id}'",
                artifact_id=artifact.artifact_id,
                origin=FindingOrigin.LOCAL,
                affected_artifacts=tuple(sorted(affected)),
            )


def _check_audience_objective(
    snapshot: CreativeProjectSnapshot,
    collector: _Collector,
    dependents: dict[str, set[str]],
) -> None:
    brief = snapshot.brief
    for artifact in snapshot.artifacts:
        for keyword in brief.objective_keywords:
            if _contains(keyword, artifact.content):
                continue
            affected = _local_impact_closure(artifact.artifact_id, dependents)
            collector.warn(
                ConsistencyDimension.AUDIENCE_OBJECTIVE_ALIGNMENT,
                f'objective keyword {keyword!r} (objective: "{_quote(brief.objective)}") '
                f"is not reflected in '{artifact.artifact_id}'",
                artifact_id=artifact.artifact_id,
                origin=FindingOrigin.LOCAL,
                affected_artifacts=tuple(sorted(affected)),
            )


def _check_locked_decisions(
    snapshot: CreativeProjectSnapshot,
    decisions_by_id: dict[str, SharedDecision],
    collector: _Collector,
) -> None:
    """Report conflicts that touch locked state — without rewriting anything.

    The evaluator never changes a project, so "silent rewrite" is impossible
    here by construction; this dimension exists to make the conflict visible
    and to mark refinement targets that require an explicit unlock.
    """
    for artifact in snapshot.artifacts:
        locked_upstream = [
            decisions_by_id[d]
            for d in _decision_upstream_of(artifact, decisions_by_id)
            if decisions_by_id[d].locked
        ]
        if artifact.locked or locked_upstream:
            names = [d.decision_id for d in locked_upstream]
            what = (
                "the artifact itself is locked"
                if artifact.locked
                else (f"it consumes locked decision(s) {', '.join(names)}")
            )
            collector.warn(
                ConsistencyDimension.LOCKED_DECISIONS,
                f"'{artifact.artifact_id}' touches locked state: {what}. Any refinement "
                f"must be proposed, reported, and explicitly unlocked — never silently "
                f"rewritten.",
                artifact_id=artifact.artifact_id,
                decision_id=names[0] if names else None,
                origin=FindingOrigin.LOCAL,
                affected_artifacts=(artifact.artifact_id,),
                affected_decisions=tuple(names),
            )


# ─── Entry point ─────────────────────────────────────────────────────────────


def evaluate_project_snapshot(snapshot: CreativeProjectSnapshot) -> ConsistencyEvaluation:
    """Evaluate one frozen project snapshot and return the result contract.

    Pure function: no store access, no mutation, no model calls. The same
    snapshot always yields the same verdict modulo finding/evaluation ids and
    the timestamp.
    """
    decisions_by_id = {d.decision_id: d for d in snapshot.decisions}
    dependents = _artifact_dependents(snapshot)
    collector = _Collector()

    _check_persona(snapshot, decisions_by_id, collector, dependents)
    _check_terminology(snapshot, decisions_by_id, collector, dependents)
    _check_factual_claims(snapshot, decisions_by_id, collector, dependents)
    _check_decision_evidence_contradictions(snapshot, decisions_by_id, collector, dependents)
    _check_sibling_contradictions(snapshot, decisions_by_id, collector, dependents)
    _check_message_coverage(snapshot, collector, dependents)
    _check_channel_requirements(snapshot, collector, dependents)
    _check_accessibility(snapshot, collector, dependents)
    _check_design_system(snapshot, collector, dependents)
    _check_audience_objective(snapshot, collector, dependents)
    _check_locked_decisions(snapshot, decisions_by_id, collector)

    by_dimension: dict[ConsistencyDimension, list[ConsistencyFinding]] = {}
    for finding in collector.findings:
        by_dimension.setdefault(finding.dimension, []).append(finding)

    dimension_results = tuple(
        DimensionResult(
            dimension=dimension,
            passed=not any(f.severity is Severity.ERROR for f in by_dimension.get(dimension, ())),
            finding_ids=tuple(f.finding_id for f in by_dimension.get(dimension, ())),
        )
        # Emit a verdict for every dimension so consumers can tell an
        # explicitly passing check from one that was never evaluated.
        for dimension in ConsistencyDimension
    )
    passed = all(result.passed for result in dimension_results)

    provenance = EvaluationProvenance(
        brief_id=snapshot.brief.brief_id,
        brief_version=snapshot.brief.version,
        goal_revision=snapshot.brief.goal_revision,
        persona_id=snapshot.persona.persona_id if snapshot.persona else None,
        design_system_slug=snapshot.design_system.slug if snapshot.design_system else None,
        decision_versions={d.decision_id: d.version for d in snapshot.decisions},
        artifact_versions={a.artifact_id: a.version for a in snapshot.artifacts},
        evidence_ids=tuple(e.evidence_id for e in snapshot.evidence),
    )

    errors = [f for f in collector.findings if f.severity is Severity.ERROR]
    refinement = _build_refinement(snapshot, decisions_by_id, errors) if errors else None

    return ConsistencyEvaluation(
        evaluation_id=f"eval-{uuid.uuid4().hex[:12]}",
        evaluated_at=datetime.now(UTC).isoformat(),
        project_id=snapshot.project_id,
        passed=passed,
        provenance=provenance,
        dimension_results=dimension_results,
        findings=tuple(collector.findings),
        refinement=refinement,
    )


def _build_refinement(
    snapshot: CreativeProjectSnapshot,
    decisions_by_id: dict[str, SharedDecision],
    errors: list[ConsistencyFinding],
) -> RefinementProposal:
    """Route only the affected work.

    Shared-origin errors put every consumer of the bad decision (plus their
    dependents) on the list; local errors put only the defect's own branch on
    it. Targets keep their lock state so canonical Run logic can refuse to
    rewrite locked artifacts without the evaluator ever having to.
    """
    dependents = _artifact_dependents(snapshot)
    consumers = _decision_consumers(snapshot)
    shared_decision_ids: set[str] = set()
    targeted: dict[str, set[str]] = {}

    for finding in errors:
        if finding.origin is FindingOrigin.SHARED and finding.decision_id:
            shared_decision_ids.add(finding.decision_id)
            affected = _shared_impact_closure({finding.decision_id}, consumers, dependents)
        elif finding.affected_artifact_ids:
            affected = set(finding.affected_artifact_ids)
        else:
            affected = _local_impact_closure(finding.artifact_id or "", dependents) - {""}
        for artifact_id in affected:
            targeted.setdefault(artifact_id, set()).add(finding.finding_id)

    artifacts_by_id = {a.artifact_id: a for a in snapshot.artifacts}
    targets = []
    for artifact_id in sorted(targeted):
        artifact = artifacts_by_id.get(artifact_id)
        if artifact is None:
            continue
        locked = artifact.locked or any(
            decisions_by_id[d].locked for d in artifact.consumes if d in decisions_by_id
        )
        finding_ids = tuple(sorted(targeted[artifact_id]))
        reasons = [f.evidence for f in errors if f.finding_id in targeted[artifact_id]]
        targets.append(
            RefinementTarget(
                artifact_id=artifact_id,
                artifact_version=artifact.version,
                reason="; ".join(reasons) or "upstream shared decision invalidated this artifact",
                finding_ids=finding_ids,
                locked=artifact.locked,
                requires_unlock=locked,
            )
        )

    return RefinementProposal(
        proposal_id=f"refine-{uuid.uuid4().hex[:12]}",
        root_cause=FindingOrigin.SHARED if shared_decision_ids else FindingOrigin.LOCAL,
        shared_decision_ids=tuple(sorted(shared_decision_ids)),
        targets=tuple(targets),
    )
