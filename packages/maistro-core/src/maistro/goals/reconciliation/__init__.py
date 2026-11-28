"""Goal reconciliation control loop (M3 #806/#805).

This subpackage owns the Workspace Agent reconciliation loop: durable
wakeups, one claim/lease/fence per Goal, idempotent decisions, bounded
sweeps, and restart-safe convergence (the *mechanics*, #806) plus the
production decision semantics composed onto them (``production.py``, the
#805 decide-half and its physical admitter). It is not a second scheduler,
execution authority, or execution queue: physical work stays canonical
``Goal -> Graph -> Run -> NodeRun -> Attempt`` (SPEC-177), and every control
record here is derived metadata about which reconciler may act for a Goal
and when.

The Goal *ontology* itself lives one level up in ``maistro.goals`` (#1572,
the canonical durable Goal store); this control plane composes over Goal
identity and never redefines the concept.
"""

from maistro.goals.reconciliation.model import (
    Goal,
    GoalAdmission,
    GoalClaim,
    GoalFacts,
    GoalStatus,
    WakeFact,
    WakeReason,
)
from maistro.goals.reconciliation.production import (
    DISCOVERY_CORRELATION,
    GOAL_RECONCILIATION_AGENT,
    FactDrivenReconciliationPolicy,
    GoalDelegationUnsupported,
    GoalPursuitUnresolvable,
    GoalRunAdmitter,
)
from maistro.goals.reconciliation.reconciler import (
    GoalReconciler,
    PlannedAdmission,
    PolicyDecision,
    ReconciliationOutcome,
    ReconciliationPolicy,
)
from maistro.goals.reconciliation.store import (
    GoalBudgetExhausted,
    GoalCancelled,
    GoalDeadlinePassed,
    GoalReconciliationStore,
    InMemoryGoalStore,
    SqliteGoalStore,
    StaleGoalFence,
)
from maistro.goals.reconciliation.wiring import (
    GOAL_WAKE_PATTERNS,
    wake_reason_for_event,
)

__all__ = [
    "DISCOVERY_CORRELATION",
    "GOAL_RECONCILIATION_AGENT",
    "GOAL_WAKE_PATTERNS",
    "FactDrivenReconciliationPolicy",
    "Goal",
    "GoalAdmission",
    "GoalBudgetExhausted",
    "GoalCancelled",
    "GoalClaim",
    "GoalDeadlinePassed",
    "GoalDelegationUnsupported",
    "GoalFacts",
    "GoalPursuitUnresolvable",
    "GoalReconciler",
    "GoalReconciliationStore",
    "GoalRunAdmitter",
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
