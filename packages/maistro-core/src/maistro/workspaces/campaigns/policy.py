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
from pathlib import PurePosixPath
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


def _path_under(descendant: str, ancestor: str) -> bool:
    """True when ``descendant`` is ``ancestor`` or lies beneath it (POSIX).

    Segment-aware, so protected ``deploy/`` covers ``deploy/prod.yml`` but not
    sibling ``deployment/x``.
    """
    base = PurePosixPath(ancestor.strip("/"))
    path = PurePosixPath(descendant.strip("/"))
    return path == base or base in path.parents


def _area_in(area: AreaRef, declared: Sequence[AreaRef]) -> bool:
    """Protected areas reach path descendants; packages/resources match exactly."""
    if area.kind == "path":
        return any(
            candidate.kind == "path" and _path_under(candidate.value, area.value)
            for candidate in declared
        )
    return any(
        candidate.kind == area.kind and candidate.value == area.value for candidate in declared
    )


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
    usage: Mapping[str, BudgetUsage], campaigns: Sequence[CampaignDefinition]
) -> list[str]:
    """Budget stop conditions over the union of applicable campaigns (Q3).

    Each budget is compared only with its own campaign's counter: usage is
    keyed by ``campaign_id`` as recorded through the store, so consumption
    attributed to one campaign can never exhaust another's budget, and
    campaigns that reach the same item do not double-count each other.
    """
    reasons: list[str] = []
    for campaign in campaigns:
        counters = usage.get(campaign.campaign_id, BudgetUsage())
        budgets = campaign.policy.budgets
        prefix = f"budget:{campaign.campaign_id}"
        if budgets.max_cost_usd is not None and counters.cost_usd >= budgets.max_cost_usd:
            reasons.append(f"{prefix}:cost-reached")
        if budgets.max_minutes is not None and counters.minutes >= budgets.max_minutes:
            reasons.append(f"{prefix}:time-reached")
        if budgets.max_completions is not None and counters.completions >= budgets.max_completions:
            reasons.append(f"{prefix}:completions-reached")
    return reasons


def effective_mode(
    item_record: ItemPolicyRecord | None, campaign: CampaignDefinition
) -> AutonomyMode:
    """Q2: the explicit override if set, else the campaign default."""
    if item_record is not None and item_record.mode_override is not None:
        return item_record.mode_override
    return campaign.policy.default_autonomy_mode


def _scope_reasons(item: BacklogItemView, campaign: CampaignDefinition) -> list[str]:
    """The tag / milestone / package / Workspace / Project axes (AC-1).

    A declared axis narrows; an empty axis constrains nothing, so each check
    is ``declared and item misses it``."""
    constraints = campaign.policy.constraints
    prefix = f"campaign:{campaign.campaign_id}"
    missing_tags = [tag for tag in constraints.tags if tag not in item.tags]
    mismatches: list[tuple[bool, str]] = [
        (bool(missing_tags), "tag-mismatch"),
        (
            bool(constraints.milestones) and item.milestone not in constraints.milestones,
            "milestone-mismatch",
        ),
        (
            bool(constraints.packages) and item.package not in constraints.packages,
            "package-mismatch",
        ),
        (
            bool(constraints.workspace_ids) and item.workspace_id not in constraints.workspace_ids,
            "workspace-scope-mismatch",
        ),
        (
            bool(constraints.project_ids) and item.project_id not in constraints.project_ids,
            "project-scope-mismatch",
        ),
    ]
    return [f"{prefix}:{reason}" for failed, reason in mismatches if failed]


def _constraint_reasons(item: BacklogItemView, campaign: CampaignDefinition) -> list[str]:
    """Reasons the item fails one campaign's declared constraint axes."""
    reasons = _scope_reasons(item, campaign)
    if any(_area_in(area, item.declared_areas) for area in campaign.policy.protected_areas):
        reasons.append(f"campaign:{campaign.campaign_id}:protected-area")
    return reasons


def _applicable_mode(
    item: BacklogItemView,
    item_records: Mapping[str, ItemPolicyRecord],
    scoped_controls: Sequence[ControlRecord],
    reached: Sequence[CampaignDefinition],
) -> AutonomyMode | None:
    """The item's effective mode under the primary reaching campaign.

    ``None`` when no campaign covers the item. An active human-only control
    *is* the durable mode: it is folded in here so the absolute gate below
    (and the selection-time re-check) applies even without a separate
    item-policy override."""
    primary = reached[0] if reached else None
    mode = effective_mode(item_records.get(item.item_id), primary) if primary else None
    if any(
        control.kind is ControlKind.HUMAN_ONLY
        and control.active
        and control.item_id == item.item_id
        for control in scoped_controls
    ):
        mode = AutonomyMode.HUMAN_ONLY
    return mode


def _active_controls(controls: Sequence[ControlRecord]) -> list[ControlRecord]:
    """Controls not yet cleared; a cleared control steers nothing."""
    return [control for control in controls if control.active]


def _pause_reasons(item: BacklogItemView, active: Sequence[ControlRecord]) -> list[str]:
    """Campaign-wide pause first, then this-item pause (AC-5)."""
    campaign_wide = any(
        control.kind is ControlKind.PAUSE and control.item_id is None for control in active
    )
    item_scoped = any(
        control.kind is ControlKind.PAUSE and control.item_id == item.item_id for control in active
    )
    return [
        reason
        for paused, reason in (
            (campaign_wide, "campaign:paused"),
            (item_scoped, "item:paused"),
        )
        if paused
    ]


def _control_reasons(item: BacklogItemView, scoped_controls: Sequence[ControlRecord]) -> list[str]:
    """Reasons an active operator control removes the item, in the canonical
    order the audit trail records them: campaign pause, item pause, exclude."""
    active = _active_controls(scoped_controls)
    reasons = _pause_reasons(item, active)
    if any(
        control.kind is ControlKind.EXCLUDE and control.item_id == item.item_id
        for control in active
    ):
        reasons.append("item:excluded")
    return reasons


def _item_park_reason(item: BacklogItemView, scoped_parks: Sequence[ParkRecord]) -> list[str]:
    """``item:parked`` when an active park names this item (Q5)."""
    if any(park.active and park.item_id == item.item_id for park in scoped_parks):
        return ["item:parked"]
    return []


def _decision(
    item: BacklogItemView,
    *,
    eligible: bool,
    reasons: list[str],
    mode: AutonomyMode | None,
    versions: list[tuple[str, int]],
) -> EligibilityDecision:
    """One eligibility decision with the campaign versions it was made under."""
    return EligibilityDecision(
        item_id=item.item_id,
        eligible=eligible,
        reasons=reasons,
        effective_mode=mode,
        campaign_versions=versions,
    )


def _scoped_records(
    controls: Sequence[ControlRecord], parks: Sequence[ParkRecord], reached_ids: set[str]
) -> tuple[list[ControlRecord], list[ParkRecord]]:
    """Only records written on a campaign that reaches this item may narrow
    it. The default selector loads every campaign, so without this filter a
    campaign-wide pause in one campaign would read as a global pause."""
    scoped_controls = [control for control in controls if control.campaign_id in reached_ids]
    scoped_parks = [park for park in parks if park.campaign_id in reached_ids]
    return scoped_controls, scoped_parks


def evaluate_item(
    *,
    item: BacklogItemView,
    actor: Actor,
    campaigns: Sequence[CampaignDefinition],
    item_records: Mapping[str, ItemPolicyRecord],
    controls: Sequence[ControlRecord],
    parks: Sequence[ParkRecord],
    usage: Mapping[str, BudgetUsage],
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
    scoped_controls, scoped_parks = _scoped_records(
        controls, parks, {campaign.campaign_id for campaign in reached}
    )
    mode = _applicable_mode(item, item_records, scoped_controls, reached)

    if not can_actor_access(item):
        # Invariant 1: never widen. A campaign cannot make an inaccessible
        # item accessible, so the decision short-circuits as ineligible.
        return _decision(
            item,
            eligible=False,
            reasons=["authorization:actor-cannot-access"],
            mode=mode,
            versions=versions,
        )

    if not reached:
        # No campaign covers the item: eligibility is simply the actor's own
        # authorization, with no campaign attribution or mode to record.
        return _decision(item, eligible=True, reasons=[], mode=None, versions=versions)

    if actor.kind == "agent" and mode is AutonomyMode.HUMAN_ONLY:
        # Invariant 4: absolute. Not even pin-next reaches past this.
        return _decision(
            item,
            eligible=False,
            reasons=["mode:human-only"],
            mode=mode,
            versions=versions,
        )

    reasons = _control_reasons(item, scoped_controls)
    reasons.extend(_item_park_reason(item, scoped_parks))
    for campaign in reached:
        reasons.extend(_constraint_reasons(item, campaign))
    reasons.extend(_budget_reached_reasons(usage, reached))

    return _decision(item, eligible=not reasons, reasons=reasons, mode=mode, versions=versions)


async def _read_goal_state(reader: GoalReader, item: BacklogItemView) -> str | None:
    if item.goal_id is None:
        return None
    return await reader.read_goal_state(item.goal_id, item.goal_revision)


def _required_states(item: BacklogItemView, campaigns: Sequence[CampaignDefinition]) -> set[str]:
    """Goal states a reaching campaign demands, for the AC-4 read."""
    return {
        campaign.policy.required_goal_state
        for campaign in applicable_campaigns(item, campaigns)
        if campaign.policy.required_goal_state is not None
    }


def _unreadable_goal_reasons(
    item: BacklogItemView, campaigns: Sequence[CampaignDefinition]
) -> list[str]:
    """Fail-closed reasons: a required Goal state that cannot be observed."""
    return sorted(
        f"campaign:{campaign.campaign_id}:goal-state-unreadable"
        for campaign in applicable_campaigns(item, campaigns)
        if campaign.policy.required_goal_state is not None
    )


def _fail_closed(
    items: Sequence[BacklogItemView],
    base_decisions: Sequence[EligibilityDecision],
    campaigns: Sequence[CampaignDefinition],
) -> list[EligibilityDecision]:
    """Without a reader the required Goal state cannot be observed, so items
    under a narrowing campaign stay ineligible instead of silently bypassing
    the check."""
    return [
        _decision(
            item,
            eligible=False
            if (unreadable := _unreadable_goal_reasons(item, campaigns))
            else base.eligible,
            reasons=base.reasons + unreadable,
            mode=base.effective_mode,
            versions=base.campaign_versions,
        )
        for item, base in zip(items, base_decisions, strict=True)
    ]


async def _goal_state_decision(
    reader: GoalReader,
    item: BacklogItemView,
    base: EligibilityDecision,
    campaigns: Sequence[CampaignDefinition],
) -> EligibilityDecision:
    """Re-check one base decision against the linked Goal's observed state.

    The Goal is read by ``goal_id``/``goal_revision``; the observed state is
    returned in the decision's reasons as audit evidence and is never copied
    into campaign or item state (AC-4)."""
    if not base.eligible:
        return base
    required = _required_states(item, campaigns)
    if not required:
        return base
    reached = applicable_campaigns(item, campaigns)
    observed = await _read_goal_state(reader, item)
    mismatches = sorted(
        f"campaign:{campaign.campaign_id}:goal-state-mismatch"
        for campaign in reached
        if campaign.policy.required_goal_state is not None
        and observed != campaign.policy.required_goal_state
    )
    return _decision(
        item,
        eligible=not mismatches,
        reasons=base.reasons
        + mismatches
        + ([f"goal-state-observed:{observed}"] if observed is not None else []),
        mode=base.effective_mode,
        versions=base.campaign_versions,
    )


async def evaluate_items(
    *,
    actor: Actor,
    items: Sequence[BacklogItemView],
    campaigns: Sequence[CampaignDefinition],
    item_records: Mapping[str, ItemPolicyRecord],
    controls: Sequence[ControlRecord],
    parks: Sequence[ParkRecord],
    usage: Mapping[str, BudgetUsage],
    can_actor_access: Callable[[BacklogItemView], bool],
    goal_reader: GoalReader | None = None,
) -> list[EligibilityDecision]:
    """Decide every item's eligibility, reading linked Goal state through the
    read-only reader when a campaign requires it (AC-4)."""
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
        return _fail_closed(items, base_decisions, campaigns)

    return [
        await _goal_state_decision(goal_reader, item, base, campaigns)
        for item, base in zip(items, base_decisions, strict=True)
    ]


def _selection_key(candidate: RankedCandidate) -> tuple[float, float, float, float, str]:
    """``campaign-selection-rule-v1`` order: pin-next first, then explicit
    human priority, then system score, then item id (AC-3)."""
    priority = candidate.human_priority
    return (
        -float(candidate.pinned),
        # An explicit human instruction outranks silence.
        0.0 if priority is not None else 1.0,
        -(priority if priority is not None else 0.0),
        -candidate.score,
        candidate.item_id,
    )


def _pinned_ids(controls: Sequence[ControlRecord]) -> set[str]:
    """Items an active pin-next names; a pin outranks the score (AC-3, AC-5)."""
    return {
        control.item_id
        for control in controls
        if control.active and control.kind is ControlKind.PIN_NEXT and control.item_id is not None
    }


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
    pinned_ids = _pinned_ids(controls)
    candidates: list[RankedCandidate] = []
    for decision in eligible:
        if not decision.eligible:
            continue
        if actor.kind == ActorKind.AGENT and decision.effective_mode is AutonomyMode.HUMAN_ONLY:
            continue
        item_record = item_records.get(decision.item_id)
        priority = item_record.human_priority if item_record is not None else None
        score, measured = score_item(signals.get(decision.item_id))
        candidates.append(
            RankedCandidate(
                item_id=decision.item_id,
                rank=0,
                human_priority=priority,
                score=score,
                score_inputs=measured,
                effective_mode=decision.effective_mode,
                pinned=decision.item_id in pinned_ids,
            )
        )
    candidates.sort(key=_selection_key)
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
