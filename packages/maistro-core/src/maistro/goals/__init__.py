"""Canonical Goal reconciliation control-loop mechanics (M3 #806).

This package owns the *mechanics* of the Workspace Agent reconciliation loop:
durable wakeups, one claim/lease/fence per Goal, idempotent decisions,
bounded sweeps, and restart-safe convergence. It does not own what a
reconciliation *decision* means (#805) and it is not a second scheduler,
execution authority, or execution queue: physical work stays canonical
``Goal -> Graph -> Run -> NodeRun -> Attempt`` (SPEC-177), and this module
only records derived control metadata about which reconciler may act for a
Goal and when.
"""

from maistro.goals.model import (
    Goal,
    GoalAdmission,
    GoalClaim,
    GoalFacts,
    GoalStatus,
    WakeFact,
    WakeReason,
)
from maistro.goals.reconciler import (
    GoalReconciler,
    PlannedAdmission,
    PolicyDecision,
    ReconciliationOutcome,
    ReconciliationPolicy,
)
from maistro.goals.store import (
    GoalBudgetExhausted,
    GoalCancelled,
    GoalDeadlinePassed,
    GoalReconciliationStore,
    InMemoryGoalStore,
    SqliteGoalStore,
    StaleGoalFence,
)
from maistro.goals.wiring import GOAL_WAKE_PATTERNS, wake_reason_for_event

__all__ = [
    "GOAL_WAKE_PATTERNS",
    "Goal",
    "GoalAdmission",
    "GoalAlreadyClaimed",
    "GoalBudgetExhausted",
    "GoalCancelled",
    "GoalClaim",
    "GoalDeadlinePassed",
    "GoalFacts",
    "GoalReconciler",
    "GoalReconciliationStore",
    "GoalStatus",
    "InMemoryGoalStore",
    "PlannedAdmission",
    "PolicyDecision",
    "ReconciliationOutcome",
    "ReconciliationPolicy",
    "SqliteGoalStore",
    "StaleGoalFence",
    "WakeFact",
    "WakeReason",
    "wake_reason_for_event",
]
