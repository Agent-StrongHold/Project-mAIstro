"""create_container() wiring for the Goal reconciliation control plane (#806).

The mechanics module is production composition, not a library orphan: the
Container owns the durable store on the same backend the Runs use, reclaims
lapsed Goal leases policy-free, and runs the bounded reconciliation sweep only
under a #805-composed policy — never inventing decision semantics here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from maistro.container import Container, create_container
from maistro.goals import Goal, GoalFacts, PlannedAdmission, PolicyDecision, WakeReason
from maistro.goals.wiring import wire_goal_reconciliation
from maistro.types.config import AgentConfig


async def _container(**overrides: object) -> Container:
    return await create_container(AgentConfig(router_api_key="test-key", **overrides))  # type: ignore[arg-type]


class StubPolicy:
    """Minimal #805 stand-in: admit one decision key per pass."""

    def __init__(self, key: str = "dec-1") -> None:
        self._key = key

    async def decide(self, facts: GoalFacts) -> PolicyDecision:
        return PolicyDecision(admissions=(PlannedAdmission(kind="run", decision_key=self._key),))


# --- backend selection -------------------------------------------------------


async def test_container_wires_the_goal_reconciliation_control_plane() -> None:
    container = await _container()
    assert type(container.goal_reconciliation_store).__name__ == "InMemoryGoalStore"
    assert container.goal_reconciliation_policy is None, (
        "the Container never invents #805's decision semantics"
    )


async def test_sqlite_backend_wires_the_durable_goal_store() -> None:
    container = await _container(database_url="sqlite://")
    assert type(container.goal_reconciliation_store).__name__ == "SqliteGoalStore"
    store = container.goal_reconciliation_store
    await store.create_goal(Goal(goal_id="g-wired", workspace_id="ws", project_id="p"))
    view = await store.reconciliation_view("g-wired")
    assert view is not None and view["goal_id"] == "g-wired"


async def test_pg_pool_falls_back_to_memory_with_a_loud_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    with caplog.at_level(logging.WARNING, logger="maistro.goals.wiring"):
        store = await wire_goal_reconciliation(pg_pool=object())
    assert type(store).__name__ == "InMemoryGoalStore"
    assert any("#1572" in record.getMessage() for record in caplog.records)


# --- policy-free fence recovery ---------------------------------------------


async def test_sweep_goal_leases_reclaims_only_lapsed_claims() -> None:
    container = await _container()
    store = container.goal_reconciliation_store
    past = datetime.now(UTC) - timedelta(seconds=60)
    await store.create_goal(Goal(goal_id="g-lapsed", workspace_id="ws", project_id="p"))
    stale = await store.claim(
        "g-lapsed", holder="dead-process", ttl=timedelta(seconds=30), now=past
    )
    assert stale is not None
    await store.create_goal(Goal(goal_id="g-live", workspace_id="ws", project_id="p"))
    live = await store.claim("g-live", holder="alive", ttl=timedelta(seconds=30))
    assert live is not None

    assert await container.sweep_goal_leases() == 1

    # The dead holder's fence is gone (a takeover claim succeeds); the live
    # holder's fence still excludes a challenger.
    assert await store.claim("g-lapsed", holder="new-process") is not None
    assert await store.claim("g-live", holder="challenger") is None


# --- policy-gated reconciliation ---------------------------------------------


async def test_reconcile_goals_without_a_policy_decides_nothing() -> None:
    container = await _container()
    store = container.goal_reconciliation_store
    await store.create_goal(Goal(goal_id="g-inert", workspace_id="ws", project_id="p"))
    assert await container.reconcile_goals() == 0
    view = await store.reconciliation_view("g-inert")
    assert view is not None and view["admissions_total"] == 0


async def test_reconcile_goals_repairs_a_missed_wake_under_a_policy() -> None:
    container = await _container()
    store = container.goal_reconciliation_store
    await store.create_goal(Goal(goal_id="g-tick", workspace_id="ws", project_id="p"))
    # A canonical change was recorded durably, then the notifying process
    # died: nobody re-delivers. The bounded tick alone must repair it.
    await store.record_wake(
        "g-tick",
        reason=WakeReason.RUN_TERMINAL,
        correlation_id="event-1",
        unblocks=True,
    )
    container.goal_reconciliation_policy = StubPolicy()  # type: ignore[assignment]

    assert await container.reconcile_goals() == 1

    view = await store.reconciliation_view("g-tick")
    assert view is not None
    assert view["admissions_total"] == 1
    assert view["pending_wakes"] == 0
    # Idempotent across ticks: the same durable facts re-decide nothing new.
    assert await container.reconcile_goals() == 0


async def test_composed_policy_admission_is_fenced_and_idempotent() -> None:
    container = await _container()
    store = container.goal_reconciliation_store
    await store.create_goal(Goal(goal_id="g-fence", workspace_id="ws", project_id="p"))
    container.goal_reconciliation_policy = StubPolicy()  # type: ignore[assignment]
    assert await container.reconcile_goals() == 0, "no wake, nothing to decide yet"

    await store.record_wake(
        "g-fence",
        reason=WakeReason.GOAL_REVISION,
        correlation_id="event-2",
        unblocks=True,
    )
    assert await container.reconcile_goals() == 1
    # A replayed wake (same correlation) collapses; nothing double-admits.
    await store.record_wake(
        "g-fence",
        reason=WakeReason.GOAL_REVISION,
        correlation_id="event-2",
        unblocks=True,
    )
    assert await container.reconcile_goals() == 0
    view = await store.reconciliation_view("g-fence")
    assert view is not None and view["admissions_total"] == 1
