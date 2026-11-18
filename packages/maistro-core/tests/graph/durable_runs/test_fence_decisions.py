"""Park / redirect / accept as a HITL fence on waiting NodeRuns (M7-A5, #794).

Issue-acceptance mapping (each test class names the criterion it proves):

- AC-1 "A pack fence enters a durable waiting NodeRun that survives process
  restart (#737 invariant)" → `TestPackFenceWaitsDurably`
- AC-2 "Park leaves Goal/Rubric/eval/artifact state intact and resumes on the
  same Run" → `TestParkKeepsStateAndResumes`
- AC-3 "Redirect-Goal mints a Goal revision and a subsequent Rubric/brief
  revision; historical Attempts still name the old Goal revision"
  → `TestRedirectGoal`
- AC-4 "Redirect-Rubric mints a Rubric revision against the same Goal
  revision" → `TestRedirectRubric`
- AC-5 "Redirect-brief does not change Goal or Rubric identity"
  → `TestRedirectBrief`
- AC-6 "Accept on a failing gate requires recorded human rationale and still
  does not grant extra Capability" → `TestAcceptGate`
- AC-7 "Cancel remains distinct from park" → `TestCancelIsNotPark`
- AC-8 "Tests prove UI-only pause without NodeRun evidence is impossible on
  this path" → `TestNoUiOnlyPause`

Fixtures follow the established durable-runs pattern: a loop Graph whose
fence is the real `human.fence_decision` gate node placed at the pack's
declared `evaluate.accept` fence point, executed by the real
`run_durable_graph` over each durable store backend, with Rubric revisions
minted through the M7-A2 `RubricStore` and gate evidence derived from
M7-A3 eval records on the Run spine.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel, ValidationError

from maistro.graph import Graph, Node
from maistro.graph.definitions import Edge
from maistro.graph.durable_runs import (
    CanonicalDurableRunStore,
    HitlAuthorization,
    InMemoryDurableRunStore,
    InMemoryGraphContinuationStore,
    RunStatus,
    resume_durable_graph,
    run_durable_graph,
)
from maistro.graph.durable_runs.fence import (
    InMemoryGoalRevisionRedirector,
    accept_fence,
    park_fence,
    redirect_fence,
)
from maistro.graph.durable_runs.hitl import HitlDeadlineElapsed, hitl_deadline, hitl_pause
from maistro.graph.durable_runs.stores import (
    SqliteDurableRunStore,
    fence_binding,
    fence_decisions_of,
)
from maistro.graph.durable_runs.types import DurableRunRecord
from maistro.graph.execution_state import GraphExecutionState
from maistro.graph.nodes import BaseNode, NodeContext, get_node
from maistro.graph.nodes.base import PAUSE_AWAITING_HUMAN_DECISION
from maistro.interop.contract import INTEROP_ONTOLOGY_V1
from maistro.ontology.registry import InMemoryOntology
from maistro.ontology.rubric import (
    NumericScale,
    RubricDimension,
    RubricGate,
    RubricScale,
    ScoringMethod,
)
from maistro.projects.rubric_store import (
    GoalRevisionSnapshot,
    RubricProvenance,
    RubricStore,
)
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore
from maistro.runs.eval import eval_summary
from maistro.runs.fence import (
    FenceAcceptRequiresRationale,
    FenceDecision,
    FenceDecisionKind,
    FenceError,
    FenceNotWaitingError,
    FenceRedirectTarget,
    FenceRedirectTargetRequired,
    brief_version_at_least,
    goal_revision_at_least,
    normalize_decision_time,
)
from maistro.runs.lifecycle import transition_node_run
from maistro.runs.model import (
    EvalMethod,
    NodeRun,
    RunEvalScore,
)
from maistro.runs.model import (
    RunStatus as RunStatusModel,
)

from .._canonical_helpers import durable_record

pytestmark = [pytest.mark.contract("behavioral")]

WORKSPACE_ID = "ws-794-fence"
GOAL_ID = "goal-794"
GOAL_REVISION = 3
RUBRIC_ID = "rubric-794"
DIMENSION_CLARITY = "clarity_of_offer"
DIMENSION_EVIDENCE = "claim_evidence"
NODE_FENCE = "fence.evaluate"
NODE_FENCE_B = "fence.publish"
NODE_AFTER = "refine.revise"


async def _allow_test_membership(_principal: str, _workspace_id: str) -> bool:
    return True


def _authorization() -> HitlAuthorization:
    return HitlAuthorization(
        effective_principal="fence-operator",
        workspace_ids=frozenset({WORKSPACE_ID}),
        membership_check=_allow_test_membership,
    )


def _dimensions() -> list[RubricDimension]:
    return [
        RubricDimension(
            id=DIMENSION_CLARITY,
            name="Clarity of offer",
            weight=1.0,
            scale=RubricScale(numeric=NumericScale()),
            method=ScoringMethod.DETERMINISTIC,
        ),
        RubricDimension(
            id=DIMENSION_EVIDENCE,
            name="Claim-evidence",
            weight=1.0,
            scale=RubricScale(numeric=NumericScale()),
            method=ScoringMethod.DETERMINISTIC,
        ),
    ]


def _revised_dimensions() -> list[RubricDimension]:
    """A changed scoring standard for redirect-rubric tests."""
    return [
        RubricDimension(
            id=DIMENSION_CLARITY,
            name="Clarity of offer (tightened)",
            weight=2.0,
            scale=RubricScale(numeric=NumericScale()),
            method=ScoringMethod.DETERMINISTIC,
        ),
        RubricDimension(
            id=DIMENSION_EVIDENCE,
            name="Claim-evidence (tightened)",
            weight=3.0,
            scale=RubricScale(numeric=NumericScale()),
            method=ScoringMethod.DETERMINISTIC,
        ),
    ]


class _InMemoryGoalRevisionCatalog:
    """Dict-backed :class:`~maistro.projects.rubric_store.GoalRevisionCatalog`
    test double (the engine's dict-backed copy lives in maistro_design, which
    core tests must not import — dependency direction)."""

    def __init__(self) -> None:
        self._goals: dict[tuple[str, int], GoalRevisionSnapshot] = {}

    def register_goal(self, snapshot: GoalRevisionSnapshot) -> GoalRevisionSnapshot:
        self._goals[(snapshot.goal_id, snapshot.goal_revision)] = snapshot.model_copy(deep=True)
        return snapshot

    def resolve(self, goal_id: str, goal_revision: int) -> GoalRevisionSnapshot | None:
        snap = self._goals.get((goal_id, goal_revision))
        return snap.model_copy(deep=True) if snap is not None else None


class _GoalAuthority(_InMemoryGoalRevisionCatalog):
    """One Goal authority for the test world: the read seam RubricStore
    resolves liveness through, and the mint port the fence redirects through
    — exactly the single authority canonical Goal persistence (#458) will be."""

    def mint_revision(
        self,
        goal_id: str,
        *,
        prior_revision: int,
        workspace_id: str,
        project_id: str,
    ) -> int:
        from maistro.graph.durable_runs.fence import FenceError

        snapshot = self.resolve(goal_id, prior_revision)
        if (
            snapshot is None
            or snapshot.workspace_id != workspace_id
            or snapshot.project_id != project_id
        ):
            raise FenceError(
                f"goal {goal_id!r} revision {prior_revision} is not live in "
                f"workspace={workspace_id!r} project={project_id!r}"
            )
        next_revision = prior_revision + 1
        self.register_goal(
            GoalRevisionSnapshot(
                goal_id=goal_id,
                goal_revision=next_revision,
                workspace_id=workspace_id,
                project_id=project_id,
            )
        )
        return next_revision


class _World:
    """Project-scoped Goal/Rubric/Run stores shared by every fence test."""

    def __init__(self) -> None:
        self.goals = _GoalAuthority()
        self.rubrics = RubricStore(InMemoryOntology(), self.goals)
        # The redirect port and the liveness seam are the same authority —
        # one Goal identity, no second store.
        self.goal_redirector = self.goals
        self.project_id = ""

    async def setup(self) -> None:
        self.goals.register_goal(
            GoalRevisionSnapshot(
                goal_id=GOAL_ID,
                goal_revision=GOAL_REVISION,
                workspace_id=WORKSPACE_ID,
                project_id=self.project_id,
            )
        )
        await self.rubrics.create(
            workspace_id=WORKSPACE_ID,
            project_id=self.project_id,
            goal_id=GOAL_ID,
            goal_revision=GOAL_REVISION,
            dimensions=_dimensions(),
            gate=RubricGate(pass_threshold=80.0),
            provenance=RubricProvenance(authored_by="fence-operator"),
            rubric_id=RUBRIC_ID,
        )

    def binding(self) -> dict[str, Any]:
        return {
            "goal_id": GOAL_ID,
            "goal_revision": GOAL_REVISION,
            "rubric_id": RUBRIC_ID,
            "rubric_revision": 1,
            "brief_version": 1,
        }


def _loop_graph(project_id: str, *, timeout_seconds: int = 86_400) -> Graph:
    """One loop Run: explore → execute → evaluate → fence gate → refine.

    The gate is the `human.fence_decision` node the loop runtime places at a
    pack's declared fence point (#793 declares where the gates sit; #794 owns
    the durable wait and the three decisions).
    """
    return Graph(
        graph_id="loop-794",
        workspace_id=WORKSPACE_ID,
        project_id=project_id,
        name="fence-loop",
        nodes=[
            Node(node_id="explore.a", node_type="pack.explore", name="explore"),
            Node(node_id="execute.a", node_type="pack.execute", name="execute"),
            Node(node_id="evaluate.a", node_type="pack.evaluate", name="evaluate"),
            Node(
                node_id=NODE_FENCE,
                node_type="human.fence_decision",
                name="fence",
                inputs={
                    "fence_point": "evaluate.accept",
                    "goal_id": GOAL_ID,
                    "goal_revision": GOAL_REVISION,
                    "rubric_id": RUBRIC_ID,
                    "rubric_revision": 1,
                    "brief_version": 1,
                    "timeout_seconds": timeout_seconds,
                },
            ),
            Node(node_id=NODE_AFTER, node_type="pack.refine", name="refine"),
        ],
        edges=[
            Edge(edge_id="e1", from_node="explore.a", to_node="execute.a"),
            Edge(edge_id="e2", from_node="execute.a", to_node="evaluate.a"),
            Edge(edge_id="e3", from_node="evaluate.a", to_node=NODE_FENCE),
            Edge(edge_id="e4", from_node=NODE_FENCE, to_node=NODE_AFTER),
        ],
        metadata={"entry_node": "explore.a"},
    )


class _PhaseIn(BaseModel):
    text: str = ""


class _PhaseOut(BaseModel):
    text: str


class _ExploreNode(BaseNode):
    kind: ClassVar[str] = "pack.explore"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _PhaseIn
    output_schema: ClassVar[type[BaseModel]] = _PhaseOut

    async def _execute(self, inputs: _PhaseIn, ctx: NodeContext) -> _PhaseOut:
        return _PhaseOut(text=inputs.text)


class _ExecuteNode(BaseNode):
    kind: ClassVar[str] = "pack.execute"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _PhaseIn
    output_schema: ClassVar[type[BaseModel]] = _PhaseOut

    async def _execute(self, inputs: _PhaseIn, ctx: NodeContext) -> _PhaseOut:
        return _PhaseOut(text=inputs.text)


class _EvaluateNode(BaseNode):
    kind: ClassVar[str] = "pack.evaluate"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _PhaseIn
    output_schema: ClassVar[type[BaseModel]] = _PhaseOut

    async def _execute(self, inputs: _PhaseIn, ctx: NodeContext) -> _PhaseOut:
        return _PhaseOut(text=inputs.text)


class _RefineNode(BaseNode):
    kind: ClassVar[str] = "pack.refine"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _PhaseIn
    output_schema: ClassVar[type[BaseModel]] = _PhaseOut

    async def _execute(self, inputs: _PhaseIn, ctx: NodeContext) -> _PhaseOut:
        return _PhaseOut(text=inputs.text)


_PHASE_EXECUTORS: dict[str, type[BaseNode[Any, Any]]] = {
    stub.kind: stub for stub in (_ExploreNode, _ExecuteNode, _EvaluateNode, _RefineNode)
}


def _fence_resolver(node_id: str, graph: Graph) -> BaseNode[Any, Any]:
    node_type = next(node.node_type for node in graph.nodes if node.node_id == node_id)
    if node_type == "human.fence_decision":
        return get_node(node_type)()
    executor = _PHASE_EXECUTORS.get(node_type)
    if executor is None:
        raise KeyError(f"no executor for node kind {node_type!r}")
    return executor()


async def _run_to_fence(
    store: Any,
    run_store: InMemoryRunStore,
    world: _World,
    *,
    timeout_seconds: int = 86_400,
) -> DurableRunRecord:
    graph = _loop_graph(world.project_id, timeout_seconds=timeout_seconds)
    admitted = await run_store.create_run(
        graph,
        initial_status=RunStatus.QUEUED,
        actor_principal_id="fence-operator",
        provenance=world.binding(),
    )
    return await run_durable_graph(
        graph,
        store=store,
        node_resolver=_fence_resolver,
        provenance=world.binding(),
        run_id=admitted.run_id,
        run_store=run_store,
    )


def _waiting_fence_node_run(record: DurableRunRecord, node_id: str = NODE_FENCE) -> Any:
    matches = [
        node_run
        for node_run in record.node_runs
        if node_run.node_id == node_id and node_run.status is RunStatusModel.PAUSED
    ]
    assert matches, f"no waiting NodeRun for {node_id!r}"
    return matches[0]


@pytest.fixture
def world() -> _World:
    return _World()


@pytest.fixture
async def run_store(world: _World) -> AsyncIterator[InMemoryRunStore]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(WORKSPACE_ID)
    world.project_id = root.project_id
    await world.setup()
    yield InMemoryRunStore(project_store=projects)


@pytest.fixture
def store() -> InMemoryDurableRunStore:
    return InMemoryDurableRunStore()


async def _seed_eval_evidence(
    run_store: InMemoryRunStore,
    record: DurableRunRecord,
    *,
    failing: tuple[str, ...] = (DIMENSION_EVIDENCE,),
    goal_revision: int = GOAL_REVISION,
    rubric_revision: int = 1,
) -> None:
    """Score the evaluate phase's own durable Attempt evidence on the Run."""
    evaluate_node_run = next(
        node_run
        for node_run in record.node_runs
        if node_run.node_id == "evaluate.a" and node_run.status is RunStatusModel.COMPLETED
    )
    attempts = await run_store.list_attempts(evaluate_node_run.node_run_id)
    assert attempts, "the walk left no Attempt evidence for evaluate.a"
    attempt_id = attempts[-1].attempt_id
    for dimension in (DIMENSION_CLARITY, DIMENSION_EVIDENCE):
        await run_store.record_eval_score(
            RunEvalScore(
                run_id=record.run_id,
                node_run_id=evaluate_node_run.node_run_id,
                attempt_id=attempt_id,
                goal_id=GOAL_ID,
                goal_revision=goal_revision,
                rubric_id=RUBRIC_ID,
                rubric_revision=rubric_revision,
                dimension_id=dimension,
                raw_score=100.0 if dimension not in failing else 0.0,
                passed=dimension not in failing,
                method=EvalMethod.DETERMINISTIC,
            )
        )


# --- AC-1: the fence waits durably and survives process restart ---------------


class TestPackFenceWaitsDurably:
    @pytest.mark.asyncio
    async def test_fence_parks_as_durable_waiting_noderun_and_survives_restart(
        self, world: _World, run_store: InMemoryRunStore, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "durable-fence.sqlite3"
        store = SqliteDurableRunStore(db_path)
        paused = await _run_to_fence(store, run_store, world)

        assert paused.status is RunStatus.PAUSED
        _waiting_fence_node_run(paused)
        pause = hitl_pause(paused, NODE_FENCE)
        assert pause["kind"] == "hitl"
        # The fence's identity rides the durable pause: which pack fence
        # point, and which Goal/Rubric revisions the loop is consuming.
        assert pause["metadata"]["fence_point"] == "evaluate.accept"
        assert pause["metadata"]["goal_revision"] == GOAL_REVISION
        assert hitl_deadline(paused, NODE_FENCE) is not None

        # Process restart: a brand-new store instance over the same durable
        # file sees the same waiting fence — no new explore, no lost pause.
        reopened = SqliteDurableRunStore(db_path)
        restored = await reopened.get(paused.run_id)
        assert restored is not None
        assert restored.status is RunStatus.PAUSED
        assert hitl_pause(restored, NODE_FENCE) == pause
        _waiting_fence_node_run(restored)

    @pytest.mark.asyncio
    async def test_restarted_fence_settles_and_the_loop_completes(
        self, world: _World, run_store: InMemoryRunStore, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "durable-fence-resume.sqlite3"
        store = SqliteDurableRunStore(db_path)
        paused = await _run_to_fence(store, run_store, world)
        await _seed_eval_evidence(run_store, paused, failing=())

        reopened = SqliteDurableRunStore(db_path)
        settled = await reopened.accept_hitl(
            paused.run_id,
            NODE_FENCE,
            gate_passed=True,
            authorization=_authorization(),
        )
        assert settled.status is RunStatus.QUEUED
        resumed = await resume_durable_graph(
            paused.run_id, store=reopened, node_resolver=_fence_resolver
        )
        assert resumed.status is RunStatus.COMPLETED
        completed = {
            node_run.node_id
            for node_run in resumed.node_runs
            if node_run.status is RunStatusModel.COMPLETED
        }
        assert {NODE_FENCE, NODE_AFTER} <= completed


# --- AC-2: park preserves everything and resumes the same Run -----------------


class TestParkKeepsStateAndResumes:
    @pytest.mark.asyncio
    async def test_park_preserves_binding_eval_and_artifacts_then_resumes(
        self, world: _World, run_store: InMemoryRunStore, store: InMemoryDurableRunStore
    ) -> None:
        paused = await _run_to_fence(store, run_store, world)
        await _seed_eval_evidence(run_store, paused)
        before_scores = await run_store.list_eval_scores(paused.run_id)
        before_deadline = hitl_deadline(paused, NODE_FENCE)

        parked = await store.park_hitl(
            paused.run_id, NODE_FENCE, authorization=_authorization(), note="reviewing offline"
        )

        # Park writes only the decision: the Run is still waiting on the same
        # NodeRun, with the same binding, eval records, and deadline.
        assert parked.status is RunStatus.PAUSED
        _waiting_fence_node_run(parked)
        assert fence_binding(parked) == fence_binding(paused)
        assert await run_store.list_eval_scores(paused.run_id) == before_scores
        assert hitl_deadline(parked, NODE_FENCE) == before_deadline
        decisions = fence_decisions_of(parked)
        assert len(decisions) == 1
        assert decisions[0].decision is FenceDecisionKind.PARK
        assert decisions[0].goal_revision == GOAL_REVISION
        assert decisions[0].rubric_revision == 1
        assert decisions[0].decided_by == "fence-operator"

        # The same Run resumes from the same waiting NodeRun afterwards.
        settled = await store.accept_hitl(
            parked.run_id,
            NODE_FENCE,
            gate_passed=False,
            failing_dimensions=(DIMENSION_EVIDENCE,),
            rationale="shipping the earlier evidence",
            authorization=_authorization(),
        )
        assert settled.run_id == paused.run_id
        assert settled.status is RunStatus.QUEUED
        resumed = await resume_durable_graph(
            paused.run_id, store=store, node_resolver=_fence_resolver
        )
        assert resumed.status is RunStatus.COMPLETED
        assert len(fence_decisions_of(resumed)) == 2

    @pytest.mark.asyncio
    async def test_park_fence_composes_the_hold_through_the_store(
        self, world: _World, run_store: InMemoryRunStore, store: InMemoryDurableRunStore
    ) -> None:
        """park_fence is the hold verb's composition entry: the durable write
        (waiting NodeRun evidence, binding, deadline) stays the store's rule,
        the decision is recorded under the authorization's principal, and the
        fence still accepts a later decision on the same Run."""
        paused = await _run_to_fence(store, run_store, world)
        await _seed_eval_evidence(run_store, paused)
        before_deadline = hitl_deadline(paused, NODE_FENCE)

        parked = await park_fence(
            store,
            paused.run_id,
            NODE_FENCE,
            authorization=_authorization(),
            note="stepping away",
        )

        assert parked.run_id == paused.run_id
        assert parked.status is RunStatus.PAUSED
        _waiting_fence_node_run(parked)
        assert fence_binding(parked) == fence_binding(paused)
        assert hitl_deadline(parked, NODE_FENCE) == before_deadline
        decision = fence_decisions_of(parked)[-1]
        assert decision.decision is FenceDecisionKind.PARK
        assert decision.decided_by == "fence-operator"
        assert decision.rationale == "stepping away"

        # Park did not consume the pause: the same fence accepts a decision —
        # here an override, since the seeded gate evidence is failing.
        settled = await accept_fence(
            store,
            parked.run_id,
            NODE_FENCE,
            authorization=_authorization(),
            rubrics=world.rubrics,
            run_store=run_store,
            rationale="back from the hold; shipping the earlier evidence",
        )
        assert settled.status is RunStatus.QUEUED
        assert len(fence_decisions_of(settled)) == 2

    @pytest.mark.asyncio
    async def test_park_keeps_the_run_waiting_while_another_fence_stands(
        self, world: _World, store: InMemoryDurableRunStore
    ) -> None:
        """A frontier can hold several fences at once: parking one keeps the
        Run waiting on the other, with the other fence's deadline still armed
        and the redirect binding moving only where it was redirected."""
        deadline = datetime.now(UTC) + timedelta(hours=1)
        pause = {
            "kind": "hitl",
            "resume_at": deadline.isoformat(),
            "metadata": {"paused_reason": PAUSE_AWAITING_HUMAN_DECISION},
        }
        dag = {
            "id": "loop-794-two-fences",
            "nodes": [{"id": NODE_FENCE}, {"id": NODE_FENCE_B}],
            "edges": [],
            "entry_node": NODE_FENCE,
        }

        def _fence_node_run(node_id: str, ordinal: int) -> NodeRun:
            node_run = NodeRun(run_id="run-794-two-fences", node_id=node_id, ordinal=ordinal)
            node_run = transition_node_run(node_run, RunStatusModel.QUEUED)
            node_run = transition_node_run(node_run, RunStatusModel.RUNNING)
            return transition_node_run(node_run, RunStatusModel.PAUSED)

        record = durable_record(
            dag,
            run_id="run-794-two-fences",
            status=RunStatus.PAUSED,
            active_node_id=NODE_FENCE,
            node_runs=(_fence_node_run(NODE_FENCE, 1), _fence_node_run(NODE_FENCE_B, 2)),
            metadata={
                "initial_inputs": {},
                "hitl_answers": {},
                "pauses": {NODE_FENCE: dict(pause), NODE_FENCE_B: dict(pause)},
                "pause": dict(pause),
            },
            resume_at=deadline,
            workspace_id=WORKSPACE_ID,
        )
        record = record.model_copy(
            update={"run": record.run.model_copy(update={"provenance": world.binding()})}
        )
        state_values = record.graph_state.model_dump(mode="json")
        state_values["active_node_ids"] = [NODE_FENCE, NODE_FENCE_B]
        record = record.model_copy(
            update={"graph_state": GraphExecutionState.model_validate(state_values)}
        )
        await store.create(record)

        parked = await park_fence(
            store,
            "run-794-two-fences",
            NODE_FENCE,
            authorization=_authorization(),
            note="hold the accept gate",
        )
        assert parked.status is RunStatus.PAUSED
        other = next(node_run for node_run in parked.node_runs if node_run.node_id == NODE_FENCE_B)
        assert other.status is RunStatusModel.PAUSED
        assert hitl_deadline(parked, NODE_FENCE_B) == deadline

        settled = await store.redirect_hitl(
            "run-794-two-fences",
            NODE_FENCE_B,
            target=FenceRedirectTarget.BRIEF.value,
            new_brief_version=2,
            authorization=_authorization(),
        )
        # The first fence still stands, so the Run keeps waiting — and the
        # other fence's deadline stays the armed waker.
        assert settled.status is RunStatus.PAUSED
        assert settled.resume_at is not None
        assert fence_binding(settled)["brief_version"] == 2
        decisions = fence_decisions_of(settled)
        assert [d.decision for d in decisions] == [
            FenceDecisionKind.PARK,
            FenceDecisionKind.REDIRECT,
        ]


# --- AC-3: redirect-goal mints Goal + Rubric + brief revisions -----------------


class TestRedirectGoal:
    @pytest.mark.asyncio
    async def test_goal_redirect_cascades_and_history_kept_old_revisions(
        self, world: _World, run_store: InMemoryRunStore, store: InMemoryDurableRunStore
    ) -> None:
        paused = await _run_to_fence(store, run_store, world)
        await _seed_eval_evidence(run_store, paused)

        redirected = await redirect_fence(
            store,
            paused.run_id,
            NODE_FENCE,
            target=FenceRedirectTarget.GOAL,
            authorization=_authorization(),
            goals=world.goal_redirector,
            rubrics=world.rubrics,
        )

        decision = fence_decisions_of(redirected)[-1]
        assert decision.decision is FenceDecisionKind.REDIRECT
        assert decision.redirect_target is FenceRedirectTarget.GOAL
        assert decision.new_goal_revision == GOAL_REVISION + 1
        assert decision.new_rubric_revision == 2
        assert decision.new_brief_version == 2
        # The decision itself names what the Run consumed *at decision time*.
        assert decision.goal_revision == GOAL_REVISION
        assert decision.rubric_revision == 1

        # The minted Rubric revision binds the NEW Goal revision; revision 1
        # is immutable and still names the old one.
        revised = await world.rubrics.get_revision(RUBRIC_ID, 2)
        assert revised is not None and revised.goal_revision == GOAL_REVISION + 1
        original = await world.rubrics.get_revision(RUBRIC_ID, 1)
        assert original is not None and original.goal_revision == GOAL_REVISION

        # Newly eligible work consumes the new revision; the goal identity
        # itself never changed.
        assert redirected.run.provenance["goal_id"] == GOAL_ID
        assert redirected.run.provenance["goal_revision"] == GOAL_REVISION + 1
        assert redirected.run.provenance["rubric_revision"] == 2
        assert redirected.run.provenance["brief_version"] == 2
        assert INTEROP_ONTOLOGY_V1.validate_projection(
            "Goal",
            {
                "goal_id": redirected.run.provenance["goal_id"],
                "goal_revision": redirected.run.provenance["goal_revision"],
            },
        )

        # Historical Attempts' eval evidence still names the old Goal
        # revision — no silent history rewrite.
        scores = await run_store.list_eval_scores(paused.run_id)
        assert scores
        assert all(score.goal_revision == GOAL_REVISION for score in scores)
        assert all(score.rubric_revision == 1 for score in scores)

        # The loop continues on the same Run and the resumed fence node
        # consumed the redirect.
        assert redirected.status is RunStatus.QUEUED
        resumed = await resume_durable_graph(
            paused.run_id, store=store, node_resolver=_fence_resolver
        )
        assert resumed.status is RunStatus.COMPLETED
        answers = resumed.hitl_answers[NODE_FENCE]
        assert answers["decision"] == "redirect"
        assert answers["redirect_target"] == "goal"

    @pytest.mark.asyncio
    async def test_goal_redirect_requires_a_goal_lineage_port(
        self, world: _World, run_store: InMemoryRunStore, store: InMemoryDurableRunStore
    ) -> None:
        paused = await _run_to_fence(store, run_store, world)
        with pytest.raises(FenceError):
            await redirect_fence(
                store,
                paused.run_id,
                NODE_FENCE,
                target=FenceRedirectTarget.GOAL,
                authorization=_authorization(),
                rubrics=world.rubrics,
            )
        still_waiting = await store.get(paused.run_id)
        assert still_waiting is not None and still_waiting.status is RunStatus.PAUSED
        assert fence_decisions_of(still_waiting) == ()


# --- AC-4: redirect-rubric rebinds scoring on the same Goal revision -----------


class TestRedirectRubric:
    @pytest.mark.asyncio
    async def test_rubric_redirect_mints_revision_against_same_goal_revision(
        self, world: _World, run_store: InMemoryRunStore, store: InMemoryDurableRunStore
    ) -> None:
        paused = await _run_to_fence(store, run_store, world)

        redirected = await redirect_fence(
            store,
            paused.run_id,
            NODE_FENCE,
            target=FenceRedirectTarget.RUBRIC,
            authorization=_authorization(),
            rubrics=world.rubrics,
            dimensions=_revised_dimensions(),
        )

        decision = fence_decisions_of(redirected)[-1]
        assert decision.redirect_target is FenceRedirectTarget.RUBRIC
        assert decision.new_rubric_revision == 2
        assert decision.new_goal_revision is None
        assert decision.new_brief_version is None

        revised = await world.rubrics.get_revision(RUBRIC_ID, 2)
        assert revised is not None
        # Scoring changed; the desired outcome did not.
        assert revised.goal_revision == GOAL_REVISION
        assert revised.dimensions[0].weight == 2.0
        assert redirected.run.provenance["goal_revision"] == GOAL_REVISION
        assert redirected.run.provenance["rubric_revision"] == 2
        assert redirected.run.provenance["brief_version"] == 1

    @pytest.mark.asyncio
    async def test_a_redirect_cannot_mix_targets_into_one_blob(
        self, world: _World, run_store: InMemoryRunStore, store: InMemoryDurableRunStore
    ) -> None:
        """A redirect-rubric that also names a Goal revision is three requests
        pretending to be one — the decision model refuses it before commit."""
        paused = await _run_to_fence(store, run_store, world)
        with pytest.raises(FenceError, match="must not name new_goal_revision"):
            await store.redirect_hitl(
                paused.run_id,
                NODE_FENCE,
                target=FenceRedirectTarget.RUBRIC.value,
                new_goal_revision=GOAL_REVISION + 1,
                new_rubric_revision=2,
                authorization=_authorization(),
            )
        unchanged = await store.get(paused.run_id)
        assert unchanged is not None and unchanged.status is RunStatus.PAUSED
        assert fence_decisions_of(unchanged) == ()


# --- AC-5: redirect-brief moves neither Goal nor Rubric identity ---------------


class TestRedirectBrief:
    @pytest.mark.asyncio
    async def test_brief_redirect_changes_only_the_brief_version(
        self, world: _World, run_store: InMemoryRunStore, store: InMemoryDurableRunStore
    ) -> None:
        paused = await _run_to_fence(store, run_store, world)

        redirected = await redirect_fence(
            store,
            paused.run_id,
            NODE_FENCE,
            target=FenceRedirectTarget.BRIEF,
            authorization=_authorization(),
        )

        decision = fence_decisions_of(redirected)[-1]
        assert decision.redirect_target is FenceRedirectTarget.BRIEF
        assert decision.new_brief_version == 2
        assert decision.new_goal_revision is None
        assert decision.new_rubric_revision is None
        assert redirected.run.provenance["goal_id"] == GOAL_ID
        assert redirected.run.provenance["goal_revision"] == GOAL_REVISION
        assert redirected.run.provenance["rubric_id"] == RUBRIC_ID
        assert redirected.run.provenance["rubric_revision"] == 1
        assert redirected.run.provenance["brief_version"] == 2
        # No Rubric revision was minted.
        assert await world.rubrics.get_revision(RUBRIC_ID, 2) is None


# --- AC-6: accept on a failing gate needs recorded rationale, grants nothing --


class TestAcceptGate:
    @pytest.mark.asyncio
    async def test_failing_gate_accept_requires_rationale(
        self, world: _World, run_store: InMemoryRunStore, store: InMemoryDurableRunStore
    ) -> None:
        paused = await _run_to_fence(store, run_store, world)
        await _seed_eval_evidence(run_store, paused, failing=(DIMENSION_EVIDENCE,))

        with pytest.raises(FenceAcceptRequiresRationale):
            await accept_fence(
                store,
                paused.run_id,
                NODE_FENCE,
                authorization=_authorization(),
                rubrics=world.rubrics,
                run_store=run_store,
            )
        # The refusal wrote nothing.
        unchanged = await store.get(paused.run_id)
        assert unchanged is not None and unchanged.status is RunStatus.PAUSED
        assert fence_decisions_of(unchanged) == ()

        accepted = await accept_fence(
            store,
            paused.run_id,
            NODE_FENCE,
            authorization=_authorization(),
            rubrics=world.rubrics,
            run_store=run_store,
            rationale="the failing evidence lives in the canvas; the rubric text is stale",
        )
        decision = fence_decisions_of(accepted)[-1]
        assert decision.decision is FenceDecisionKind.ACCEPT
        assert decision.gate_passed is False
        assert decision.failing_dimensions == (DIMENSION_EVIDENCE,)
        assert decision.rationale.startswith("the failing evidence lives in the canvas")
        assert accepted.status is RunStatus.QUEUED
        resumed = await resume_durable_graph(
            paused.run_id, store=store, node_resolver=_fence_resolver
        )
        assert resumed.status is RunStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_accept_evaluates_the_bound_revision_not_the_latest(
        self, world: _World, run_store: InMemoryRunStore, store: InMemoryDurableRunStore
    ) -> None:
        """A Rubric revised after binding cannot rewrite the gate.

        Revision 2 drops the dimension that failed at revision 1; the Run is
        still bound to revision 1, so the failing dimension must still block
        a rationale-less accept instead of silently vanishing from the
        summary.
        """
        paused = await _run_to_fence(store, run_store, world)
        await _seed_eval_evidence(run_store, paused, failing=(DIMENSION_EVIDENCE,))
        await world.rubrics.update_dimensions(
            RUBRIC_ID,
            dimensions=[d for d in _dimensions() if d.id != DIMENSION_EVIDENCE],
        )

        with pytest.raises(FenceAcceptRequiresRationale):
            await accept_fence(
                store,
                paused.run_id,
                NODE_FENCE,
                authorization=_authorization(),
                rubrics=world.rubrics,
                run_store=run_store,
            )
        accepted = await accept_fence(
            store,
            paused.run_id,
            NODE_FENCE,
            authorization=_authorization(),
            rubrics=world.rubrics,
            run_store=run_store,
            rationale="bound revision still fails evidence",
        )
        decision = fence_decisions_of(accepted)[-1]
        assert decision.gate_passed is False
        assert decision.failing_dimensions == (DIMENSION_EVIDENCE,)

    @pytest.mark.asyncio
    async def test_unscored_run_cannot_pass_itself_and_overrides_need_rationale(
        self, world: _World, run_store: InMemoryRunStore, store: InMemoryDurableRunStore
    ) -> None:
        paused = await _run_to_fence(store, run_store, world)
        # No eval records at all: the gate is derived, not asserted. A UI
        # claiming "passed" without records has no path through here.
        with pytest.raises(FenceAcceptRequiresRationale):
            await accept_fence(
                store,
                paused.run_id,
                NODE_FENCE,
                authorization=_authorization(),
                rubrics=world.rubrics,
                run_store=run_store,
            )
        accepted = await accept_fence(
            store,
            paused.run_id,
            NODE_FENCE,
            authorization=_authorization(),
            rubrics=world.rubrics,
            run_store=run_store,
            rationale="accepted before scoring per sponsor request",
        )
        decision = fence_decisions_of(accepted)[-1]
        assert decision.gate_passed is False
        assert set(decision.failing_dimensions) == {DIMENSION_CLARITY, DIMENSION_EVIDENCE}

    @pytest.mark.asyncio
    async def test_accept_grants_no_capability(
        self, world: _World, run_store: InMemoryRunStore, store: InMemoryDurableRunStore
    ) -> None:
        paused = await _run_to_fence(store, run_store, world)
        await _seed_eval_evidence(run_store, paused, failing=())
        provenance_before = dict(paused.run.provenance)

        accepted = await store.accept_hitl(
            paused.run_id,
            NODE_FENCE,
            gate_passed=True,
            authorization=_authorization(),
        )

        decision = fence_decisions_of(accepted)[-1]
        # The accept record is a scoring verdict: no capability, grant, or
        # authorization fields exist on it, and the Run's provenance gained
        # nothing an effect chain could ride.
        decision_fields = set(decision.model_dump())
        assert not decision_fields & {"capability", "grant", "authorities", "permissions"}
        assert accepted.run.provenance == provenance_before
        assert accepted.run.provenance.get("capabilities") is None

    @pytest.mark.asyncio
    async def test_passing_gate_accepts_without_rationale(
        self, world: _World, run_store: InMemoryRunStore, store: InMemoryDurableRunStore
    ) -> None:
        paused = await _run_to_fence(store, run_store, world)
        await _seed_eval_evidence(run_store, paused, failing=())
        summary = await eval_summary(
            run_store,
            paused.run_id,
            rubric_id=RUBRIC_ID,
            rubric_revision=1,
            dimension_ids=[DIMENSION_CLARITY, DIMENSION_EVIDENCE],
        )
        assert summary.passed
        accepted = await accept_fence(
            store,
            paused.run_id,
            NODE_FENCE,
            authorization=_authorization(),
            rubrics=world.rubrics,
            run_store=run_store,
        )
        decision = fence_decisions_of(accepted)[-1]
        assert decision.gate_passed is True
        assert decision.failing_dimensions == ()
        assert decision.rationale == ""


# --- every fence refusal is the durable rule, observable at its own seam ---


def _decision_fields(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "run_id": "run-794",
        "node_id": NODE_FENCE,
        "node_run_id": "nr-794",
        "decision": FenceDecisionKind.PARK,
        "goal_id": GOAL_ID,
        "goal_revision": GOAL_REVISION,
        "rubric_id": RUBRIC_ID,
        "rubric_revision": 1,
        "decided_by": "fence-operator",
        "decided_at": datetime.now(UTC),
    }
    fields.update(overrides)
    return fields


def _refused(fields: dict[str, Any]) -> FenceError:
    """Build the decision and return the model's own fence error.

    pydantic wraps model_validator refusals in ValidationError; the original
    FenceError rides ``errors()[0]["ctx"]["error"]`` — the same structure the
    durable store re-throws at its boundary.
    """
    with pytest.raises(ValidationError) as excinfo:
        FenceDecision(**fields)
    original = (excinfo.value.errors()[0].get("ctx") or {}).get("error")
    assert isinstance(original, FenceError)
    return original


class TestFenceRefusalsAreObservable:
    """Each invalid fence decision is refused by the decision model itself,
    and each composition refusal names what was missing — so no caller (UI
    included) can smuggle a decision the durable evidence does not show."""

    def test_redirect_without_a_target_is_not_a_redirect(self) -> None:
        refused = _refused(_decision_fields(decision=FenceDecisionKind.REDIRECT))
        assert isinstance(refused, FenceRedirectTargetRequired)

    def test_redirect_goal_must_name_every_revision_it_implies(self) -> None:
        assert "must name" in str(
            _refused(
                _decision_fields(
                    decision=FenceDecisionKind.REDIRECT,
                    redirect_target=FenceRedirectTarget.GOAL,
                    new_rubric_revision=2,
                )
            )
        )

    def test_redirect_brief_must_not_name_revisions_it_does_not_imply(self) -> None:
        assert "must not name" in str(
            _refused(
                _decision_fields(
                    decision=FenceDecisionKind.REDIRECT,
                    redirect_target=FenceRedirectTarget.BRIEF,
                    new_brief_version=2,
                    new_goal_revision=GOAL_REVISION + 1,
                )
            )
        )

    def test_redirect_carries_no_gate_citation(self) -> None:
        assert "no gate citation" in str(
            _refused(
                _decision_fields(
                    decision=FenceDecisionKind.REDIRECT,
                    redirect_target=FenceRedirectTarget.BRIEF,
                    new_brief_version=2,
                    gate_passed=True,
                )
            )
        )

    def test_redirect_carries_no_override_rationale(self) -> None:
        assert "no override rationale" in str(
            _refused(
                _decision_fields(
                    decision=FenceDecisionKind.REDIRECT,
                    redirect_target=FenceRedirectTarget.BRIEF,
                    new_brief_version=2,
                    rationale="it looked fine",
                )
            )
        )

    def test_accept_must_cite_the_gate_result(self) -> None:
        assert "must cite the Rubric gate result" in str(
            _refused(_decision_fields(decision=FenceDecisionKind.ACCEPT))
        )

    def test_park_has_no_redirect_target_and_mints_no_revisions(self) -> None:
        assert "has no redirect target" in str(
            _refused(
                _decision_fields(
                    redirect_target=FenceRedirectTarget.BRIEF,
                    new_brief_version=2,
                )
            )
        )
        assert "mints no revisions" in str(
            _refused(_decision_fields(new_goal_revision=GOAL_REVISION + 1))
        )

    def test_revision_clocks_move_forward_and_decisions_are_aware(self) -> None:
        with pytest.raises(ValueError, match="advance from 1"):
            goal_revision_at_least(0)
        with pytest.raises(ValueError, match="advance from 1"):
            goal_revision_at_least(GOAL_REVISION, step=0)
        with pytest.raises(ValueError, match="advance from 1"):
            brief_version_at_least(0)
        with pytest.raises(ValueError, match="advance from 1"):
            brief_version_at_least(1, step=0)
        with pytest.raises(ValueError, match="timezone"):
            normalize_decision_time(datetime(2026, 1, 1))
        assert normalize_decision_time(None).tzinfo is not None

    def test_goal_lineage_stand_in_refuses_foreign_and_unborn_revisions(self) -> None:
        redirector = InMemoryGoalRevisionRedirector()
        with pytest.raises(ValueError, match="start at 1"):
            redirector.register_goal(
                GOAL_ID,
                revision=0,
                workspace_id=WORKSPACE_ID,
                project_id="p-794",
            )
        with pytest.raises(FenceError, match="not live"):
            redirector.mint_revision(
                GOAL_ID,
                prior_revision=GOAL_REVISION,
                workspace_id=WORKSPACE_ID,
                project_id="p-794",
            )
        redirector.register_goal(
            GOAL_ID,
            revision=GOAL_REVISION,
            workspace_id=WORKSPACE_ID,
            project_id="p-794",
        )
        assert (
            redirector.mint_revision(
                GOAL_ID,
                prior_revision=GOAL_REVISION,
                workspace_id=WORKSPACE_ID,
                project_id="p-794",
            )
            == GOAL_REVISION + 1
        )

    @pytest.mark.asyncio
    async def test_composition_refusals_name_what_was_missing(
        self, world: _World, run_store: InMemoryRunStore, store: InMemoryDurableRunStore
    ) -> None:
        paused = await _run_to_fence(store, run_store, world)
        await _seed_eval_evidence(run_store, paused)

        with pytest.raises(KeyError, match="no such run"):
            await redirect_fence(
                store,
                "run-794-missing",
                NODE_FENCE,
                target=FenceRedirectTarget.BRIEF,
                authorization=_authorization(),
            )
        with pytest.raises(KeyError, match="no such run"):
            await accept_fence(
                store,
                "run-794-missing",
                NODE_FENCE,
                authorization=_authorization(),
                rubrics=world.rubrics,
                run_store=run_store,
            )
        with pytest.raises(FenceError, match="re-binds the Rubric"):
            await redirect_fence(
                store,
                paused.run_id,
                NODE_FENCE,
                target=FenceRedirectTarget.GOAL,
                authorization=_authorization(),
                goals=world.goal_redirector,
            )
        with pytest.raises(FenceError, match="requires a RubricReviser"):
            await redirect_fence(
                store,
                paused.run_id,
                NODE_FENCE,
                target=FenceRedirectTarget.RUBRIC,
                authorization=_authorization(),
            )
        empty_rubrics = RubricStore(InMemoryOntology(), world.goals)
        with pytest.raises(FenceError, match=r"no rubric .* to re-bind"):
            await redirect_fence(
                store,
                paused.run_id,
                NODE_FENCE,
                target=FenceRedirectTarget.GOAL,
                authorization=_authorization(),
                goals=world.goal_redirector,
                rubrics=empty_rubrics,
            )
        with pytest.raises(FenceError, match=r"no rubric .* to revise"):
            await redirect_fence(
                store,
                paused.run_id,
                NODE_FENCE,
                target=FenceRedirectTarget.RUBRIC,
                authorization=_authorization(),
                rubrics=empty_rubrics,
            )
        with pytest.raises(FenceError, match=r"no rubric .* to cite on accept"):
            await accept_fence(
                store,
                paused.run_id,
                NODE_FENCE,
                authorization=_authorization(),
                rubrics=empty_rubrics,
                run_store=run_store,
            )
        # Every refusal above left the waiting fence exactly as it was.
        untouched = await store.get(paused.run_id)
        assert untouched is not None
        assert untouched.status is RunStatus.PAUSED
        assert fence_decisions_of(untouched) == ()

    @pytest.mark.asyncio
    async def test_malformed_loop_binding_is_refused_fail_closed(
        self, world: _World, run_store: InMemoryRunStore, store: InMemoryDurableRunStore
    ) -> None:
        """A redirect-written binding that lost its required keys is a durable
        corruption signal, not a reason to fall back to launch provenance."""
        from .._canonical_helpers import durable_record

        record = durable_record(
            {"id": "loop-794-binding", "entry_node": NODE_FENCE},
            run_id="run-794-binding",
            metadata={
                "initial_inputs": {},
                "hitl_answers": {},
                "loop_binding": {"goal_id": GOAL_ID},
            },
        )
        with pytest.raises(FenceNotWaitingError, match="malformed loop binding"):
            fence_binding(record)

    @pytest.mark.asyncio
    async def test_generic_answer_leaves_the_fence_pending(
        self, world: _World, run_store: InMemoryRunStore, store: InMemoryDurableRunStore
    ) -> None:
        """The node fails closed: a resume payload that is not a recorded
        fence decision (a plain answer, no `decision` key) re-arms the same
        waiting NodeRun instead of being read as a verdict."""
        paused = await _run_to_fence(store, run_store, world)
        answered = await store.submit_hitl_answer(
            paused.run_id,
            NODE_FENCE,
            {"note": "just checking in"},
            authorization=_authorization(),
        )
        assert answered.status is RunStatus.QUEUED

        resumed = await resume_durable_graph(
            paused.run_id, store=store, node_resolver=_fence_resolver
        )
        assert resumed.status is RunStatus.PAUSED
        _waiting_fence_node_run(resumed)
        assert fence_decisions_of(resumed) == ()


# --- AC-7: cancel stays cancel, park stays waiting -----------------------------


class TestCancelIsNotPark:
    @pytest.mark.asyncio
    async def test_cancel_terminalizes_where_park_keeps_waiting(
        self, world: _World, run_store: InMemoryRunStore, store: InMemoryDurableRunStore
    ) -> None:
        cancelled_run = await _run_to_fence(store, run_store, world, timeout_seconds=3600)
        parked_run = await _run_to_fence(store, run_store, world, timeout_seconds=3600)

        cancelled = await store.cancel_hitl(
            cancelled_run.run_id, NODE_FENCE, authorization=_authorization()
        )
        assert cancelled.status is RunStatus.CANCELLED

        parked = await store.park_hitl(
            parked_run.run_id, NODE_FENCE, authorization=_authorization()
        )
        assert parked.status is RunStatus.PAUSED
        _waiting_fence_node_run(parked)

        # A cancelled fence accepts no further decisions; a parked one does.
        with pytest.raises(ValueError):
            await store.accept_hitl(
                cancelled.run_id,
                NODE_FENCE,
                gate_passed=True,
                authorization=_authorization(),
            )
        settled = await store.accept_hitl(
            parked.run_id,
            NODE_FENCE,
            gate_passed=True,
            authorization=_authorization(),
        )
        assert settled.status is RunStatus.QUEUED


# --- AC-8: no UI-only pause without waiting NodeRun evidence -------------------


class TestNoUiOnlyPause:
    @pytest.mark.asyncio
    async def test_park_refused_without_a_durable_waiting_noderun(
        self, world: _World, run_store: InMemoryRunStore, store: InMemoryDurableRunStore
    ) -> None:
        completed = await _run_to_fence(store, run_store, world)
        # Settle the fence first: the Run is no longer waiting on anything.
        await store.accept_hitl(
            completed.run_id, NODE_FENCE, gate_passed=True, authorization=_authorization()
        )
        await resume_durable_graph(completed.run_id, store=store, node_resolver=_fence_resolver)

        with pytest.raises(ValueError, match="not paused on HITL"):
            await store.park_hitl(completed.run_id, NODE_FENCE, authorization=_authorization())
        after = await store.get(completed.run_id)
        assert after is not None
        assert after.status is RunStatus.COMPLETED
        assert len(fence_decisions_of(after)) == 1  # only the earlier accept

    @pytest.mark.asyncio
    async def test_park_refused_on_a_non_hitl_pause(
        self, world: _World, run_store: InMemoryRunStore
    ) -> None:
        from .._canonical_helpers import durable_record

        store = InMemoryDurableRunStore()
        dag = {
            "id": "loop-794-wait",
            "entry_node": NODE_FENCE,
            "nodes": [{"id": NODE_FENCE, "kind": "pack.evaluate"}],
            "edges": [],
        }
        record = durable_record(
            dag,
            run_id="run-794-system-wait",
            status=RunStatusModel.PAUSED,
            active_node_id=NODE_FENCE,
            workspace_id=WORKSPACE_ID,
            metadata={
                "initial_inputs": {},
                "hitl_answers": {},
                "pauses": {NODE_FENCE: {"kind": "wait", "metadata": {}, "resume_at": None}},
            },
        )
        record = record.model_copy(
            update={"run": record.run.model_copy(update={"provenance": world.binding()})}
        )
        await store.create(record)

        with pytest.raises(ValueError, match="not awaiting human input"):
            await store.park_hitl(record.run_id, NODE_FENCE, authorization=_authorization())
        unchanged = await store.get(record.run_id)
        assert unchanged is not None and unchanged.status is RunStatusModel.PAUSED
        assert fence_decisions_of(unchanged) == ()

    @pytest.mark.asyncio
    async def test_fence_decision_requires_the_loop_binding_evidence(
        self, store: InMemoryDurableRunStore, tmp_path: Path
    ) -> None:
        """A paused HITL Run without the Goal/Rubric binding cannot take a
        decision that cites or mints revisions — the binding is evidence, not
        caller-supplied UI state."""
        from .._canonical_helpers import durable_record

        dag = {
            "id": "loop-794-nobinding",
            "entry_node": "ask",
            "nodes": [
                {
                    "id": "ask",
                    "kind": "human.approve_draft",
                    "inputs": {"draft": {"x": 1}, "timeout_seconds": 3600},
                }
            ],
            "edges": [],
        }
        record = durable_record(
            dag,
            run_id="run-794-nobinding",
            status=RunStatusModel.PAUSED,
            active_node_id="ask",
            workspace_id=WORKSPACE_ID,
            node_runs=(
                NodeRun(
                    run_id="run-794-nobinding",
                    node_id="ask",
                    ordinal=1,
                    status=RunStatusModel.PAUSED,
                ),
            ),
            metadata={
                "initial_inputs": {},
                "hitl_answers": {},
                "pauses": {
                    "ask": {
                        "kind": "hitl",
                        "metadata": {},
                        "resume_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                    }
                },
            },
        )
        await store.create(record)
        with pytest.raises(FenceNotWaitingError, match="no loop binding"):
            await store.park_hitl(record.run_id, "ask", authorization=_authorization())

    @pytest.mark.asyncio
    async def test_settlements_after_the_deadline_are_refused_for_every_verb(
        self, world: _World, run_store: InMemoryRunStore, store: InMemoryDurableRunStore
    ) -> None:
        """Park/redirect/accept extend the #737 rule unchanged: the persisted
        deadline is the deadline, and a late decision cannot outrun it."""
        paused = await _run_to_fence(store, run_store, world, timeout_seconds=3600)
        deadline = hitl_deadline(paused, NODE_FENCE)
        assert deadline is not None
        late = deadline + timedelta(seconds=1)
        auth = _authorization()
        with pytest.raises(HitlDeadlineElapsed):
            await store.park_hitl(paused.run_id, NODE_FENCE, authorization=auth, at=late)
        with pytest.raises(HitlDeadlineElapsed):
            await redirect_fence(
                store,
                paused.run_id,
                NODE_FENCE,
                target=FenceRedirectTarget.BRIEF,
                authorization=auth,
                at=late,
            )
        with pytest.raises(HitlDeadlineElapsed):
            await accept_fence(
                store,
                paused.run_id,
                NODE_FENCE,
                authorization=auth,
                rubrics=world.rubrics,
                run_store=run_store,
                at=late,
            )


# --- Canonical spine parity: fence decisions mirror onto the Run ---------------


class TestCanonicalSpineParity:
    @pytest.mark.asyncio
    async def test_fence_decisions_mirror_onto_the_canonical_run_store(
        self, world: _World, run_store: InMemoryRunStore
    ) -> None:
        canonical = CanonicalDurableRunStore(run_store, InMemoryGraphContinuationStore())
        paused = await _run_to_fence(canonical, run_store, world)
        assert paused.status is RunStatus.PAUSED

        spine_before = await run_store.get_run(paused.run_id)
        assert spine_before is not None
        assert spine_before.status is RunStatusModel.PAUSED

        parked = await canonical.park_hitl(
            paused.run_id, NODE_FENCE, authorization=_authorization()
        )
        assert parked.status is RunStatus.PAUSED

        accepted = await canonical.accept_hitl(
            parked.run_id,
            NODE_FENCE,
            gate_passed=True,
            authorization=_authorization(),
        )
        assert accepted.status is RunStatus.QUEUED
        # The durable decision mirrored onto the canonical Run: the spine no
        # longer says PAUSED, and no second lifecycle was invented.
        spine_after = await run_store.get_run(paused.run_id)
        assert spine_after is not None
        assert spine_after.status is RunStatusModel.QUEUED
        resumed = await resume_durable_graph(
            paused.run_id, store=canonical, node_resolver=_fence_resolver, run_store=run_store
        )
        assert resumed.status is RunStatus.COMPLETED
        spine_done = await run_store.get_run(paused.run_id)
        assert spine_done is not None and spine_done.status is RunStatusModel.COMPLETED

        # The redirect verb mirrors the same way: park holds, a brief redirect
        # re-queues with the new version on the spine Run's provenance, and
        # the resumed fence node consumed the recorded decision.
        fence2 = await _run_to_fence(canonical, run_store, world)
        parked2 = await canonical.park_hitl(
            fence2.run_id, NODE_FENCE, authorization=_authorization()
        )
        assert parked2.status is RunStatus.PAUSED
        redirected = await canonical.redirect_hitl(
            fence2.run_id,
            NODE_FENCE,
            target=FenceRedirectTarget.BRIEF.value,
            new_brief_version=2,
            authorization=_authorization(),
        )
        assert redirected.status is RunStatus.QUEUED
        # The durable binding moved (the loop consumes the new version); the
        # spine Run's launch provenance stays as admitted (#1572) — the
        # canonical record is re-projected from the spine, so the redirect
        # authority lives in the graph state, not the spine row.
        assert fence_binding(redirected)["brief_version"] == 2
        assert redirected.run.provenance["brief_version"] == 1
        resumed2 = await resume_durable_graph(
            fence2.run_id, store=canonical, node_resolver=_fence_resolver, run_store=run_store
        )
        assert resumed2.status is RunStatus.COMPLETED
        decisions = fence_decisions_of(resumed2)
        assert [d.decision for d in decisions] == [
            FenceDecisionKind.PARK,
            FenceDecisionKind.REDIRECT,
        ]
        assert decisions[-1].redirect_target is FenceRedirectTarget.BRIEF
        assert decisions[-1].new_brief_version == 2
        spine_done2 = await run_store.get_run(fence2.run_id)
        assert spine_done2 is not None and spine_done2.status is RunStatusModel.COMPLETED
