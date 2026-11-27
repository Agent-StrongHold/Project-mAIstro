"""Production #805 decide-half composed in create_container (#7 row 8).

The reconciliation mechanics were always tested; what this suite pins is the
production composition: the fact-driven policy's deterministic answers, the
admitter's fulfilment of a run admission as one canonical QUEUED pursuit Run
bound to ``goal_id``/``goal_revision``, and the composed Container driving a
durable Goal through ``Goal -> Graph -> Run -> NodeRun -> Attempt`` via the
same operator cadence ticks every other admitted Run uses.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from maistro.container import Container, create_container
from maistro.goals.model import GoalRevisionDraft
from maistro.goals.reconciliation import (
    DISCOVERY_CORRELATION,
    GOAL_RECONCILIATION_AGENT,
    FactDrivenReconciliationPolicy,
    Goal,
    GoalAdmission,
    GoalDelegationUnsupported,
    GoalFacts,
    GoalPursuitUnresolvable,
    GoalReconciler,
    GoalRunAdmitter,
    GoalStatus,
    WakeFact,
    WakeReason,
)
from maistro.goals.store import InMemoryGoalStore as CanonicalInMemoryGoalStore
from maistro.runs.consumption import CONSUMABLE_SOURCES
from maistro.runs.goal_context import goal_context_of
from maistro.runs.model import RunStatus
from maistro.runs.sources import ADMISSION_SOURCE, GOAL_RECONCILIATION_SOURCE
from maistro.runs.store import InMemoryRunStore
from maistro.types.config import AgentConfig

WORKSPACE = "ws-goal-production"
PROJECT = "proj-goal-production"
AGENT = "goal-agent"

DRAFT = GoalRevisionDraft(desired_state="Publish the milestone release notes", author=AGENT)


async def _canonical_goal(
    goals: CanonicalInMemoryGoalStore,
    *,
    goal_id: str = "g-production",
    project_id: str = PROJECT,
) -> Any:
    return await goals.create_goal(
        workspace_id=WORKSPACE,
        project_id=project_id,
        agent_id=AGENT,
        draft=DRAFT,
        goal_id=goal_id,
    )


def _facts(goal: Goal, **kwargs: Any) -> GoalFacts:
    return GoalFacts(goal=goal, now=datetime.now(UTC), **kwargs)


def _wake(correlation: str, *, unblocks: bool = True) -> WakeFact:
    return WakeFact(
        wake_id=f"g-production:{correlation}",
        goal_id="g-production",
        reason=WakeReason.GOAL_REVISION,
        correlation_id=correlation,
        unblocks=unblocks,
    )


# --- the policy's deterministic answers --------------------------------------


async def test_an_unblocking_wake_progresses_under_the_wake_correlation() -> None:
    policy = FactDrivenReconciliationPolicy()
    goal = Goal(goal_id="g-production", workspace_id=WORKSPACE, project_id=PROJECT)

    decision = await policy.decide(_facts(goal, pending_wakes=(_wake("event-1"),)))

    assert decision.admissions[0].decision_key == "g-production:event-1"
    assert decision.admissions[0].correlation_id == "event-1"
    assert decision.admissions[0].kind == "run"
    assert not decision.complete and decision.blocked_reason is None


async def test_a_replayed_wake_yields_the_same_key_and_a_new_wake_replans() -> None:
    policy = FactDrivenReconciliationPolicy()
    goal = Goal(goal_id="g-production", workspace_id=WORKSPACE, project_id=PROJECT)

    replayed = await policy.decide(_facts(goal, pending_wakes=(_wake("event-1"),)))
    fresh = await policy.decide(_facts(goal, pending_wakes=(_wake("event-2"),)))

    assert replayed.admissions[0].decision_key == "g-production:event-1"
    assert fresh.admissions[0].decision_key == "g-production:event-2", (
        "a genuinely new canonical change must produce new work, not collapse "
        "onto the admission the old event already produced"
    )


async def test_a_goal_in_pursuit_with_no_new_change_waits_wake_driven() -> None:
    policy = FactDrivenReconciliationPolicy()
    pursued = Goal(
        goal_id="g-production",
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        runs_admitted=1,
        status=GoalStatus.DORMANT,
    )

    decision = await policy.decide(_facts(pursued))

    assert decision.admissions == () and decision.sleep_for is None
    assert decision.blocked_reason is None, (
        "waiting pursuit work parks without a sweep horizon: no wake, no cost"
    )


async def test_an_open_admission_blocks_stacking_a_second_one() -> None:
    policy = FactDrivenReconciliationPolicy()

    decision = await policy.decide(
        _facts(
            Goal(
                goal_id="g-production",
                workspace_id=WORKSPACE,
                project_id=PROJECT,
                runs_admitted=1,
            ),
            pending_admissions=(
                GoalAdmission(
                    goal_id="g-production",
                    revision=1,
                    fence_epoch=1,
                    decision_key="g-production:discovery",
                ),
            ),
        )
    )

    assert decision.admissions == (), "never stack work while an admission is open"


async def test_an_exhausted_budget_gates_the_goal() -> None:
    policy = FactDrivenReconciliationPolicy()
    goal = Goal(
        goal_id="g-production",
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        runs_admitted=3,
        budget_max_runs=3,
    )

    decision = await policy.decide(_facts(goal, pending_wakes=(_wake("event-1"),)))

    assert decision.admissions == () and decision.complete is False
    assert decision.blocked_reason is not None and "budget" in decision.blocked_reason


async def test_a_terminal_goal_is_never_redecided() -> None:
    policy = FactDrivenReconciliationPolicy()
    goal = Goal(
        goal_id="g-production",
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        status=GoalStatus.SETTLED,
    )

    decision = await policy.decide(_facts(goal, pending_wakes=(_wake("event-1"),)))

    assert decision.admissions == () and decision.complete is False


async def test_a_never_notified_goal_is_discovered_under_a_stable_key() -> None:
    policy = FactDrivenReconciliationPolicy()
    goal = Goal(goal_id="g-production", workspace_id=WORKSPACE, project_id=PROJECT)

    first = await policy.decide(_facts(goal))
    second = await policy.decide(_facts(goal))

    assert first.admissions[0].decision_key == f"g-production:{DISCOVERY_CORRELATION}"
    assert second.admissions[0].decision_key == first.admissions[0].decision_key, (
        "discovery replays converge on one decision key, so the store's "
        "idempotence — not luck — bounds the admissions"
    )


# --- the physical admitter ----------------------------------------------------


@pytest.fixture
async def spine() -> Any:
    """A run store, a canonical Goal store, and the project they file under."""
    from maistro.projects.scope_store import InMemoryProjectScopeStore

    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(WORKSPACE)
    project = await projects.create(
        workspace_id=WORKSPACE, parent_project_id=root.project_id, name="Goals"
    )
    runs = InMemoryRunStore(project_store=projects)
    goals = CanonicalInMemoryGoalStore()
    return runs, goals, project.project_id


async def test_an_admission_is_fulfilled_as_a_bound_queued_run(spine: Any) -> None:
    runs, goals, project_id = spine
    goal = await _canonical_goal(goals, project_id=project_id)
    admitter = GoalRunAdmitter(runs, goals)
    admission = GoalAdmission(
        goal_id=goal.goal_id,
        revision=1,
        fence_epoch=1,
        decision_key=f"{goal.goal_id}:{DISCOVERY_CORRELATION}",
        correlation_id=DISCOVERY_CORRELATION,
    )

    run_id = await admitter.admit(admission)
    run = await runs.get_run(run_id)

    assert run is not None
    assert run.status is RunStatus.QUEUED, (
        "QUEUED in the same insert: no caller holds a receipt, so a CREATED "
        "pursuit Run would be admitted work nobody would ever execute"
    )
    assert (run.goal_id, run.goal_revision) == (goal.goal_id, 1)
    assert run.provenance[ADMISSION_SOURCE] == GOAL_RECONCILIATION_SOURCE
    assert run.actor_principal_id == AGENT, (
        "the accountable Agent acts, not a caller-supplied string"
    )
    assert run.graph.project_id == project_id
    node = run.graph.materialize().nodes[0]
    assert node.parameters["to_agent"] == AGENT
    assert node.parameters["from_agent"] == GOAL_RECONCILIATION_AGENT
    assert node.parameters["task"] == DRAFT.desired_state
    context = goal_context_of(run.provenance)
    assert context is not None
    assert context.goal_id == goal.goal_id and context.goal_revision == "1"
    assert context.desired_state == DRAFT.desired_state
    assert context.accountable_agent_id == AGENT


async def test_replayed_physical_admission_returns_the_existing_run(spine: Any) -> None:
    runs, goals, project_id = spine
    goal = await _canonical_goal(goals, project_id=project_id)
    admitter = GoalRunAdmitter(runs, goals)
    admission = GoalAdmission(
        goal_id=goal.goal_id,
        revision=1,
        fence_epoch=1,
        decision_key=f"{goal.goal_id}:restart-wake",
    )

    first = await admitter.admit(admission)
    replay = await admitter.admit(admission)

    assert replay == first
    persisted = await runs.list_recent_runs(WORKSPACE)
    assert len([run for run in persisted if run.goal_id == goal.goal_id]) == 1


async def test_an_unknown_canonical_goal_refuses_loudly(spine: Any) -> None:
    runs, goals, _ = spine
    admitter = GoalRunAdmitter(runs, goals)
    admission = GoalAdmission(goal_id="g-ghost", revision=1, fence_epoch=1, decision_key="k")

    with pytest.raises(GoalPursuitUnresolvable):
        await admitter.admit(admission)


async def test_a_goal_without_its_current_revision_refuses_fail_closed(spine: Any) -> None:
    """A store whose chain lacks the Goal's current revision cannot be pursued.

    The canonical Goal is the revision authority, so fulfilment binds the
    Goal's ``current_revision`` — a store reporting a current revision its
    own chain does not carry is misbehaving, and admitting a Run whose
    language cannot be resolved would mint evidence with an invented payload.
    Fail closed instead.
    """

    class _ChainlessGoalStore:
        """A GoalStore whose revision chain is missing (protocol-shape stub)."""

        async def get_goal(self, goal_id: str) -> Any:
            return await goals.get_goal(goal_id)

        async def list_goal_revisions(self, goal_id: str) -> list[Any]:
            return []

    runs, goals, _ = spine
    goal = await _canonical_goal(goals)
    admitter = GoalRunAdmitter(runs, _ChainlessGoalStore())  # type: ignore[arg-type]
    admission = GoalAdmission(goal_id=goal.goal_id, revision=1, fence_epoch=1, decision_key="k")

    with pytest.raises(GoalPursuitUnresolvable):
        await admitter.admit(admission)


async def test_a_subgoal_admission_refuses_instead_of_minting_an_empty_goal(
    spine: Any,
) -> None:
    runs, goals, _ = spine
    admitter = GoalRunAdmitter(runs, goals)
    admission = GoalAdmission(
        goal_id="g-any", revision=1, fence_epoch=1, decision_key="k", kind="subgoal"
    )

    with pytest.raises(GoalDelegationUnsupported):
        await admitter.admit(admission)


async def test_pursuit_runs_across_a_revision_bump_keep_their_own_language(
    spine: Any,
) -> None:
    """Historical evidence is never rewritten: each Run keeps the revision
    whose desired state it carries, before and after the Goal moves on."""
    runs, goals, project_id = spine
    goal = await _canonical_goal(goals, project_id=project_id)
    admitter = GoalRunAdmitter(runs, goals)

    before = await runs.get_run(
        await admitter.admit(
            GoalAdmission(
                goal_id=goal.goal_id,
                revision=1,
                fence_epoch=1,
                decision_key=f"{goal.goal_id}:discovery",
            )
        )
    )
    await goals.append_revision(
        goal.goal_id,
        GoalRevisionDraft(desired_state="Publish the RC announcement", author=AGENT),
        expected_revision=1,
    )
    after = await runs.get_run(
        await admitter.admit(
            GoalAdmission(
                goal_id=goal.goal_id,
                revision=1,
                fence_epoch=2,
                decision_key=f"{goal.goal_id}:event-revision-2",
            )
        )
    )

    assert before is not None and after is not None
    assert before.goal_revision == 1
    assert before.graph.materialize().nodes[0].parameters["task"] == DRAFT.desired_state
    assert after.goal_revision == 2, (
        "the canonical Goal is the revision authority: a pursuit after the "
        "bump runs against the current revision, not the stale control value"
    )
    assert after.graph.materialize().nodes[0].parameters["task"] == "Publish the RC announcement"
    context = goal_context_of(after.provenance)
    assert context is not None and context.goal_revision == "2"


async def test_the_goal_reconciliation_source_is_consumable() -> None:
    # A pursuit Run is admitted QUEUED with no caller holding a receipt — the
    # exact shape the consumer exists to drive. Removing the source from the
    # allowlist would recreate "admitted work nobody executes" (#251) for
    # every Goal in the workspace, so the allowlist membership is pinned.
    assert GOAL_RECONCILIATION_SOURCE in CONSUMABLE_SOURCES


# --- the composed Container, end to end ---------------------------------------


async def _container(database_url: str = "sqlite://") -> tuple[Container, str]:
    """A composed Container plus the id of its Workspace's Root Project."""
    container = await create_container(
        AgentConfig(
            router_api_key="test-key",
            database_url=database_url,
            workspace_id=WORKSPACE,
        )
    )
    root = await container.project_scope_store.create_root(WORKSPACE)
    return container, root.project_id


async def test_the_composed_container_reconciles_a_goal_into_a_canonical_run() -> None:
    container, project_id = await _container()
    try:
        goal = await container.goal_store.create_goal(
            workspace_id=WORKSPACE,
            project_id=project_id,
            agent_id=AGENT,
            draft=DRAFT,
            goal_id="g-composed",
        )
        await container.goal_reconciliation_store.create_goal(
            Goal(goal_id=goal.goal_id, workspace_id=WORKSPACE, project_id=PROJECT)
        )

        assert await container.reconcile_goals() == 1

        queued = await container.run_store.list_by_status(RunStatus.QUEUED)
        pursuit = [run for run in queued if run.goal_id == goal.goal_id]
        assert len(pursuit) == 1
        assert pursuit[0].goal_revision == 1
        assert pursuit[0].provenance[ADMISSION_SOURCE] == GOAL_RECONCILIATION_SOURCE

        view = await container.goal_reconciliation_store.reconciliation_view(goal.goal_id)
        assert view is not None and view["admissions_total"] == 1

        # The Goal parked wake-driven: a second tick re-decides nothing, so
        # one discovered Goal admits exactly one pursuit Run.
        assert await container.reconcile_goals() == 0
        queued_again = await container.run_store.list_by_status(RunStatus.QUEUED)
        assert len([r for r in queued_again if r.goal_id == goal.goal_id]) == 1
    finally:
        await container.aclose()


async def test_crash_after_run_insert_replays_one_canonical_run() -> None:
    container, project_id = await _container()
    try:
        goal = await container.goal_store.create_goal(
            workspace_id=WORKSPACE,
            project_id=project_id,
            agent_id=AGENT,
            draft=DRAFT,
            goal_id="g-restart-replay",
        )
        await container.goal_reconciliation_store.create_goal(
            Goal(goal_id=goal.goal_id, workspace_id=WORKSPACE, project_id=PROJECT)
        )

        class CrashAfterPhysicalAdmission:
            def __init__(self, inner: Any) -> None:
                self.inner = inner
                self.crash_once = True

            def __getattr__(self, name: str) -> Any:
                return getattr(self.inner, name)

            async def complete_admission(self, admission_id: str, **kwargs: Any) -> bool:
                if self.crash_once:
                    self.crash_once = False
                    raise RuntimeError("simulated process death after Run insert")
                return await self.inner.complete_admission(admission_id, **kwargs)

        interrupted = GoalReconciler(
            CrashAfterPhysicalAdmission(container.goal_reconciliation_store),
            container.goal_reconciliation_policy,
            holder="crashed-after-run-insert",
            admitter=container.goal_reconciliation_admitter,
        )
        with pytest.raises(RuntimeError, match="after Run insert"):
            await interrupted.reconcile(goal.goal_id)

        persisted = await container.run_store.list_recent_runs(WORKSPACE)
        assert len([run for run in persisted if run.goal_id == goal.goal_id]) == 1

        restarted = GoalReconciler(
            container.goal_reconciliation_store,
            container.goal_reconciliation_policy,
            holder="restarted-after-run-insert",
            admitter=container.goal_reconciliation_admitter,
        )
        outcome = await restarted.reconcile(goal.goal_id)

        assert [admission.decision_key for admission in outcome.repaired] == [
            f"{goal.goal_id}:discovery"
        ]
        persisted = await container.run_store.list_recent_runs(WORKSPACE)
        assert len([run for run in persisted if run.goal_id == goal.goal_id]) == 1
        assert await container.goal_reconciliation_store.pending_admissions(goal.goal_id) == []
    finally:
        await container.aclose()


async def test_reopened_container_sweep_repairs_the_lapsed_physical_admission(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'restart.db'}"
    start = datetime.now(UTC)
    ttl = timedelta(seconds=30)
    first, project_id = await _container(database_url)
    try:
        goal = await first.goal_store.create_goal(
            workspace_id=WORKSPACE, project_id=project_id, agent_id=AGENT, draft=DRAFT
        )
        control = first.goal_reconciliation_store
        await control.create_goal(
            Goal(goal_id=goal.goal_id, workspace_id=WORKSPACE, project_id=project_id)
        )
        claim = await control.claim(goal.goal_id, holder="lost-worker", ttl=ttl, now=start)
        assert claim is not None
        admission, created = await control.admit(
            goal.goal_id,
            fencing_token=claim.fencing_token,
            decision_key=f"{goal.goal_id}:{DISCOVERY_CORRELATION}",
            now=start,
        )
        assert created and first.goal_reconciliation_admitter is not None
        run_id = await first.goal_reconciliation_admitter.admit(admission)
        # Stop at the durable boundary: no complete_admission or release_claim.
    finally:
        await first.aclose()

    restarted, _ = await _container(database_url)
    try:
        store = restarted.goal_reconciliation_store
        assert await restarted.reconcile_goals(now=start) == 0
        pending = await store.pending_admissions(goal.goal_id)
        assert [row.admission_id for row in pending] == [admission.admission_id]
        assert await restarted.reconcile_goals(now=start + ttl) == 1
        assert await store.pending_admissions(goal.goal_id) == []
        runs = await restarted.run_store.list_recent_runs(WORKSPACE)
        assert [(r.run_id, r.status) for r in runs if r.goal_id == goal.goal_id] == [
            (run_id, RunStatus.QUEUED)
        ]
    finally:
        await restarted.aclose()


async def test_the_consumer_drives_the_admitted_pursuit_through_the_lineage() -> None:
    container, project_id = await _container()
    try:
        goal = await container.goal_store.create_goal(
            workspace_id=WORKSPACE,
            project_id=project_id,
            agent_id=AGENT,
            draft=DRAFT,
            goal_id="g-lineage",
        )
        await container.goal_reconciliation_store.create_goal(
            Goal(goal_id=goal.goal_id, workspace_id=WORKSPACE, project_id=PROJECT)
        )
        assert await container.reconcile_goals() == 1

        queued = await container.run_store.list_by_status(RunStatus.QUEUED)
        pursuit = next(run for run in queued if run.goal_id == goal.goal_id)

        accounting = await container.execute_admitted_runs_accounting()

        assert accounting.attempted == 1, (
            "the consumer owns the pursuit source; skipping it would recreate "
            "the admitted-work-nobody-executes state #251 removed"
        )
        claimed = await container.run_store.get_run(pursuit.run_id)
        assert claimed is not None and claimed.status is not RunStatus.QUEUED, (
            "the claimed pursuit Run left QUEUED in the same insert that "
            "persisted its NodeRun and leased Attempt"
        )
        node_runs = await container.run_store.list_node_runs(pursuit.run_id)
        assert len(node_runs) >= 1, "the Run's Graph became NodeRun rows"
        attempts = await container.run_store.list_attempts(node_runs[0].node_run_id)
        assert len(attempts) >= 1, "the NodeRun leased an Attempt"
    finally:
        await container.aclose()


async def test_a_goal_revision_bump_replans_under_a_new_decision_key() -> None:
    container, project_id = await _container()
    try:
        goal = await container.goal_store.create_goal(
            workspace_id=WORKSPACE,
            project_id=project_id,
            agent_id=AGENT,
            draft=DRAFT,
            goal_id="g-replan",
        )
        await container.goal_reconciliation_store.create_goal(
            Goal(goal_id=goal.goal_id, workspace_id=WORKSPACE, project_id=PROJECT)
        )
        assert await container.reconcile_goals() == 1
        assert await container.reconcile_goals() == 0, "parked: no wake, no work"

        # The desired state moves (the Goal authority's compare-and-set) and a
        # canonical change is recorded durably — the replan trigger.
        await container.goal_store.append_revision(
            goal.goal_id,
            GoalRevisionDraft(desired_state="Publish the RC announcement", author=AGENT),
            expected_revision=1,
        )
        await container.goal_reconciliation_store.record_wake(
            goal.goal_id,
            reason=WakeReason.GOAL_REVISION,
            correlation_id="event-revision-2",
            unblocks=True,
        )

        assert await container.reconcile_goals() == 1

        queued = await container.run_store.list_by_status(RunStatus.QUEUED)
        pursuits = [run for run in queued if run.goal_id == goal.goal_id]
        assert len(pursuits) == 2, "the replan produced new work"
        revision_two = [run for run in pursuits if run.goal_revision == 2]
        assert len(revision_two) == 1
        assert revision_two[0].graph.materialize().nodes[0].parameters["task"] == (
            "Publish the RC announcement"
        )
    finally:
        await container.aclose()
