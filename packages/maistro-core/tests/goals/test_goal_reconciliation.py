"""Acceptance tests for durable, event-driven, fenced Goal reconciliation (#806).

Each test class maps to one acceptance criterion of M3 #806. Both store
twins (in-memory, SQLite) must enforce the same mechanics; the SQLite
concurrency tests use two independent connections on one database file to
stand in for two MAIstro processes.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from maistro.events.envelope import EventEnvelope
from maistro.goals.reconciliation import (
    GOAL_WAKE_PATTERNS,
    Goal,
    GoalReconciler,
    GoalStatus,
    InMemoryGoalStore,
    PlannedAdmission,
    PolicyDecision,
    SqliteGoalStore,
    StaleGoalFence,
    WakeReason,
)
from maistro.goals.reconciliation.model import GoalFacts, coerce_datetime
from maistro.goals.reconciliation.store import (
    GoalBudgetExhausted,
    GoalCancelled,
    GoalDeadlinePassed,
    GoalReconciliationError,
    _check_gates,
)
from maistro.goals.reconciliation.wiring import (
    EventWakeBridge,
    goal_id_of_event,
    wake_reason_for_event,
)

T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def make_goal(goal_id: str = "g-1", **overrides: Any) -> Goal:
    return Goal(goal_id=goal_id, workspace_id="ws-1", project_id="p-1", **overrides)


class StubPolicy:
    """The #805-owned decision semantics, stubbed for mechanics tests."""

    def __init__(self, plan: Callable[[GoalFacts], PolicyDecision]) -> None:
        self._plan = plan
        self.calls = 0
        self.facts: list[GoalFacts] = []

    async def decide(self, facts: GoalFacts) -> PolicyDecision:
        self.calls += 1
        self.facts.append(facts)
        return self._plan(facts)


class StubAdmitter:
    """Creates the canonical artifact; can be told to crash at will."""

    def __init__(self, fail_keys: set[str] | None = None) -> None:
        self.fail_keys = fail_keys or set()
        self.calls: list[str] = []

    async def admit(self, admission: Any) -> str:
        self.calls.append(admission.decision_key)
        if admission.decision_key in self.fail_keys:
            raise RuntimeError(f"forced crash after decision {admission.decision_key!r}")
        return f"run-for-{admission.decision_key}"


@pytest.fixture(params=["memory", "sqlite"])
async def store(request: Any):
    if request.param == "memory":
        yield InMemoryGoalStore()
        return
    import aiosqlite

    conn = await aiosqlite.connect(":memory:")
    try:
        sqlite_store = SqliteGoalStore(conn)
        await sqlite_store.ensure_schema()
        yield sqlite_store
    finally:
        await conn.close()


def run_policy(key: str = "dec-1") -> StubPolicy:
    return StubPolicy(
        lambda facts: PolicyDecision(admissions=(PlannedAdmission(kind="run", decision_key=key),))
    )


def make_event(event_type: str, goal_id: str | None, event_id: str) -> EventEnvelope:
    return EventEnvelope(
        type=event_type, payload={"goal_id": goal_id}, event_id=event_id, workspace_id="ws-1"
    )


# ---------------------------------------------------------------------------
# AC 1 — two concurrent MAIstro processes cannot both admit next work
# ---------------------------------------------------------------------------


class TestTwoProcessesCannotBothAct:
    async def test_second_holder_gets_no_claim_and_cannot_admit(self, store: Any) -> None:
        await store.ensure_schema()
        await store.create_goal(make_goal())
        claim_a = await store.claim("g-1", holder="process-a", ttl=timedelta(seconds=30), now=T0)
        assert claim_a is not None
        claim_b = await store.claim("g-1", holder="process-b", ttl=timedelta(seconds=30), now=T0)
        assert claim_b is None, "two processes must not both hold the Goal claim"

        admission, created = await store.admit(
            "g-1",
            fencing_token=claim_a.fencing_token,
            decision_key="dec-1",
            now=T0,
        )
        assert created and admission.fence_epoch == 1
        with pytest.raises(StaleGoalFence):
            await store.admit(
                "g-1",
                fencing_token="process-b-never-had-a-token",
                decision_key="dec-2",
                now=T0,
            )
        assert (await store.get_goal("g-1")).runs_admitted == 1

    async def test_concurrent_claims_on_one_sqlite_database_elect_one_winner(
        self, tmp_path: Any
    ) -> None:
        """Two independent connections (two processes) on one database file."""
        import aiosqlite

        path = str(tmp_path / "goals.db")
        conns = [await aiosqlite.connect(path), await aiosqlite.connect(path)]
        try:
            stores = []
            for conn in conns:
                sqlite_store = SqliteGoalStore(conn)
                await sqlite_store.ensure_schema()
                stores.append(sqlite_store)
            await stores[0].create_goal(make_goal())
            results = await asyncio.gather(
                stores[0].claim("g-1", holder="process-a", ttl=timedelta(seconds=30), now=T0),
                stores[1].claim("g-1", holder="process-b", ttl=timedelta(seconds=30), now=T0),
            )
            winners = [claim for claim in results if claim is not None]
            assert len(winners) == 1
            loser_store = stores[1] if results[0] is not None else stores[0]
            with pytest.raises(StaleGoalFence):
                await loser_store.admit(
                    "g-1",
                    fencing_token="loser-token",
                    decision_key="dec-1",
                    now=T0,
                )
        finally:
            for conn in conns:
                await conn.close()

    async def test_reconciler_skips_when_another_holder_owns_the_goal(self, store: Any) -> None:
        await store.ensure_schema()
        await store.create_goal(make_goal())
        policy_b = run_policy("dec-b")
        reconciler_b = GoalReconciler(store, policy_b, holder="agent-b")

        # A holds the claim (simulating an in-flight pass); B's reconcile skips.
        claim = await store.claim("g-1", holder="agent-a", now=T0)
        assert claim is not None
        outcome_b = await reconciler_b.reconcile("g-1", now=T0)
        assert outcome_b.claimed is False
        assert policy_b.calls == 0
        assert (await store.get_goal("g-1")).runs_admitted == 0


# ---------------------------------------------------------------------------
# AC 2 — losing/expiring the claim fences the stale holder from later Runs
# ---------------------------------------------------------------------------


class TestStaleHolderFenced:
    async def test_takeover_makes_the_old_token_stale(self, store: Any) -> None:
        await store.ensure_schema()
        await store.create_goal(make_goal())
        stale = await store.claim("g-1", holder="old", ttl=timedelta(seconds=30), now=T0)
        assert stale is not None
        fresh = await store.claim(
            "g-1", holder="new", ttl=timedelta(seconds=30), now=T0 + timedelta(seconds=31)
        )
        assert fresh is not None and fresh.fence_epoch == stale.fence_epoch + 1

        with pytest.raises(StaleGoalFence):
            await store.admit(
                "g-1",
                fencing_token=stale.fencing_token,
                decision_key="dec-late",
                now=T0 + timedelta(seconds=31),
            )

    async def test_expired_claim_cannot_admit_even_without_takeover(self, store: Any) -> None:
        await store.ensure_schema()
        await store.create_goal(make_goal())
        stale = await store.claim("g-1", holder="old", ttl=timedelta(seconds=30), now=T0)
        assert stale is not None
        later = T0 + timedelta(seconds=61)
        with pytest.raises(StaleGoalFence):
            await store.admit(
                "g-1", fencing_token=stale.fencing_token, decision_key="dec-late", now=later
            )

    async def test_stale_reconciler_process_cannot_start_a_later_run(self, store: Any) -> None:
        """The stale process keeps running; its work is still refused."""
        await store.ensure_schema()
        await store.create_goal(make_goal())
        policy = run_policy("dec-late")
        stale_reconciler = GoalReconciler(
            store, policy, holder="crashed-but-alive", lease_ttl=timedelta(seconds=30)
        )
        claim = await store.claim(
            "g-1", holder="crashed-but-alive", ttl=timedelta(seconds=30), now=T0
        )
        assert claim is not None
        await store.claim(
            "g-1", holder="takeover", ttl=timedelta(seconds=30), now=T0 + timedelta(seconds=31)
        )
        # The still-running stale process tries to reconcile again.
        outcome = await stale_reconciler.reconcile("g-1", now=T0 + timedelta(seconds=32))
        assert outcome.claimed is False
        assert policy.calls == 0
        # And a direct admission attempt with its old token is fenced.
        with pytest.raises(StaleGoalFence):
            await store.admit(
                "g-1",
                fencing_token=claim.fencing_token,
                decision_key="dec-late",
                now=T0 + timedelta(seconds=32),
            )
        assert (await store.get_goal("g-1")).runs_admitted == 0


# ---------------------------------------------------------------------------
# AC 3 — duplicate/replayed Event delivery creates no duplicate work
# ---------------------------------------------------------------------------


class TestDuplicateDeliveryIsIdempotent:
    async def test_same_event_wakes_and_admits_once(self, store: Any) -> None:
        await store.ensure_schema()
        goal = await store.create_goal(make_goal())
        policy = run_policy("event-1:admit")
        admitter = StubAdmitter()
        reconciler = GoalReconciler(store, policy, holder="agent", admitter=admitter)
        bridge = EventWakeBridge(reconciler)

        event = make_event("run.terminal", goal.goal_id, "event-1")
        for _ in range(3):  # at-least-once delivery, three times
            recorded = await bridge.handle(event)
            await reconciler.reconcile(goal.goal_id)
        assert recorded is None, "replayed event must not record another wake"

        assert admitter.calls == ["event-1:admit"]
        refreshed = await store.get_goal(goal.goal_id)
        assert refreshed.runs_admitted == 1
        assert len(await store.pending_wakes(goal.goal_id)) == 0
        assert len(await store.pending_admissions()) == 0

    async def test_decision_key_replayed_after_restart_admits_once(self, store: Any) -> None:
        await store.ensure_schema()
        goal = await store.create_goal(make_goal())
        policy = run_policy("dec-x")
        admitter = StubAdmitter()
        first = GoalReconciler(store, policy, holder="agent-1", admitter=admitter)
        await first.reconcile(goal.goal_id, now=T0)
        # "Restart": a fresh reconciler replays the same decision.
        second = GoalReconciler(store, policy, holder="agent-2", admitter=admitter)
        await store.record_wake(
            goal.goal_id,
            reason=WakeReason.MANUAL,
            correlation_id="manual-1",
            now=T0 + timedelta(seconds=1),
        )
        outcome = await second.reconcile(goal.goal_id, now=T0 + timedelta(seconds=1))
        assert [a.decision_key for a in outcome.duplicates] == ["dec-x"]
        assert outcome.admissions == []
        assert admitter.calls == ["dec-x"]
        assert (await store.get_goal(goal.goal_id)).runs_admitted == 1


# ---------------------------------------------------------------------------
# AC 4 — death after decision, before/after admission, converges on restart
# ---------------------------------------------------------------------------


class TestCrashConvergence:
    async def test_crash_after_admission_record_before_artifact_repairs_once(
        self, store: Any
    ) -> None:
        await store.ensure_schema()
        goal = await store.create_goal(make_goal())
        policy = run_policy("dec-crash")
        # The process dies after the durable admission, before the artifact:
        # the crash propagates, but the admission is already durable.
        crashed = GoalReconciler(
            store,
            policy,
            holder="dies-mid-admit",
            admitter=StubAdmitter(fail_keys={"dec-crash"}),
        )
        with pytest.raises(RuntimeError, match="forced crash"):
            await crashed.reconcile(goal.goal_id, now=T0)
        pending = await store.pending_admissions(goal.goal_id)
        assert len(pending) == 1
        assert pending[0].completed_at is None

        # Restart: fresh holder, same store, durable facts only.
        admitter = StubAdmitter()
        restarted = GoalReconciler(store, policy, holder="restarted", admitter=admitter)
        repaired = await restarted.reconcile(goal.goal_id, now=T0 + timedelta(seconds=1))
        assert [a.decision_key for a in repaired.repaired] == ["dec-crash"]
        assert admitter.calls == ["dec-crash"]
        assert len(await store.pending_admissions(goal.goal_id)) == 0
        assert (await store.get_goal(goal.goal_id)).runs_admitted == 1

    async def test_crash_after_artifact_before_completion_never_duplicates(
        self, store: Any
    ) -> None:
        await store.ensure_schema()
        goal = await store.create_goal(make_goal())
        policy = run_policy("dec-y")
        admitter = StubAdmitter()

        class CrashBeforeCompleteStore:
            """Wraps the store: the process dies right after the artifact."""

            def __init__(self, inner: Any) -> None:
                self._inner = inner

            def __getattr__(self, name: str) -> Any:
                return getattr(self._inner, name)

            async def complete_admission(self, admission_id: str, **kwargs: Any) -> bool:
                raise RuntimeError(
                    f"forced crash after artifact creation ({admission_id}, {sorted(kwargs)})"
                )

        wrapper = CrashBeforeCompleteStore(store)
        crashed = GoalReconciler(wrapper, policy, holder="dies-late", admitter=admitter)
        with pytest.raises(RuntimeError, match="forced crash"):
            await crashed.reconcile(goal.goal_id, now=T0)
        assert admitter.calls == ["dec-y"]

        restarted = GoalReconciler(store, policy, holder="restarted", admitter=admitter)
        repaired = await restarted.reconcile(goal.goal_id, now=T0 + timedelta(seconds=1))
        assert [a.decision_key for a in repaired.repaired] == ["dec-y"]
        # The artifact was requested twice (crash + repair) but under the same
        # idempotent key: one admission, one lineage, no second decision.
        assert (await store.get_goal(goal.goal_id)).runs_admitted == 1
        assert len(await store.pending_admissions(goal.goal_id)) == 0

    async def test_recover_enumerates_from_durable_facts_only(self, store: Any) -> None:
        await store.ensure_schema()
        await store.create_goal(make_goal("g-live"))
        await store.create_goal(make_goal("g-done", status=GoalStatus.SETTLED))
        policy = StubPolicy(lambda facts: PolicyDecision())
        reconciler = GoalReconciler(store, policy, holder="agent")
        assert await reconciler.recover() == ["g-live"]


# ---------------------------------------------------------------------------
# AC 5 — canonical changes can trigger reconciliation
# ---------------------------------------------------------------------------


class TestCanonicalTriggersWake:
    @pytest.mark.parametrize(
        ("event_type", "expected_reason"),
        [
            ("goal.changed", WakeReason.GOAL_REVISION),
            ("run.terminal", WakeReason.RUN_TERMINAL),
            ("goal.subgoal.transition", WakeReason.SUBGOAL_TRANSITION),
            ("goal.hitl.resolved", WakeReason.HITL_RESOLVED),
            ("goal.evidence.updated", WakeReason.EVIDENCE_UPDATED),
        ],
    )
    async def test_each_canonical_change_wakes_and_reconciles(
        self, store: Any, event_type: str, expected_reason: WakeReason
    ) -> None:
        await store.ensure_schema()
        goal = await store.create_goal(make_goal())
        policy = StubPolicy(lambda facts: PolicyDecision())
        reconciler = GoalReconciler(store, policy, holder="agent", admitter=StubAdmitter())
        bridge = EventWakeBridge(reconciler)

        recorded = await bridge.handle(make_event(event_type, goal.goal_id, f"ev-{event_type}"))
        assert recorded is not None
        assert recorded.reason is expected_reason
        assert wake_reason_for_event(event_type) is expected_reason

        outcome = await reconciler.reconcile(goal.goal_id)
        assert outcome.claimed and outcome.decided
        assert len(await store.pending_wakes(goal.goal_id)) == 0, (
            "the wake must be dispatched once reconciled"
        )

    async def test_irrelevant_events_wake_nothing(self, store: Any) -> None:
        await store.ensure_schema()
        goal = await store.create_goal(make_goal())
        policy = StubPolicy(lambda facts: PolicyDecision())
        reconciler = GoalReconciler(store, policy, holder="agent")
        bridge = EventWakeBridge(reconciler)
        assert await bridge.handle(make_event("agent.chat.turn", goal.goal_id, "ev-1")) is None
        assert await bridge.handle(make_event("run.terminal", None, "ev-2")) is None
        assert policy.calls == 0
        assert GOAL_WAKE_PATTERNS["run.terminal"][0] is WakeReason.RUN_TERMINAL


# ---------------------------------------------------------------------------
# AC 6 — missed notifications repaired by a bounded safety sweep
# ---------------------------------------------------------------------------


class TestBoundedSafetySweep:
    async def test_missed_unblocking_wake_is_repaired_by_the_sweep(self, store: Any) -> None:
        """Death between recording the wake and reconciling loses nothing."""
        await store.ensure_schema()
        goal = await store.create_goal(make_goal())
        policy = run_policy("event-9:admit")
        admitter = StubAdmitter()
        # The notifier records the durable wake fact, then the process dies
        # before any reconcile pass — the Goal was never slept, so nothing
        # but the sweep's due-marking can repair it.
        notifier = GoalReconciler(store, policy, holder="notifier")
        assert (
            await notifier.wake(
                goal.goal_id,
                reason=WakeReason.RUN_TERMINAL,
                correlation_id="event-9",
                unblocks=True,
                now=T0,
            )
            is True
        )
        due = await store.due_goals(T0 + timedelta(seconds=1), limit=16)
        assert [g.goal_id for g in due] == [goal.goal_id], (
            "a recorded relevant wake marks the Goal due"
        )

        # A fresh process's bounded sweep alone repairs it: no re-delivery.
        restarted = GoalReconciler(store, policy, holder="restarted", admitter=admitter)
        repaired = await restarted.sweep(T0 + timedelta(seconds=1))
        assert [o.goal_id for o in repaired] == [goal.goal_id]
        assert repaired[0].decided
        assert admitter.calls == ["event-9:admit"]
        assert len(await store.pending_wakes(goal.goal_id)) == 0

    async def test_never_reconciled_goal_with_a_pending_wake_is_sweep_due(self, store: Any) -> None:
        await store.ensure_schema()
        goal = await store.create_goal(make_goal())
        policy = StubPolicy(lambda facts: PolicyDecision())
        reconciler = GoalReconciler(store, policy, holder="agent")
        await store.record_wake(
            goal.goal_id,
            reason=WakeReason.SAFETY_SWEEP,
            correlation_id="sw-0",
            now=T0,
        )
        outcomes = await reconciler.sweep(T0 + timedelta(seconds=1))
        assert [o.goal_id for o in outcomes] == [goal.goal_id]
        assert policy.calls == 1, "a READY Goal is not asleep; its pending wake is work"

    async def test_sleeping_goal_is_re_derived_after_its_horizon(self, store: Any) -> None:
        await store.ensure_schema()
        goal = await store.create_goal(make_goal())
        policy = StubPolicy(lambda facts: PolicyDecision())
        reconciler = GoalReconciler(
            store, policy, holder="agent", sweep_horizon=timedelta(seconds=60)
        )
        await reconciler.reconcile(goal.goal_id, now=T0)
        slept = await store.get_goal(goal.goal_id)
        assert slept.status is GoalStatus.DORMANT

        # The notification was lost (the process died before dispatch): nobody
        # re-delivers anything — the bounded sweep alone repairs it.
        lost = await reconciler.sweep(T0 + timedelta(seconds=30))
        assert lost == []
        assert policy.calls == 1
        repaired = await reconciler.sweep(T0 + timedelta(seconds=61))
        assert [o.goal_id for o in repaired] == [goal.goal_id]
        assert policy.calls == 2

    async def test_sweep_is_bounded_and_does_not_poll_every_goal(self, store: Any) -> None:
        await store.ensure_schema()
        await store.create_goal(make_goal("g-due-1", awake_after=T0 - timedelta(seconds=1)))
        await store.create_goal(make_goal("g-due-2", awake_after=T0 - timedelta(seconds=2)))
        # Not due: must not be polled by the sweep at all.
        await store.create_goal(make_goal("g-later", awake_after=T0 + timedelta(hours=1)))
        blocked = await store.create_goal(make_goal("g-blocked", status=GoalStatus.GATED))
        policy = StubPolicy(lambda facts: PolicyDecision())
        reconciler = GoalReconciler(store, policy, holder="agent")

        outcomes = await reconciler.sweep(T0, limit=1)
        # Bounded: only the most-overdue due Goal, not the whole table.
        assert [o.goal_id for o in outcomes] == ["g-due-2"]
        assert policy.calls == 1
        viewed = await store.reconciliation_view(blocked.goal_id)
        assert viewed["status"] == "gated"
        assert viewed["awake_after"] is None, "a blocked Goal is never due for the sweep"


# ---------------------------------------------------------------------------
# AC 7 — blocked / waiting-human Goals consume nothing until relevant change
# ---------------------------------------------------------------------------


class TestBlockedGoalsSleep:
    async def test_hitl_blocked_goal_consumes_no_decisions_until_resolution(
        self, store: Any
    ) -> None:
        await store.ensure_schema()
        goal = await store.create_goal(make_goal())
        state = {"blocked": True}

        def plan(facts: GoalFacts) -> PolicyDecision:
            if state["blocked"]:
                return PolicyDecision(blocked_reason="waiting for human approval")
            return PolicyDecision()

        policy = StubPolicy(plan)
        reconciler = GoalReconciler(store, policy, holder="agent")
        outcome = await reconciler.reconcile(goal.goal_id, now=T0)
        assert outcome.slept_as is GoalStatus.GATED
        assert (await store.get_goal(goal.goal_id)).status is GoalStatus.GATED
        # Safety sweeps at any later time must not consume decisions.
        for seconds in (1, 60, 3_600, 86_400):
            outcomes = await reconciler.sweep(T0 + timedelta(seconds=seconds))
            assert outcomes == []
        assert policy.calls == 1

        # The relevant state change — HITL resolution — wakes exactly once.
        bridge = EventWakeBridge(reconciler)
        await bridge.handle(make_event("goal.hitl.resolved", goal.goal_id, "ev-hitl"))
        state["blocked"] = False
        outcome = await reconciler.reconcile(goal.goal_id, now=T0 + timedelta(seconds=86_401))
        assert outcome.decided
        assert outcome.slept_as is GoalStatus.DORMANT, (
            "the unblocked pass sleeps, it did not complete"
        )
        assert policy.calls == 2

    async def test_sleeping_goal_skips_non_unblocking_wakes(self, store: Any) -> None:
        await store.ensure_schema()
        goal = await store.create_goal(make_goal())
        policy = StubPolicy(lambda facts: PolicyDecision())
        reconciler = GoalReconciler(store, policy, holder="agent")
        await reconciler.reconcile(goal.goal_id, now=T0)
        await store.record_wake(
            goal.goal_id, reason=WakeReason.SAFETY_SWEEP, correlation_id="sw-1", now=T0
        )
        outcome = await reconciler.reconcile(goal.goal_id, now=T0 + timedelta(seconds=1))
        assert outcome.skipped_asleep
        assert policy.calls == 1
        # And the sweep agrees: a non-unblocking wake never shortens the night.
        assert await reconciler.sweep(T0 + timedelta(seconds=30)) == []
        assert policy.calls == 1


# ---------------------------------------------------------------------------
# AC 8 — Goal-level budget/deadline/cancel fence admission across restarts
# ---------------------------------------------------------------------------


class TestGoalLevelStopConditions:
    async def test_budget_survives_restart_and_fences_admission(self, store: Any) -> None:
        await store.ensure_schema()
        goal = await store.create_goal(make_goal(budget_max_runs=1))
        counter = {"n": 0}

        def plan(facts: GoalFacts) -> PolicyDecision:
            counter["n"] += 1
            return PolicyDecision(
                admissions=(PlannedAdmission(kind="run", decision_key=f"dec-{counter['n']}"),)
            )

        policy = StubPolicy(plan)
        admitter = StubAdmitter()
        first = GoalReconciler(store, policy, holder="agent-1", admitter=admitter)
        await first.reconcile(goal.goal_id, now=T0)
        assert (await store.get_goal(goal.goal_id)).runs_admitted == 1

        # Restart with a fresh reconciler: the budget is durable, not
        # process-local, and still fences the second admission.
        restarted = GoalReconciler(store, policy, holder="agent-2", admitter=admitter)
        await store.record_wake(
            goal.goal_id,
            reason=WakeReason.MANUAL,
            correlation_id="manual-1",
            now=T0 + timedelta(seconds=1),
        )
        outcome = await restarted.reconcile(goal.goal_id, now=T0 + timedelta(seconds=1))
        assert outcome.error is not None and "budget exhausted" in outcome.error
        assert (await store.get_goal(goal.goal_id)).runs_admitted == 1
        assert admitter.calls == ["dec-1"]

    async def test_deadline_fences_across_restart(self, store: Any) -> None:
        await store.ensure_schema()
        goal = await store.create_goal(make_goal(deadline_at=T0))
        policy = run_policy("dec-late")
        reconciler = GoalReconciler(store, policy, holder="agent-2", admitter=StubAdmitter())
        outcome = await reconciler.reconcile(goal.goal_id, now=T0 + timedelta(seconds=1))
        assert outcome.error is not None and "deadline passed" in outcome.error
        assert (await store.get_goal(goal.goal_id)).runs_admitted == 0

    async def test_deadline_gate_is_enforced_in_the_store(self, store: Any) -> None:
        await store.ensure_schema()
        await store.create_goal(make_goal("g-deadline-gate", deadline_at=T0))
        claim = await store.claim("g-deadline-gate", holder="gate", now=T0 - timedelta(seconds=1))
        assert claim is not None
        with pytest.raises(GoalDeadlinePassed):
            await store.admit(
                "g-deadline-gate",
                fencing_token=claim.fencing_token,
                decision_key="direct",
                now=T0,
            )

    async def test_stop_condition_settles_the_goal_and_fences_everything_after(
        self, store: Any
    ) -> None:
        """``complete=True`` is the Goal-level stop condition: terminal, fenced."""
        await store.ensure_schema()
        goal = await store.create_goal(make_goal())
        policy = StubPolicy(
            lambda facts: PolicyDecision(
                admissions=(PlannedAdmission(kind="run", decision_key="dec-final"),),
                complete=True,
            )
        )
        admitter = StubAdmitter()
        reconciler = GoalReconciler(store, policy, holder="agent", admitter=admitter)
        outcome = await reconciler.reconcile(goal.goal_id, now=T0)
        assert outcome.completed is True
        assert outcome.slept_as is None, "a settled Goal never sleeps — it is terminal"
        settled = await store.get_goal(goal.goal_id)
        assert settled.status is GoalStatus.SETTLED

        # Terminal posture fences everything across restarts: no new claim,
        # no decision, no admission, even with a fresh reconciler and a wake.
        restarted = GoalReconciler(store, policy, holder="agent-2", admitter=admitter)
        await store.record_wake(
            goal.goal_id,
            reason=WakeReason.MANUAL,
            correlation_id="manual-after-settle",
            now=T0 + timedelta(seconds=1),
        )
        after = await restarted.reconcile(goal.goal_id, now=T0 + timedelta(seconds=1))
        assert after.claimed is False and after.decided is False
        assert admitter.calls == ["dec-final"]
        assert (await store.get_goal(goal.goal_id)).runs_admitted == 1

    async def test_cancel_fences_across_restart(self, store: Any) -> None:
        await store.ensure_schema()
        goal = await store.create_goal(make_goal())
        await store.cancel_goal(goal.goal_id, reason="user stop")
        policy = run_policy("dec-z")
        reconciler = GoalReconciler(store, policy, holder="agent-2", admitter=StubAdmitter())
        outcome = await reconciler.reconcile(goal.goal_id, now=T0)
        assert outcome.claimed is False, "a cancelled Goal is never claimed again"
        assert policy.calls == 0
        assert await store.claim(goal.goal_id, holder="agent-3", now=T0) is None

    async def test_cancel_gate_is_enforced_in_the_store(self) -> None:
        cancelled = make_goal("g-c", status=GoalStatus.WITHDRAWN)
        with pytest.raises(GoalCancelled):
            _check_gates(cancelled, T0)


# ---------------------------------------------------------------------------
# AC 9 — reconciliation state is inspectable derived/control metadata
# ---------------------------------------------------------------------------


class TestControlMetadataNotExecution:
    async def test_view_is_derived_control_metadata(self, store: Any) -> None:
        await store.ensure_schema()
        goal = await store.create_goal(make_goal())
        policy = run_policy("dec-1")
        reconciler = GoalReconciler(store, policy, holder="agent", admitter=StubAdmitter())
        await reconciler.reconcile(goal.goal_id, now=T0)
        view = await store.reconciliation_view(goal.goal_id)
        assert view["goal_id"] == goal.goal_id
        assert view["status"] == "dormant"
        assert view["runs_admitted"] == 1
        assert view["open_admissions"] == 0
        assert view["claim"] is None, "the claim was released with the pass"

    async def test_control_records_carry_no_execution_lifecycle(self) -> None:
        from maistro.goals.reconciliation.model import GoalAdmission, GoalClaim, WakeFact

        # None of the control records may restate Run/NodeRun/Attempt state;
        # they reference canonical artifacts, never re-own them.
        assert set(GoalAdmission.model_fields) == {
            "admission_id",
            "goal_id",
            "revision",
            "fence_epoch",
            "decision_key",
            "kind",
            "correlation_id",
            "admitted_at",
            "completed_at",
            "physical_ref",
        }
        for fields in (GoalClaim.model_fields, WakeFact.model_fields):
            assert not any(k.startswith(("run_", "node_run_", "attempt_")) for k in fields)

    async def test_store_never_creates_runs_itself(self, store: Any) -> None:
        """Admission records name canonical artifacts; they do not create them."""
        await store.ensure_schema()
        goal = await store.create_goal(make_goal())
        claim = await store.claim(goal.goal_id, holder="agent", now=T0)
        assert claim is not None
        admission, created = await store.admit(
            goal.goal_id, fencing_token=claim.fencing_token, decision_key="dec-1", now=T0
        )
        assert created
        assert admission.physical_ref is None, "no Run exists until the caller creates it"
        assert await store.complete_admission(
            admission.admission_id, physical_ref="run-123", now=T0
        )
        again = await store.complete_admission(
            admission.admission_id, physical_ref="run-999", now=T0
        )
        assert again is False, "completion is idempotent: the lineage never forks"


# ---------------------------------------------------------------------------
# AC 10 — failover/restart keeps one lineage, no double execution
# ---------------------------------------------------------------------------


class TestFailoverKeepsOneLineage:
    async def test_lease_lapse_takeover_and_stale_owner_release(self, store: Any) -> None:
        await store.ensure_schema()
        goal = await store.create_goal(make_goal())
        policy = run_policy("dec-1")
        admitter = StubAdmitter()
        # Primary claims, then "dies" right after claiming (no release).
        primary_claim = await store.claim(
            goal.goal_id, holder="primary", ttl=timedelta(seconds=30), now=T0
        )
        assert primary_claim is not None
        # Failover: the secondary's bounded sweep reclaims the lapsed lease.
        restarted = GoalReconciler(
            store, policy, holder="secondary", admitter=admitter, lease_ttl=timedelta(seconds=30)
        )
        outcomes = await restarted.sweep(T0 + timedelta(seconds=31))
        assert [o.goal_id for o in outcomes] == [goal.goal_id]
        assert outcomes[0].claimed and outcomes[0].decided
        assert admitter.calls == ["dec-1"]
        view = await store.reconciliation_view(goal.goal_id)
        assert view["admissions_total"] == 1

        # The primary comes back and tries to admit with its stale epoch:
        # refused, no double execution.
        with pytest.raises(StaleGoalFence):
            await store.admit(
                goal.goal_id,
                fencing_token=primary_claim.fencing_token,
                decision_key="dec-1-late",
                now=T0 + timedelta(seconds=32),
            )
        # And its reconciler pass cannot produce any second decision either:
        # the Goal is asleep and no relevant change has arrived.
        failing = GoalReconciler(store, policy, holder="primary", admitter=admitter)
        outcome = await failing.reconcile(goal.goal_id, now=T0 + timedelta(seconds=32))
        assert outcome.decided is False and outcome.admissions == []
        assert admitter.calls == ["dec-1"]
        assert (await store.get_goal(goal.goal_id)).runs_admitted == 1

    async def test_same_goal_lineage_across_failover(self, store: Any) -> None:
        await store.ensure_schema()
        goal = await store.create_goal(make_goal())
        key = "event-7:admit"
        policy = StubPolicy(
            lambda facts: PolicyDecision(
                admissions=(
                    PlannedAdmission(kind="run", decision_key=key, correlation_id="event-7"),
                )
            )
        )
        admitter = StubAdmitter()
        outcomes = []
        for index, holder in enumerate(("primary", "secondary", "tertiary")):
            reconciler = GoalReconciler(store, policy, holder=holder, admitter=admitter)
            # Each failover holder replays the same canonical event.
            await reconciler.wake(
                goal.goal_id,
                reason=WakeReason.RUN_TERMINAL,
                correlation_id=f"event-7-redelivery-{index}",
                unblocks=True,
                now=T0,
            )
            outcomes.append(await reconciler.reconcile(goal.goal_id, now=T0))
        assert len(await store.pending_admissions(goal.goal_id)) == 0
        view = await store.reconciliation_view(goal.goal_id)
        assert view["admissions_total"] == 1
        assert (await store.get_goal(goal.goal_id)).revision == 1
        # All three holders decided the same work under the same key...
        assert all(o.decided for o in outcomes)
        assert [a.decision_key for a in outcomes[1].duplicates] == [key]
        assert [a.decision_key for a in outcomes[2].duplicates] == [key]
        # ...but only the first created the artifact: one lineage, no double
        # execution across failover.
        assert admitter.calls == [key]
        assert (await store.get_goal(goal.goal_id)).runs_admitted == 1


# ---------------------------------------------------------------------------
# Degenerate paths — unknown ids, double settlement, stale fences, bad
# postures, and coercion. Every guard runs on both store twins.
# ---------------------------------------------------------------------------


class TestStoreGuardsAndDegeneratePaths:
    async def test_create_goal_duplicate_refused(self, store: Any) -> None:
        await store.ensure_schema()
        await store.create_goal(make_goal())
        with pytest.raises(GoalReconciliationError, match="already exists"):
            await store.create_goal(make_goal())

    async def test_record_wake_unknown_goal_refused(self, store: Any) -> None:
        await store.ensure_schema()
        with pytest.raises(GoalReconciliationError, match="unknown Goal"):
            await store.record_wake(
                "missing", reason=WakeReason.GOAL_REVISION, correlation_id="e-1", now=T0
            )

    async def test_complete_admission_unknown_id_is_false(self, store: Any) -> None:
        await store.ensure_schema()
        await store.create_goal(make_goal())
        assert await store.complete_admission("no-such-admission", physical_ref="run-1") is False

    async def test_complete_admission_twice_settles_once(self, store: Any) -> None:
        await store.ensure_schema()
        await store.create_goal(make_goal())
        claim = await store.claim("g-1", holder="a", ttl=timedelta(seconds=30), now=T0)
        assert claim is not None
        admission, _ = await store.admit(
            "g-1", fencing_token=claim.fencing_token, decision_key="dec-1", now=T0
        )
        assert (
            await store.complete_admission(admission.admission_id, physical_ref="run-1", now=T0)
            is True
        )
        # A crash replay of the same settlement must not restamp or double-count.
        assert (
            await store.complete_admission(admission.admission_id, physical_ref="run-2", now=T0)
            is False
        )
        view = await store.reconciliation_view("g-1")
        assert view is not None and view["open_admissions"] == 0

    async def test_pending_wakes_without_goal_filter_returns_all(self, store: Any) -> None:
        await store.ensure_schema()
        for goal_id in ("g-1", "g-2"):
            await store.create_goal(make_goal(goal_id=goal_id))
            await store.record_wake(
                goal_id, reason=WakeReason.GOAL_REVISION, correlation_id=f"e-{goal_id}", now=T0
            )
        assert {w.goal_id for w in await store.pending_wakes()} == {"g-1", "g-2"}

    async def test_mark_wakes_dispatched_ignores_unknown_and_already_dispatched(
        self, store: Any
    ) -> None:
        await store.ensure_schema()
        await store.create_goal(make_goal())
        wake = await store.record_wake(
            "g-1", reason=WakeReason.GOAL_REVISION, correlation_id="e-1", now=T0
        )
        assert wake is not None
        assert await store.mark_wakes_dispatched(["missing"], now=T0) == 0
        assert await store.mark_wakes_dispatched([wake.wake_id], now=T0) == 1
        # A redelivery must not re-mark an already-dispatched wake.
        assert await store.mark_wakes_dispatched([wake.wake_id], now=T0) == 0
        assert await store.pending_wakes("g-1") == []

    async def test_sleep_goal_refuses_non_sleeping_status(self, store: Any) -> None:
        await store.ensure_schema()
        await store.create_goal(make_goal())
        claim = await store.claim("g-1", holder="a", ttl=timedelta(seconds=30), now=T0)
        assert claim is not None
        with pytest.raises(GoalReconciliationError, match="sleeping status"):
            await store.sleep_goal(
                "g-1", status=GoalStatus.READY, fencing_token=claim.fencing_token, now=T0
            )

    async def test_sleep_goal_after_fence_loss_refused(self, store: Any) -> None:
        await store.ensure_schema()
        await store.create_goal(make_goal())
        lapsed = await store.claim("g-1", holder="a", ttl=timedelta(seconds=1), now=T0)
        assert lapsed is not None
        takeover = await store.claim(
            "g-1", holder="b", ttl=timedelta(seconds=30), now=T0 + timedelta(seconds=2)
        )
        assert takeover is not None and takeover.fence_epoch > lapsed.fence_epoch
        with pytest.raises(StaleGoalFence):
            await store.sleep_goal(
                "g-1",
                status=GoalStatus.DORMANT,
                fencing_token=lapsed.fencing_token,
                awake_after=T0 + timedelta(seconds=2),
                now=T0 + timedelta(seconds=2),
            )

    async def test_finish_goal_after_fence_loss_refused(self, store: Any) -> None:
        await store.ensure_schema()
        await store.create_goal(make_goal())
        lapsed = await store.claim("g-1", holder="a", ttl=timedelta(seconds=1), now=T0)
        assert lapsed is not None
        takeover = await store.claim(
            "g-1", holder="b", ttl=timedelta(seconds=30), now=T0 + timedelta(seconds=2)
        )
        assert takeover is not None
        with pytest.raises(StaleGoalFence):
            await store.finish_goal(
                "g-1", fencing_token=lapsed.fencing_token, now=T0 + timedelta(seconds=2)
            )
        goal = await store.get_goal("g-1")
        assert goal is not None and goal.status is not GoalStatus.SETTLED

    async def test_reconciliation_view_of_unknown_goal_is_none(self, store: Any) -> None:
        await store.ensure_schema()
        assert await store.reconciliation_view("missing") is None

    async def test_reconciliation_view_unclaimed_goal_has_no_claim(self, store: Any) -> None:
        await store.ensure_schema()
        await store.create_goal(make_goal())
        view = await store.reconciliation_view("g-1")
        assert view is not None
        assert view["claim"] is None
        assert view["pending_wakes"] == 0

    async def test_unknown_goal_lookup_refused(self) -> None:
        store = InMemoryGoalStore()
        with pytest.raises(GoalReconciliationError, match="unknown Goal"):
            store._require_goal("missing")


class TestCheckGatesRefusals:
    """Each Goal-level stop condition fences admission on its own."""

    def test_withdrawn_goal_refused(self) -> None:
        withdrawn = make_goal().model_copy(update={"status": GoalStatus.WITHDRAWN})
        with pytest.raises(GoalCancelled, match="cancelled"):
            _check_gates(withdrawn, T0)

    def test_deadline_passed_goal_refused(self) -> None:
        with pytest.raises(GoalDeadlinePassed, match="deadline passed"):
            _check_gates(make_goal(deadline_at=T0 - timedelta(seconds=1)), T0)

    def test_budget_exhausted_goal_refused(self) -> None:
        with pytest.raises(GoalBudgetExhausted, match="budget exhausted"):
            _check_gates(make_goal(budget_max_runs=1, runs_admitted=1), T0)


class TestSqliteDegeneratePaths:
    async def test_reclaim_expired_survives_goal_row_deleted_under_it(self, tmp_path: Any) -> None:
        """A claim whose Goal row vanished (torn external surgery) reclaims safely."""
        import aiosqlite

        path = str(tmp_path / "goals.db")
        conn = await aiosqlite.connect(path)
        try:
            sqlite_store = SqliteGoalStore(conn)
            await sqlite_store.ensure_schema()
            await sqlite_store.create_goal(make_goal())
            claim = await sqlite_store.claim("g-1", holder="a", ttl=timedelta(seconds=1), now=T0)
            assert claim is not None
            await conn.execute("DELETE FROM goals WHERE goal_id = 'g-1'")
            await conn.commit()
            woken = await sqlite_store.reclaim_expired(T0 + timedelta(seconds=2), limit=16)
            assert woken == []
        finally:
            await conn.close()


class TestReconcilerGuardPaths:
    async def test_goal_vanishing_after_claim_records_reconciliation_error(self) -> None:
        """A torn restart can drop the Goal row between claim and pass."""

        class VanishingGoalStore(InMemoryGoalStore):
            async def get_goal(self, goal_id: str) -> Goal | None:
                goal = await super().get_goal(goal_id)
                if goal is not None and goal.goal_id == "g-vanish":
                    return None
                return goal

        store = VanishingGoalStore()
        await store.create_goal(make_goal(goal_id="g-vanish"))
        reconciler = GoalReconciler(store, run_policy(), holder="h")
        outcome = await reconciler.reconcile("g-vanish", now=T0)
        assert outcome.claimed and not outcome.decided
        assert outcome.error is not None and "unknown Goal" in outcome.error

    async def test_goal_settled_between_claim_and_pass_decides_nothing(self) -> None:
        """A terminal transition landing mid-pass ends the pass without a decision."""

        class SettlingAfterClaimStore(InMemoryGoalStore):
            async def claim(self, goal_id: str, **kwargs: Any) -> Any:
                claim = await super().claim(goal_id, **kwargs)
                if claim is not None:
                    await self.finish_goal(goal_id, fencing_token=claim.fencing_token, now=T0)
                return claim

        store = SettlingAfterClaimStore()
        await store.create_goal(make_goal())
        policy = run_policy()
        reconciler = GoalReconciler(store, policy, holder="h")
        outcome = await reconciler.reconcile("g-1", now=T0)
        assert outcome.claimed
        assert not outcome.decided and outcome.admissions == [] and outcome.error is None
        assert policy.calls == 0

    async def test_fence_lost_mid_pass_records_stale_fence_and_skips(self) -> None:
        """A newer epoch taking the fence mid-pass makes the pass harmless."""

        class FenceRotatingStore(InMemoryGoalStore):
            async def claim(self, goal_id: str, **kwargs: Any) -> Any:
                claim = await super().claim(goal_id, **kwargs)
                if claim is not None:
                    # The same holder re-claims (epoch + 1, new token): the
                    # token the reconciler came in with is now stale.
                    await super().claim(goal_id, **kwargs)
                return claim

        store = FenceRotatingStore()
        await store.create_goal(make_goal())
        admitter = StubAdmitter()
        reconciler = GoalReconciler(store, run_policy(), holder="h", admitter=admitter)
        outcome = await reconciler.reconcile("g-1", now=T0)
        assert outcome.claimed
        assert outcome.error is not None and outcome.error.startswith("stale fence")
        assert outcome.admissions == [] and admitter.calls == []

    async def test_repair_open_without_admitter_or_pending_is_noop(self) -> None:
        store = InMemoryGoalStore()
        await store.create_goal(make_goal())
        bare = GoalReconciler(store, run_policy(), holder="h")
        assert await bare._repair_open("g-1", claim=None, at=T0) == []

        fenced = GoalReconciler(store, run_policy(), holder="h", admitter=StubAdmitter())
        claim = await store.claim("g-1", holder="h", ttl=timedelta(seconds=30), now=T0)
        assert claim is not None
        assert await fenced._repair_open("g-1", claim, T0) == []


class TestModelAndWiringEdges:
    def test_coerce_datetime_accepts_both_stored_shapes(self) -> None:
        assert coerce_datetime(T0) is T0
        assert coerce_datetime("2026-01-01T12:00:00+00:00") == T0

    def test_goal_id_of_event_ignores_unsuitable_payloads(self) -> None:
        assert goal_id_of_event(make_event("goal.changed", "g-1", "e-1")) == "g-1"
        assert goal_id_of_event(make_event("goal.changed", None, "e-2")) is None
        unshaped = SimpleNamespace(
            type="goal.changed", payload=None, event_id="e-3", workspace_id="ws-1"
        )
        assert goal_id_of_event(unshaped) is None
        non_string = SimpleNamespace(
            type="goal.changed", payload={"goal_id": 42}, event_id="e-4", workspace_id="ws-1"
        )
        assert goal_id_of_event(non_string) is None
        blank = SimpleNamespace(
            type="goal.changed", payload={"goal_id": ""}, event_id="e-5", workspace_id="ws-1"
        )
        assert goal_id_of_event(blank) is None
