"""Workspace work campaigns (SPEC-092626-1831, #103, ADR-092626-c1e7).

Versioned operator policy that **narrows** which BacklogItems and linked
canonical Goals an already-authorized actor may choose. The contract never
grants a permission, never owns or reassigns a Goal, never schedules or
executes work, and never adds a lifecycle beside Goal and Run. Consumers:
the persistent Workspace Agent (#804) now, RSI (#50) later — both consume
this one contract; neither defines a private campaign model.
"""

from maistro.workspaces.campaigns.model import (
    Actor,
    ActorKind,
    AreaRef,
    AuditKind,
    AutonomyMode,
    BacklogItemView,
    BudgetUsage,
    CampaignAuditRecord,
    CampaignBudgets,
    CampaignConstraints,
    CampaignDefinition,
    CampaignPolicy,
    ControlKind,
    ControlRecord,
    ItemPolicyRecord,
    ParkEvidence,
    ParkRecord,
    ParkUnpark,
    SelectionSignals,
)
from maistro.workspaces.campaigns.policy import (
    ORDER_RULE_VERSION,
    SCORE_RULE_VERSION,
    EligibilityDecision,
    GoalReader,
    RankedCandidate,
    evaluate_items,
    order_candidates,
    score_item,
)
from maistro.workspaces.campaigns.store import (
    CampaignNotFound,
    CampaignSelector,
    CampaignStore,
    ControlNotFound,
    InMemoryCampaignStore,
    ParkNotFound,
)

__all__ = [
    "ORDER_RULE_VERSION",
    "SCORE_RULE_VERSION",
    "Actor",
    "ActorKind",
    "AreaRef",
    "AuditKind",
    "AutonomyMode",
    "BacklogItemView",
    "BudgetUsage",
    "CampaignAuditRecord",
    "CampaignBudgets",
    "CampaignConstraints",
    "CampaignDefinition",
    "CampaignNotFound",
    "CampaignPolicy",
    "CampaignSelector",
    "CampaignStore",
    "ControlKind",
    "ControlNotFound",
    "ControlRecord",
    "EligibilityDecision",
    "GoalReader",
    "InMemoryCampaignStore",
    "ItemPolicyRecord",
    "ParkEvidence",
    "ParkNotFound",
    "ParkRecord",
    "ParkUnpark",
    "RankedCandidate",
    "SelectionSignals",
    "evaluate_items",
    "order_candidates",
    "score_item",
]
