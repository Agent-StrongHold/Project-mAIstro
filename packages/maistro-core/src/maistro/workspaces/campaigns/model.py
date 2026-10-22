"""Durable records for Workspace work campaigns (SPEC-092626-1831, #103).

A campaign is **versioned operator policy that narrows** which BacklogItems and
linked canonical Goals an already-authorized actor may choose. It never grants
a permission, never owns or reassigns a Goal, and never schedules or executes
work: the canonical ``Goal -> Graph -> Run -> NodeRun -> Attempt`` spine is the
only execution identity, and authorization stays with its existing owners
(`maistro.workspaces` membership, `maistro.projects` scope, Sentinel,
capability grants). Every type here is a *record* about choices — not a
lifecycle. There is deliberately no campaign "status" enum: a campaign is
paused exactly while an active ``pause`` control exists, and nothing else owns
work-state.

Two inputs stay separate by construction (AC-3):

* **explicit human priority** — stored as given on
  :class:`ItemPolicyRecord`, never rewritten by the system; and
* **the system selection score** — computed only at selection time from
  :class:`SelectionSignals`, where an unmeasured signal is *absent*, never
  zero (ADR-083026-a91e).

Implementation defaults for the spec's open questions, recorded here because
code cannot ship an "open":

* **Q1** — ``campaign-selection-rule-v1``: pin-next first, then explicit human
  priority as a hard override tier, then system score, then ``item_id`` for
  determinism.
* **Q2** — an item with no explicit mode gets the campaign's
  ``default_autonomy_mode`` (``autonomous`` unless the operator tightens it).
* **Q3** — applicable campaigns intersect (each only ever narrows); a budget
  reached in *any* applicable campaign stops **new** selections only.
* **Q4** — campaign, per-item mode/priority and park records live in the
  campaign store, keyed by ``item_id``. Nothing is written onto a BacklogItem
  (#98) and no Goal field is ever copied.
* **Q5** — un-parking is an attributed human decision only; this contract does
  not auto-unpark when a recorded blocker clears.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return uuid.uuid4().hex


class AutonomyMode(StrEnum):
    """The one mode an item carries under a campaign, verbatim from #103."""

    AUTONOMOUS = "autonomous"
    AUTONOMOUS_WITH_PROMOTION_APPROVAL = "autonomous-with-promotion-approval"
    HUMAN_REVIEW_REQUIRED = "human-review-required"
    HUMAN_ONLY = "human-only"


class ControlKind(StrEnum):
    """The durable operator controls. Each is an attributed record, not
    process memory, so every one survives a restart by construction."""

    PIN_NEXT = "pin-next"
    PAUSE = "pause"
    EXCLUDE = "exclude"
    HUMAN_ONLY = "human-only"


class ActorKind(StrEnum):
    USER = "user"
    AGENT = "agent"


class Actor(BaseModel):
    """Who made a decision. Every campaign, eligibility, selection, control
    and park record carries one (invariant 3)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ActorKind = ActorKind.USER
    id: str

    @field_validator("id")
    @classmethod
    def _require_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("actor id must be a non-empty string")
        return value


class AreaRef(BaseModel):
    """One declared area — a path, a package or another resource — used both
    for a campaign's protected areas and for an item's declared scope."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["path", "package", "resource"]
    value: str

    @field_validator("value")
    @classmethod
    def _require_value(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("area value must be a non-empty string")
        return value


class CampaignConstraints(BaseModel):
    """What an item must look like to be eligible. A declared axis narrows:
    an item must match **every** axis the campaign declares. An axis left
    empty constrains nothing."""

    model_config = ConfigDict(extra="forbid")

    tags: list[str] = Field(default_factory=list)
    milestones: list[str] = Field(default_factory=list)
    packages: list[str] = Field(default_factory=list)
    #: Workspace scope. Empty means every Workspace the campaign reaches.
    workspace_ids: list[str] = Field(default_factory=list)
    #: Project scope inside the Workspace. Empty means every Project.
    project_ids: list[str] = Field(default_factory=list)


class CampaignBudgets(BaseModel):
    """Cost / time / completion budgets. Each acts as a stop condition on
    **new selections** once reached; work already in progress is untouched
    (Q3 default). Counters are observed usage recorded through the store with
    its own attributed decision — a budget is never a permission."""

    model_config = ConfigDict(extra="forbid")

    max_cost_usd: float | None = Field(default=None, gt=0)
    max_minutes: float | None = Field(default=None, gt=0)
    max_completions: int | None = Field(default=None, gt=0)


class BudgetUsage(BaseModel):
    """Observed consumption against a campaign's budgets."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cost_usd: float = 0.0
    minutes: float = 0.0
    completions: int = 0


class CampaignPolicy(BaseModel):
    """The versioned payload of one campaign."""

    model_config = ConfigDict(extra="forbid")

    constraints: CampaignConstraints = Field(default_factory=CampaignConstraints)
    budgets: CampaignBudgets = Field(default_factory=CampaignBudgets)
    #: Items whose declared scope includes one of these areas are never
    #: eligible for automated selection. Runtime enforcement once a Run starts
    #: stays with Sentinel and the capability grants; a campaign adds none.
    protected_areas: list[AreaRef] = Field(default_factory=list)
    #: Linked-Goal eligibility (AC-4): when set, an item is eligible only if
    #: its linked Goal (read by ``goal_id``/``goal_revision`` through a
    #: read-only reader) is in this state. The state is read, never copied.
    required_goal_state: str | None = None
    #: Q2 default: the mode an item carries when nothing more specific is set.
    default_autonomy_mode: AutonomyMode = AutonomyMode.AUTONOMOUS


class CampaignDefinition(BaseModel):
    """One version of one campaign. Every policy change creates a new
    ``policy_version``; earlier versions are kept for audit (invariant 3)."""

    model_config = ConfigDict(extra="forbid")

    campaign_id: str = Field(default_factory=_new_id)
    workspace_id: str
    #: When set, the campaign reaches only this Project inside the Workspace.
    project_id: str | None = None
    name: str
    policy_version: int = 1
    policy: CampaignPolicy = Field(default_factory=CampaignPolicy)
    created_by: Actor
    created_at: datetime = Field(default_factory=_now)
    #: The version this record superseded, for lineage in the audit trail.
    superseded_version: int | None = None

    @field_validator("workspace_id", "name")
    @classmethod
    def _require_campaign_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be a non-empty string")
        return value


class ControlRecord(BaseModel):
    """pin-next / pause / exclude / human-only, written identically by the UI
    and the API, attributed, and durable. Clearing is its own decision, not a
    deletion: ``cleared_at``/``cleared_by`` record it (invariant 3)."""

    model_config = ConfigDict(extra="forbid")

    control_id: str = Field(default_factory=_new_id)
    campaign_id: str
    kind: ControlKind
    #: ``None`` for a campaign-wide pause; item-scoped otherwise.
    item_id: str | None = None
    set_by: Actor
    set_at: datetime = Field(default_factory=_now)
    policy_version: int
    cleared_at: datetime | None = None
    cleared_by: Actor | None = None

    @model_validator(mode="after")
    def _scope_matches_kind(self) -> ControlRecord:
        if self.kind is ControlKind.PAUSE:
            return self
        if self.item_id is None:
            raise ValueError(f"{self.kind.value} control must name an item_id")
        return self

    @property
    def active(self) -> bool:
        return self.cleared_at is None


class ItemPolicyRecord(BaseModel):
    """Per-item campaign state: explicit human priority and mode override.

    These live beside the campaign, keyed by ``item_id`` (Q4) — they are never
    written onto the BacklogItem, which #98 owns. ``human_priority`` is stored
    exactly as a person set it and is never rewritten by the system."""

    model_config = ConfigDict(extra="forbid")

    campaign_id: str
    item_id: str
    mode_override: AutonomyMode | None = None
    human_priority: float | None = None
    updated_by: Actor
    updated_at: datetime = Field(default_factory=_now)
    policy_version: int


class ParkEvidence(BaseModel):
    """Why an item is parked: the reason, the blocking dependency or failing
    check, and Run/artifact references (AC-6)."""

    model_config = ConfigDict(extra="forbid")

    reason: str
    blocking_dependency: str | None = None
    failing_check: str | None = None
    #: References into the canonical spine — a Run id, artifact ids. Evidence
    #: only; parking follows none of them.
    run_reference: str | None = None
    artifact_references: list[str] = Field(default_factory=list)

    @field_validator("reason")
    @classmethod
    def _require_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("park evidence requires a reason")
        return value


class ParkUnpark(BaseModel):
    unparked_by: Actor
    unparked_at: datetime = Field(default_factory=_now)
    policy_version: int


class ParkRecord(BaseModel):
    """A parked item with its evidence. Parking removes the item from the
    eligible set until an attributed decision un-parks it (Q5: a person —
    this contract does not auto-unpark) and never touches the linked
    Goal's state or owner."""

    model_config = ConfigDict(extra="forbid")

    park_id: str = Field(default_factory=_new_id)
    campaign_id: str
    item_id: str
    evidence: ParkEvidence
    parked_by: Actor
    parked_at: datetime = Field(default_factory=_now)
    policy_version: int
    unparked: ParkUnpark | None = None

    @property
    def active(self) -> bool:
        return self.unparked is None


class BacklogItemView(BaseModel):
    """The read-only slice of a BacklogItem a campaign may look at (#98 owns
    the item itself). Frozen: a campaign reads these fields and writes
    nothing back — adding no BacklogItem semantics is the spec's non-goal."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    item_id: str
    workspace_id: str
    project_id: str | None = None
    tags: frozenset[str] = Field(default_factory=frozenset)
    milestone: str | None = None
    package: str | None = None
    #: Linked canonical Goal. Read by the eligibility policy through a
    #: read-only reader; never written and never copied anywhere.
    goal_id: str | None = None
    goal_revision: str | None = None
    #: The item's declared scope, matched against a campaign's protected
    #: areas (AC-1).
    declared_areas: list[AreaRef] = Field(default_factory=list)

    @field_validator("item_id", "workspace_id")
    @classmethod
    def _require_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be a non-empty string")
        return value


class SelectionSignals(BaseModel):
    """System score inputs (AC-3). Every field optional: an unmeasured signal
    is absent from the score, never zero (ADR-083026-a91e)."""

    model_config = ConfigDict(extra="forbid")

    criticality: float | None = None
    unblock_value: float | None = None
    verification_confidence: float | None = None
    expected_learning_value: float | None = None
    cost: float | None = None
    risk: float | None = None
    dependency_readiness: float | None = None


class AuditKind(StrEnum):
    """What kind of decision an audit record carries."""

    CAMPAIGN_CREATED = "campaign.created"
    POLICY_UPDATED = "policy.updated"
    CONTROL_SET = "control.set"
    CONTROL_CLEARED = "control.cleared"
    ITEM_RECORD_SET = "item.record.set"
    ITEM_PARKED = "item.parked"
    ITEM_UNPARKED = "item.unparked"
    USAGE_RECORDED = "usage.recorded"
    ELIGIBILITY_EVALUATED = "eligibility.evaluated"
    SELECTION_DECIDED = "selection.decided"
    ITEM_CLAIMED = "item.claimed"


class CampaignAuditRecord(BaseModel):
    """The audit key every decision carries (invariant 3): the actor and the
    ``policy_version`` it was made under, plus what happened and when."""

    model_config = ConfigDict(extra="forbid")

    seq: int | None = None
    at: datetime = Field(default_factory=_now)
    actor: Actor
    kind: AuditKind
    policy_version: int
    campaign_id: str | None = None
    item_id: str | None = None
    #: Kind-specific payload: reasons, inputs, restored modes, references.
    payload: dict[str, object] = Field(default_factory=dict)
