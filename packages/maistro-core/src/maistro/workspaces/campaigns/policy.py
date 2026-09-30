"""Campaign eligibility and selection: narrowing policy, nothing more.

Pure functions over immutable records. Nothing here executes work, grants a
permission, writes a Goal field, or adds a lifecycle beside Goal and Run —
the Run lease and fence primitives (`ExecutionLease`, `StaleExecutionFence`,
`CursorLease`) are untouched; campaigns filter *before* any of them apply.

Rule versions recorded on every decision (invariant 3 / AC-3, AC-8):

* ``selection-score-v1`` — the system score: the mean of the *measured*
  signals only. An absent signal leaves both the numerator and the
  denominator; an item with no measured signals scores ``0.0`` and is ranked
  by the tiers below it.
* ``campaign-selection-rule-v1`` — how the tiers combine (Q1 default):
  1. an active pin-next control outranks the score entirely;
  2. explicit human priority is a hard override tier over the score;
  3. system score descending;
  4. ``item_id`` ascending, so the same pool always orders the same way.

``human-only`` is absolute (invariant 4): no tier, including pin-next,
returns a ``human-only`` item to an automated actor.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Protocol

from maistro.workspaces.campaigns.model import (
    Actor,
    ActorKind,
    AreaRef,
    AuditKind,
    AutonomyMode,
    BacklogItemView,
    BudgetUsage,
    CampaignAuditRecord,
    CampaignDefinition,
    ControlKind,
    ControlRecord,
    ItemPolicyRecord,
    ParkRecord,
    SelectionSignals,
)

#: Version of the score formula. Recorded on every selection decision.
SCORE_RULE_VERSION = "selection-score-v1"
#: Version of the combining rule. Recorded on every selection decision.
ORDER_RULE_VERSION = "campaign-selection-rule-v1"


class GoalReader(Protocol):
    """Read-only access to linked canonical Goal state (AC-4).

    Deliberately a read protocol: there is no method here a campaign could
    use to change a Goal's state or its owning Agent, so "no silent Goal
    reassignment" (invariant 2) holds by construction, not by convention.
    """

    async def read_goal_state(self, goal_id: str, goal_revision: str | None) -> str | None:
        """Return the Goal's lifecycle state, or ``None`` if unresolvable."""
        ...


class EligibilityDecision:
    """Why one item is or is not eligible under the applicable campaigns.

    A plain class, not a pydantic record: eligibility is a *decision about*
    an item, computed fresh per evaluation, and is persisted only through the
    audit trail — never as item state.

    ``effective_mode`` is ``None`` when no campaign covers the item: the
    campaign contract then has no authority over it and records none."""

    __slots__ = ("campaign_versions", "effective_mode", "eligible", "item_id", "reasons")

    def __init__(
        self,
        *,
        item_id: str,
        eligible: bool,
        reasons: list[str],
        effective_mode: AutonomyMode | None,
        campaign_versions: list[tuple[str, int]],
    ) -> None:
        self.item_id = item_id
        self.eligible = eligible
        self.reasons = reasons
        self.effective_mode = effective_mode
        self.campaign_versions = campaign_versions

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"EligibilityDecision(item_id={self.item_id!r}, eligible={self.eligible}, "
            f"reasons={self.reasons!r})"
        )


class RankedCandidate:
    """One selection-ordered item with both recorded inputs (AC-3)."""

    __slots__ = (
        "effective_mode",
        "human_priority",
        "item_id",
        "pinned",
        "rank",
        "score",
        "score_inputs",
    )

    def __init__(
        self,
        *,
        item_id: str,
        rank: int,
        human_priority: float | None,
        score: float,
        score_inputs: dict[str, float],
        effective_mode: AutonomyMode | None,
        pinned: bool,
    ) -> None:
        self.item_id = item_id
        self.rank = rank
        self.human_priority = human_priority
        self.score = score
        self.score_inputs = score_inputs
        self.effective_mode = effective_mode
        self.pinned = pinned

    @property
    def needs_promotion_approval(self) -> bool:
        return self.effective_mode is AutonomyMode.AUTONOMOUS_WITH_PROMOTION_APPROVAL

    @property
    def needs_human_review(self) -> bool:
        return self.effective_mode is AutonomyMode.HUMAN_REVIEW_REQUIRED


def latest_versions(campaigns: Sequence[CampaignDefinition]) -> list[CampaignDefinition]:
    """Collapse campaign versions to the latest per ``campaign_id``."""
    latest: dict[str, CampaignDefinition] = {}
    for campaign in campaigns:
        current = latest.get(campaign.campaign_id)
        if current is None or campaign.policy_version > current.policy_version:
            latest[campaign.campaign_id] = campaign
    return sorted(latest.values(), key=lambda c: (c.campaign_id, c.policy_version))


def applicable_campaigns(
    item: BacklogItemView, campaigns: Sequence[CampaignDefinition]
) -> list[CampaignDefinition]:
    """Campaigns whose scope reaches this item, latest version each.

    A campaign reaches an item through its Workspace and, when it names one,
    its Project. Scope here is the soft Workspace/Project axis only (ADR-019):
    hard tenancy is decided by the caller's authorization input, never here.
    """
    return [
        campaign
        for campaign in latest_versions(campaigns)
        if campaign.workspace_id == item.workspace_id
        and (campaign.project_id is None or campaign.project_id == item.project_id)
    ]


def _area_in(area: AreaRef, declared: Sequence[AreaRef]) -> bool:
    return any(declared.kind == area.kind and declared.value == area.value for declared in declared)


def score_item(signals: SelectionSignals | None) -> tuple[float, dict[str, float]]:
    """``selection-score-v1``: mean of the measured signals (AC-3).

    Absent is absent: unmeasured signals are excluded from both numerator and
    denominator rather than read as zero (ADR-083026-a91e). No measured
    signals at all scores ``0.0`` — the neutral floor of the tier order, not
    a measurement.
    """
    if signals is None:
        return 0.0, {}
    candidates = {
        "criticality": signals.criticality,
        "unblock_value": signals.unblock_value,
        "verification_confidence": signals.verification_confidence,
        "expected_learning_value": signals.expected_learning_value,
        "cost": signals.cost,
        "risk": signals.risk,
        "dependency_readiness": signals.dependency_readiness,
    }
    measured = {name: float(value) for name, value in candidates.items() if value is not None}
    if not measured:
        return 0.0, {}
    return sum(measured.values()) / len(measured), measured


def _budget_reached_reasons(
    usage: BudgetUsage, campaigns: Sequence[CampaignDefinition]
) -> list[str]:
    """Budget stop conditions over the union of applicable campaigns (Q3)."""
    reasons: list[str] = []
    for campaign in campaigns:
        budgets = campaign.policy.budgets
        prefix = f"budget:{campaign.campaign_id}"
        if budgets.max_cost_usd is not None and usage.cost_usd >= budgets.max_cost_usd:
            reasons.append(f"{prefix}:cost-reached")
        if budgets.max_minutes is not None and usage.minutes >= budgets.max_minutes:
            reasons.append(f"{prefix}:time-reached")
        if budgets.max_completions is not None and usage.completions >= budgets.max_completions:
            reasons.append(f"{prefix}:completions-reached")
    return reasons


def effective_mode(
    item_record: ItemPolicyRecord | None, campaign: CampaignDefinition
) -> AutonomyMode:
    """Q2: the explicit override if set, else the campaign default."""
    if item_record is not None and item_record.mode_override is not None:
        return item_record.mode_override
    return campaign.policy.default_autonomy_mode


def _constraint_reasons(item: BacklogItemView, campaign: CampaignDefinition) -> list[str]:
    """Reasons the item fails one campaign's declared constraint axes."""
    reasons: list[str] = []
    constraints = campaign.policy.constraints
    prefix = f"campaign:{campaign.campaign_id}"
    if [tag for tag in constraints.tags if tag not in item.tags]:
        reasons.append(f"{prefix}:tag-mismatch")
    if constraints.milestones and item.milestone not in constraints.milestones:
        reasons.append(f"{prefix}:milestone-mismatch")
    if constraints.packages and item.package not in constraints.packages:
        reasons.append(f"{prefix}:package-mismatch")
    if constraints.workspace_ids and item.workspace_id not in constraints.workspace_ids:
        reasons.append(f"{prefix}:workspace-scope-mismatch")
    if constraints.project_ids and item.project_id not in constraints.project_ids:
        reasons.append(f"{prefix}:project-scope-mismatch")
    if any(_area_in(area, item.declared_areas) for area in campaign.policy.protected_areas):
        reasons.append(f"{prefix}:protected-area")
    return reasons


def evaluate_item(
    *,
    item: BacklogItemView,
    actor: Actor,
    campaigns: Sequence[CampaignDefinition],
    item_records: Mapping[str, ItemPolicyRecord],
    controls: Sequence[ControlRecord],
    parks: Sequence[ParkRecord],
    usage: BudgetUsage,
    can_actor_access: Callable[[BacklogItemView], bool],
) -> EligibilityDecision:
    """Decide one item's eligibility under the applicable campaigns.

    Every constraint *removes* the item from the eligible set; nothing here
    can add eligibility the actor's own authorization does not already carry
    (invariant 1). ``can_actor_access`` is the authorization owners' answer —
    Workspace membership, Project scope, capability grants — and is ANDed in
    first: a campaign naming an item the actor cannot access leaves it
    ineligible, whatever the policy says.
    """
    reached = applicable_campaigns(item, campaigns)
    versions = [(c.campaign_id, c.policy_version) for c in reached]
    reasons: list[str] = []
    primary = reached[0] if reached else None
    mode = effective_mode(item_records.get(item.item_id), primary) if primary else None

    if not can_actor_access(item):
        # Invariant 1: never widen. A campaign cannot make an inaccessible
        # item accessible, so the decision short-circuits as ineligible.
        return EligibilityDecision(
            item_id=item.item_id,
            eligible=False,
            reasons=["authorization:actor-cannot-access"],
            effective_mode=mode,
            campaign_versions=versions,
        )

    if not reached:
        # No campaign covers the item: eligibility is simply the actor's own
        # authorization, with no campaign attribution or mode to record.
        return EligibilityDecision(
            item_id=item.item_id,
            eligible=True,
            reasons=[],
            effective_mode=None,
            campaign_versions=versions,
        )

    if actor.kind == "agent" and mode is AutonomyMode.HUMAN_ONLY:
        # Invariant 4: absolute. Not even pin-next reaches past this.
        return EligibilityDecision(
            item_id=item.item_id,
            eligible=False,
            reasons=["mode:human-only"],
            effective_mode=mode,
            campaign_versions=versions,
        )

    active_controls = [control for control in controls if control.active]
    if any(
        control.kind is ControlKind.PAUSE and control.item_id is None for control in active_controls
    ):
        reasons.append("campaign:paused")
    if any(
        control.kind is ControlKind.PAUSE and control.item_id == item.item_id
        for control in active_controls
    ):
        reasons.append("item:paused")
    if any(
        control.kind is ControlKind.EXCLUDE and control.item_id == item.item_id
        for control in active_controls
    ):
        reasons.append("item:excluded")
    if any(park.active and park.item_id == item.item_id for park in parks):
        reasons.append("item:parked")

    for campaign in reached:
        reasons.extend(_constraint_reasons(item, campaign))

    reasons.extend(_budget_reached_reasons(usage, reached))

    return EligibilityDecision(
        item_id=item.item_id,
        eligible=not reasons,
        reasons=reasons,
        effective_mode=mode,
        campaign_versions=versions,
    )


async def _read_goal_state(reader: GoalReader, item: BacklogItemView) -> str | None:
    if item.goal_id is None:
        return None
    return await reader.read_goal_state(item.goal_id, item.goal_revision)


async def evaluate_items(
    *,
    actor: Actor,
    items: Sequence[BacklogItemView],
    campaigns: Sequence[CampaignDefinition],
    item_records: Mapping[str, ItemPolicyRecord],
    controls: Sequence[ControlRecord],
    parks: Sequence[ParkRecord],
    usage: BudgetUsage,
    can_actor_access: Callable[[BacklogItemView], bool],
    goal_reader: GoalReader | None = None,
) -> list[EligibilityDecision]:
    """Decide every item's eligibility, reading linked Goal state through the
    read-only reader when a campaign requires it (AC-4).

    The Goal is read by ``goal_id``/``goal_revision``; the observed state is
    returned in the decision's reasons as audit evidence and is never copied
    into campaign or item state."""
    base_decisions = [
        evaluate_item(
            item=item,
            actor=actor,
            campaigns=campaigns,
            item_records=item_records,
            controls=controls,
            parks=parks,
            usage=usage,
            can_actor_access=can_actor_access,
        )
        for item in items
    ]

    if goal_reader is None:
        return base_decisions

    decisions: list[EligibilityDecision] = []
    for item, base in zip(items, base_decisions, strict=True):
        reached = applicable_campaigns(item, campaigns)
        required = {
            campaign.policy.required_goal_state
            for campaign in reached
            if campaign.policy.required_goal_state is not None
        }
        if base.eligible and required:
            observed = await _read_goal_state(goal_reader, item)
            mismatches = sorted(
                f"campaign:{campaign.campaign_id}:goal-state-mismatch"
                for campaign in reached
                if campaign.policy.required_goal_state is not None
                and observed != campaign.policy.required_goal_state
            )
            decisions.append(
                EligibilityDecision(
                    item_id=item.item_id,
                    eligible=not mismatches,
                    reasons=base.reasons
                    + mismatches
                    + ([f"goal-state-observed:{observed}"] if observed is not None else []),
                    effective_mode=base.effective_mode,
                    campaign_versions=base.campaign_versions,
                )
            )
        else:
            decisions.append(base)
    return decisions


def order_candidates(
    *,
    actor: Actor,
    eligible: Sequence[EligibilityDecision],
    items: Mapping[str, BacklogItemView],
    item_records: Mapping[str, ItemPolicyRecord],
    controls: Sequence[ControlRecord],
    signals: Mapping[str, SelectionSignals],
) -> list[RankedCandidate]:
    """Order eligible items under ``campaign-selection-rule-v1``.

    Both inputs are recorded on each candidate separately (AC-3): the
    priority exactly as the person set it, and the score with the signals
    that produced it. A ``human-only`` item can never appear here for an
    automated actor because :func:`evaluate_items` already removed it —
    re-checking the mode makes the invariant hold even if a caller builds the
    eligible list by hand (invariant 4).
    """
    pinned_ids = {
        control.item_id
        for control in controls
        if control.active and control.kind is ControlKind.PIN_NEXT and control.item_id is not None
    }
    candidates: list[RankedCandidate] = []
    for decision in eligible:
        if not decision.eligible:
            continue
        item_record = item_records.get(decision.item_id)
        priority = item_record.human_priority if item_record is not None else None
        score, measured = score_item(signals.get(decision.item_id))
        pinned = decision.item_id in pinned_ids
        if actor.kind == ActorKind.AGENT and decision.effective_mode is AutonomyMode.HUMAN_ONLY:
            continue
        candidates.append(
            RankedCandidate(
                item_id=decision.item_id,
                rank=0,
                human_priority=priority,
                score=score,
                score_inputs=measured,
                effective_mode=decision.effective_mode,
                pinned=pinned,
            )
        )
    candidates.sort(
        key=lambda candidate: (
            -float(candidate.pinned),
            # An explicit human instruction outranks silence.
            0.0 if candidate.human_priority is not None else 1.0,
            -(candidate.human_priority if candidate.human_priority is not None else 0.0),
            -candidate.score,
            candidate.item_id,
        )
    )
    for rank, candidate in enumerate(candidates, start=1):
        candidate.rank = rank
    return candidates


def audit_eligibility(
    *,
    actor: Actor,
    decisions: Sequence[EligibilityDecision],
    at: datetime | None = None,
) -> list[CampaignAuditRecord]:
    """One audit record per evaluated item, keyed to actor + policy versions."""
    moment = at or datetime.now(UTC)
    records: list[CampaignAuditRecord] = []
    for decision in decisions:
        primary = decision.campaign_versions[0] if decision.campaign_versions else None
        records.append(
            CampaignAuditRecord(
                at=moment,
                actor=actor,
                kind=AuditKind.ELIGIBILITY_EVALUATED,
                policy_version=primary[1] if primary else 0,
                campaign_id=primary[0] if primary else None,
                item_id=decision.item_id,
                payload={
                    "eligible": decision.eligible,
                    "reasons": list(decision.reasons),
                    "effective_mode": decision.effective_mode.value
                    if decision.effective_mode
                    else None,
                    "campaign_versions": [
                        [campaign_id, version]
                        for campaign_id, version in decision.campaign_versions
                    ],
                },
            )
        )
    return records


def audit_selection(
    *,
    actor: Actor,
    candidates: Sequence[RankedCandidate],
    campaign_versions: Sequence[tuple[str, int]],
    at: datetime | None = None,
) -> list[CampaignAuditRecord]:
    """One audit record per ranked candidate carrying both inputs and the
    rule versions that combined them (AC-3, AC-8)."""
    moment = at or datetime.now(UTC)
    primary = campaign_versions[0] if campaign_versions else None
    return [
        CampaignAuditRecord(
            at=moment,
            actor=actor,
            kind=AuditKind.SELECTION_DECIDED,
            policy_version=primary[1] if primary else 0,
            campaign_id=primary[0] if primary else None,
            item_id=candidate.item_id,
            payload={
                "rank": candidate.rank,
                "pinned": candidate.pinned,
                "human_priority": candidate.human_priority,
                "score": candidate.score,
                "score_inputs": dict(candidate.score_inputs),
                "score_rule": SCORE_RULE_VERSION,
                "order_rule": ORDER_RULE_VERSION,
                "effective_mode": candidate.effective_mode.value
                if candidate.effective_mode
                else None,
                "needs_promotion_approval": candidate.needs_promotion_approval,
                "needs_human_review": candidate.needs_human_review,
            },
        )
        for candidate in candidates
    ]
