"""Canonical Event → Goal-wake mapping (M3 #806).

A canonical Goal revision change, Run terminal transition, delegated-Subgoal
transition, HITL resolution, or relevant artifact/evidence update can wake
the owning Workspace Agent. The mapping is *declarative data* (like the
reactor's trigger patterns, ADR-086): this module translates a canonical
:class:`~maistro.events.envelope.EventEnvelope` into a durable wake fact —
it never carries execution and never bypasses the reconciliation claim.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from maistro.goals.reconciliation.model import WakeFact, WakeReason, wake_id_for
from maistro.goals.reconciliation.store import (
    GoalReconciliationStore,
    InMemoryGoalStore,
    SqliteGoalStore,
)

if TYPE_CHECKING:
    from maistro.goals.reconciliation.reconciler import GoalReconciler

logger = logging.getLogger(__name__)

__all__ = [
    "GOAL_WAKE_PATTERNS",
    "EventWakeBridge",
    "goal_id_of_event",
    "wake_reason_for_event",
    "wire_goal_reconciliation",
]

GOAL_WAKE_PATTERNS: dict[str, tuple[WakeReason, bool]] = {
    # canonical event type -> (wake reason, unblocks a sleeping Goal)
    "goal.changed": (WakeReason.GOAL_REVISION, True),
    "run.terminal": (WakeReason.RUN_TERMINAL, True),
    "goal.subgoal.transition": (WakeReason.SUBGOAL_TRANSITION, True),
    "goal.hitl.resolved": (WakeReason.HITL_RESOLVED, True),
    "goal.evidence.updated": (WakeReason.EVIDENCE_UPDATED, True),
}
"""The canonical event types that may wake a Goal's reconciler.

Extending this table is the only way a new canonical change joins the
reconciliation control loop; there is no side channel.
"""


def wake_reason_for_event(event_type: str) -> WakeReason | None:
    """The wake reason for a canonical event type, or ``None`` if it never wakes."""
    entry = GOAL_WAKE_PATTERNS.get(event_type)
    return entry[0] if entry else None


def goal_id_of_event(event: Any) -> str | None:
    """Extract the Goal a canonical event is correlated to, if any.

    Canonical Events name their Goal in the payload (``goal_id``) per the
    interop ontology's ``goal_run_evidence`` / ``agent_goal_ownership``
    relationships; events without a Goal correlation wake nothing.
    """
    payload = getattr(event, "payload", None)
    if isinstance(payload, dict):
        goal_id = payload.get("goal_id")
        if isinstance(goal_id, str) and goal_id:
            return goal_id
    return None


class EventWakeBridge:
    """Turns canonical Events into deduplicated durable wake facts.

    Wired by the composition root as the Goal-facing consumer of the
    canonical event plane (ADR-086); duplicate/replayed delivery of the same
    ``event_id`` collapses to one wake fact in the store.
    """

    def __init__(self, reconciler: GoalReconciler) -> None:
        self._reconciler = reconciler

    async def handle(self, event: Any) -> WakeFact | None:
        """Record the wake for one canonical Event; ``None`` when irrelevant."""
        reason = wake_reason_for_event(getattr(event, "type", ""))
        goal_id = goal_id_of_event(event)
        if reason is None or goal_id is None:
            return None
        entry = GOAL_WAKE_PATTERNS[event.type]
        created = await self._reconciler.wake(
            goal_id,
            reason=reason,
            correlation_id=event.event_id,
            unblocks=entry[1],
        )
        if not created:
            return None
        return WakeFact(
            wake_id=wake_id_for(goal_id, event.event_id),
            goal_id=goal_id,
            reason=reason,
            correlation_id=event.event_id,
            unblocks=entry[1],
        )


async def wire_goal_reconciliation(
    *, pg_pool: Any = None, db_pool: Any = None
) -> GoalReconciliationStore:
    """Select the Goal reconciliation store from the container's backend.

    The SQLite twin is the one durable backend: ``quality/durable-table-``
    ``retention.json`` scopes this control plane's tables (``goals``/``goal_``
    ``claims``/``goal_wakes``/``goal_admissions``) to SQLite, and two MAIstro
    processes sharing the database file fence each other through ``BEGIN
    IMMEDIATE`` compare-and-set. A PostgreSQL pool does **not** get a durable
    twin yet — no PostgreSQL implementation of this control plane exists in
    tree (unlike the canonical Event plane, whose #122 wiring selects a real
    ``PgEventStore`` under a pool) — so the pool is answered with the
    in-memory twin and a loud warning: claim/lease, wake and admission facts
    stay process-local there, cannot fence a second process, and are lost on
    restart. The warning says so at wiring time, not after a restart drops
    them. Landing the PostgreSQL twin is the tracked durable-backend
    follow-up for #806's control plane (#1572 owns the canonical Goal PG
    store this plane deliberately does not re-implement).
    """
    if pg_pool is not None:
        logger.warning(
            "Goal reconciliation is in-memory despite a PostgreSQL backend: the Goal, "
            "claim/lease, wake and admission facts are lost on restart and cannot fence "
            "a second process. No PostgreSQL implementation of this control plane "
            "exists yet (#1572 owns the canonical Goal PG store, not this one)."
        )
        return InMemoryGoalStore()
    if db_pool is not None:
        store = SqliteGoalStore(db_pool)
        await store.ensure_schema()
        return store
    return InMemoryGoalStore()
