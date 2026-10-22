"""The M7-A6 public proof — one Goal, one pack, one planted failure, one refine.

This module is the documented seed of the proof scenario
(``docs/product/M7-A6-DESIGN-LOOP-PROOF.md``): the ``product`` pack (M7-A4)
executes the closed design loop (ADR-092926-7a01) as **one Graph executed as
one Run** on the canonical spine, with every stage inspectable as persisted
objects:

1. A live Goal revision (the canonical Goal system's seam, #458).
2. A Rubric instantiated from the pack's dimension catalog, bound to that
   Goal revision, with a **planted failing dimension** — the seeded artifact
   genuinely lacks the evidence the ``claim_evidence`` dimension requires.
3. Explore outputs as durable NodeRun/Attempt artifacts.
4. Execute through the non-Canvas ``builders`` backend and — when the caller
   says Canvas is available — the ``canvas`` backend, both on the same Run.
   When Canvas is unavailable the Run records exactly that, with no canvas
   artifact attached: the Canvas branch fails honestly, never a timer-faked
   success (#286, #465).
5. Eval records on that Run (`RunEvalScore`, spine-validated), including
   the planted failure.
6. Fence: the Run parks in a canonical human pause (``PAUSED``,
   ``PAUSE_AWAITING_HUMAN_REVIEW``) on the ``evaluate.accept`` fence point;
   the person redirects the *scoring* (a new Rubric revision bound to the
   **same** Goal revision — never a mutation), and after the refine
   re-evaluation passes, accepts.
7. Refine: ``open_re_eval_attempt`` opens the retry Attempt on the parked
   refine NodeRun; the failed eval record is preserved and the passing
   records name the new Attempt.
8. Lineage: ``maistro.runs.lineage`` reconstructs artifact → Attempt →
   NodeRun → Run → Graph → Rubric revision → Goal revision from the store,
   never from caller memory.

Deterministic by construction: every node is an in-process executor (the
established pack-test pattern), scoring is a pure function, and there are no
sleeps, timers, or client-side state anywhere.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from pydantic import BaseModel

from maistro.graph.durable_runs import (
    CanonicalDurableRunStore,
    DurableRunRecord,
    InMemoryGraphContinuationStore,
)
from maistro.graph.durable_runs.attempt_executor import resume_durable_graph, run_durable_graph
from maistro.graph.durable_runs.launch import durable_graph_launch_provenance
from maistro.graph.durable_runs.stores import answer_record
from maistro.graph.nodes import BaseNode, NodeContext, pause_until
from maistro.graph.nodes.base import PAUSE_AWAITING_HUMAN_REVIEW, resumed_pause
from maistro.ontology.rubric import (
    NumericScale,
    PackRubricCatalog,
    PassFailScale,
    RubricDimension,
    RubricGate,
    RubricProvenance,
    RubricScale,
    ScoringMethod,
)
from maistro.projects.rubric_store import (
    GoalRevisionSnapshot,
    RubricStore,
)
from maistro.runs.eval import eval_summary, open_re_eval_attempt
from maistro.runs.lineage import RunLineage, artifact_lineage
from maistro.runs.model import Attempt, AttemptStatus, EvalMethod, RunEvalScore, RunStatus
from maistro.runs.store import RunStore
from maistro_design.packs import PackRegistry, pack_graph_template

__all__ = [
    "PLANTED_DIMENSION_ID",
    "PRODUCT_GOAL_STATEMENT",
    "PROOF_GOAL_ID",
    "DesignLoopProof",
    "InMemoryGoalRevisionCatalog",
    "pack_rubric_catalog",
    "run_design_loop_proof",
    "score_artifact_against_rubric",
]


class InMemoryGoalRevisionCatalog:
    """Dict-backed :class:`~maistro.projects.rubric_store.GoalRevisionCatalog`.

    The Goal seam (#458) is a Protocol; this proof owns a live in-memory
    implementation of it so the scenario can register a Goal revision and let
    the ``RubricStore`` resolve it without a second Goal persistence product.
    """

    def __init__(self) -> None:
        self._goals: dict[tuple[str, int], GoalRevisionSnapshot] = {}

    def register_goal(self, snapshot: GoalRevisionSnapshot) -> GoalRevisionSnapshot:
        """Publish one live Goal revision (proof/boot helper)."""
        self._goals[(snapshot.goal_id, snapshot.goal_revision)] = snapshot.model_copy(deep=True)
        return snapshot

    def resolve(self, goal_id: str, goal_revision: int) -> GoalRevisionSnapshot | None:
        snap = self._goals.get((goal_id, goal_revision))
        return snap.model_copy(deep=True) if snap is not None else None


#: The proof Goal, verbatim from the issue: one claim that must be
#: evidence-backed.
PRODUCT_GOAL_STATEMENT = (
    "Launch a single-SKU store page with one claim that must be evidence-backed."
)
PROOF_GOAL_ID = "goal-proof-single-sku"

#: The dimension the fixture plants a failure on: the seeded artifact makes
#: the Goal's one claim without evidence, so the dimension genuinely fails.
PLANTED_DIMENSION_ID = "claim_evidence"

_UNEVIDENCED_CLAIM = {"text": "Holds 40% more than the leading brand", "evidence": None}
_CLAIM_EVIDENCE_CITATION = "source:review-notes#12"

#: Deterministic scale assignments for the product pack's dimensions: the
#: claim dimension is pass/fail, the prose dimensions score 0-100.
_SCALES: dict[str, RubricScale] = {
    "clarity_of_offer": RubricScale(numeric=NumericScale()),
    PLANTED_DIMENSION_ID: RubricScale(pass_fail=PassFailScale()),
    "channel_fit": RubricScale(numeric=NumericScale()),
}


def pack_rubric_catalog(pack_id: str, dimensions: list[RubricDimension]) -> PackRubricCatalog:
    """Project the pack's default dimensions into an ontology pack catalog."""
    return PackRubricCatalog(
        pack_id=pack_id,
        name=f"{pack_id} proof rubric",
        dimensions=dimensions,
        gate=RubricGate(pass_threshold=80.0),
    )


def pack_rubric_dimensions(pack: Any) -> list[RubricDimension]:
    """The pack manifest's dimensions as scoreable ontology dimensions."""
    mapped: list[RubricDimension] = []
    for dimension in pack.rubric_dimensions:
        mapped.append(
            RubricDimension(
                id=dimension.dimension_id,
                name=dimension.name,
                weight=1.0,
                scale=_SCALES.get(dimension.dimension_id, RubricScale(numeric=NumericScale())),
                method=ScoringMethod.DETERMINISTIC,
                evidence_required=dimension.dimension_id == PLANTED_DIMENSION_ID,
            )
        )
    return mapped


def _unevidenced_claims(claims: list[dict[str, Any]]) -> list[str]:
    """The planted-failure verdict's reasons: one line per uncited claim."""
    return [
        f"claim {index} has no evidence"
        for index, claim in enumerate(claims)
        if not claim.get("evidence")
    ]


def _presence_verdict(value: str, reason: str) -> tuple[float, bool, list[str]]:
    """Score a prose dimension purely on whether the artifact names the field."""
    if value:
        return 100.0, True, []
    return 0.0, False, [reason]


def _planted_verdict(
    claims: list[dict[str, Any]], missing_evidence: list[str]
) -> tuple[float, bool, list[str]]:
    """The planted dimension: passes only when claims exist and all are cited."""
    if not claims:
        return 0.0, False, ["no claims to evaluate"]
    if missing_evidence:
        return 0.0, False, list(missing_evidence)
    return 100.0, True, []


def _claim_evidence_pointers(claims: list[dict[str, Any]]) -> list[str]:
    """The citations the evidenced claims carry, deduped, first-seen order.

    These justify the ``claim_evidence`` verdict, so the persisted score
    names them: the score-to-evidence lineage stays inspectable from the
    canonical record alone, without excavating the Attempt payload.
    """
    pointers: list[str] = []
    for claim in claims:
        citation = str(claim.get("evidence") or "").strip()
        if citation and citation not in pointers:
            pointers.append(citation)
    return pointers


def score_artifact_against_rubric(artifact: dict[str, Any], rubric: Any) -> list[RunEvalScore]:
    """Score one artifact deterministically against one Rubric revision.

    Returns one unsaved :class:`RunEvalScore` per dimension (method
    ``deterministic`` — no judge, no LLM: ADR-061 keeps model calls out of
    this seam). The ``claim_evidence`` verdict is real: it passes only when
    every claim on the artifact cites evidence. The ``claim_evidence``
    record cites its evidence: its ``evidence_pointers`` carry exactly the
    citations the passing (or attempted) claims carry — empty only when no
    claim is evidenced, i.e. when the dimension fails.
    """
    claims = list(artifact.get("claims") or [])
    evidence_pointers = _claim_evidence_pointers(claims)
    verdicts: dict[str, tuple[float, bool, list[str]]] = {
        "clarity_of_offer": _presence_verdict(
            str(artifact.get("offer") or "").strip(), "no offer statement on the artifact"
        ),
        PLANTED_DIMENSION_ID: _planted_verdict(claims, _unevidenced_claims(claims)),
        "channel_fit": _presence_verdict(
            str(artifact.get("channel") or "").strip(), "no channel named on the artifact"
        ),
    }
    scores: list[RunEvalScore] = []
    for dimension in rubric.dimensions:
        raw, passed, reasons = verdicts.get(
            dimension.id, (0.0, False, ["dimension unknown to the proof scorer"])
        )
        scores.append(
            RunEvalScore(
                run_id="pending",
                node_run_id="pending",
                attempt_id="pending",
                goal_id=rubric.goal_id,
                goal_revision=rubric.goal_revision,
                rubric_id=rubric.rubric_id,
                rubric_revision=rubric.revision,
                dimension_id=dimension.id,
                raw_score=raw,
                passed=passed,
                method=EvalMethod.DETERMINISTIC,
                evidence_pointers=(
                    evidence_pointers if dimension.id == PLANTED_DIMENSION_ID else []
                ),
                detail={"reasons": reasons},
            )
        )
    return scores


class _PhaseIO(BaseModel):
    """The proof nodes pass one JSON payload down the loop."""

    payload: dict[str, Any] = {}


class _ExploreNode(BaseNode[_PhaseIO, _PhaseIO]):
    """Explore phase: each output is the durable artifact its Attempt records."""

    kind: ClassVar[str] = "pack.explore"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _PhaseIO
    output_schema: ClassVar[type[BaseModel]] = _PhaseIO

    async def _execute(self, inputs: _PhaseIO, ctx: NodeContext) -> _PhaseIO:
        payload = dict(inputs.payload)
        explore = dict(payload.get("explore") or {})
        explore[ctx.node_id] = {
            "artifact": f"explore-note:{ctx.node_id}",
            "node_run_id": ctx.node_run_id,
            "attempt_id": ctx.attempt_id,
        }
        payload["explore"] = explore
        return _PhaseIO(payload=payload)


class _ExecuteNode(BaseNode[_PhaseIO, _PhaseIO]):
    """Execute phase: Builders always runs; Canvas only when it is available.

    An unavailable Canvas backend is recorded, on the Run, as exactly that —
    an explicit durable fact with no artifact attached. It is never a fake
    success, never a timer, never a silent skip.
    """

    kind: ClassVar[str] = "pack.execute"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _PhaseIO
    output_schema: ClassVar[type[BaseModel]] = _PhaseIO

    async def _execute(self, inputs: _PhaseIO, ctx: NodeContext) -> _PhaseIO:
        canvas_available = bool(inputs.payload.get("canvas_available"))
        payload = dict(inputs.payload)
        payload["artifact"] = {
            "artifact_kind": "store_page",
            "channel": "store",
            "offer": "The 32 oz Insulated Bottle, in four colors",
            # The planted failure: the Goal's one claim, unevidenced. The
            # refine phase repairs exactly this.
            "claims": [dict(_UNEVIDENCED_CLAIM)],
            "backends": {
                "builders": {"produced": True, "attempt_id": ctx.attempt_id},
                "canvas": (
                    {"produced": True, "attempt_id": ctx.attempt_id, "artifact": "hero-banner"}
                    if canvas_available
                    else {
                        "produced": False,
                        "available": False,
                        "reason": "canvas binding not admitted in this environment; "
                        "no canvas artifact exists for this Run",
                    }
                ),
            },
        }
        return _PhaseIO(payload=payload)


class _EvaluateNode(BaseNode[_PhaseIO, _PhaseIO]):
    """Evaluate phase: deterministic scoring onto the Run, then the fence.

    First visit — score the produced artifact against the bound Rubric
    revision, persist every dimension as a spine-validated ``RunEvalScore``
    on THIS node's Run/NodeRun/Attempt, and park on the ``evaluate.accept``
    fence point with the failed dimensions named. Second visit — the
    person's redirect answer has arrived; record it and continue to refine.
    """

    kind: ClassVar[str] = "pack.evaluate"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _PhaseIO
    output_schema: ClassVar[type[BaseModel]] = _PhaseIO

    def __init__(self, run_store: Any, rubric_store: Any, rubric_id: str) -> None:
        self.run_store = run_store
        self.rubric_store = rubric_store
        self.rubric_id = rubric_id

    async def _execute(self, inputs: _PhaseIO, ctx: NodeContext) -> _PhaseIO:
        answers = (ctx.metadata or {}).get("hitl_answers") or {}
        own = answers.get(ctx.node_id) or {}
        payload = dict(inputs.payload)
        if not own:
            rubric = await self._current_rubric()
            artifact = payload["artifact"]
            for score in score_artifact_against_rubric(artifact, rubric):
                await self.run_store.record_eval_score(
                    score.model_copy(
                        update={
                            "run_id": ctx.run_id,
                            "node_run_id": ctx.node_run_id,
                            "attempt_id": ctx.attempt_id,
                        }
                    )
                )
            pause_until(
                PAUSE_AWAITING_HUMAN_REVIEW,
                metadata={
                    "fence_point": "evaluate.accept",
                    "rubric_id": self.rubric_id,
                    "rubric_revision": rubric.revision,
                    "goal_id": rubric.goal_id,
                    "goal_revision": rubric.goal_revision,
                    "failed_dimensions": [
                        d.id for d in rubric.dimensions if d.id == PLANTED_DIMENSION_ID
                    ],
                    "decision_request": "park | redirect_rubric | redirect_brief | accept",
                },
            )
        decision = own.get("decision")
        if decision == "redirect_rubric":
            payload["fence"] = {
                "resolved": True,
                "decision": "redirect_rubric",
                "rubric_id": own.get("rubric_id"),
                "rubric_revision": own.get("rubric_revision"),
                "answered_at": own.get("answered_at"),
            }
            return _PhaseIO(payload=payload)
        raise ValueError(f"evaluate node received unsupported decision {decision!r}")

    async def _current_rubric(self) -> Any:
        semantic = await self.rubric_store.get(self.rubric_id)
        if semantic is None:
            raise ValueError(f"rubric {self.rubric_id!r} vanished from the store")
        return semantic


def _own_answer(ctx: NodeContext) -> dict[str, Any]:
    """The human's fence answer for this node, or an empty mapping."""
    answers = (ctx.metadata or {}).get("hitl_answers") or {}
    return answers.get(ctx.node_id) or {}


class _RefineNode(BaseNode[_PhaseIO, _PhaseIO]):
    """Refine phase: repair the artifact, propose acceptance, then emit it.

    First visit — rebuild the artifact with the claim's evidence in place
    (the refine that answers the planted failure) and park with an accept
    proposal; the durable pause carries the proposed artifact. Second
    visit — the person has accepted; re-emit the revised artifact naming
    the re-evaluation Attempt whose passing records accepted it and the
    refine Attempt that produced it.
    """

    kind: ClassVar[str] = "pack.refine"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _PhaseIO
    output_schema: ClassVar[type[BaseModel]] = _PhaseIO

    async def _execute(self, inputs: _PhaseIO, ctx: NodeContext) -> _PhaseIO:
        payload = dict(inputs.payload)
        own = _own_answer(ctx)
        if not own:
            self._propose_revision(payload, ctx)
        if own.get("decision") == "accept":
            return self._accept_revision(payload, ctx)
        raise ValueError(f"refine node received unsupported decision {own.get('decision')!r}")

    def _propose_revision(self, payload: dict[str, Any], ctx: NodeContext) -> None:
        """First visit: rebuild the artifact with evidence and park on the fence."""
        revised = _with_claim_evidence(dict(payload.get("artifact") or {}))
        revised["refined_by"] = {"attempt_id": ctx.attempt_id}
        payload["artifact"] = revised
        pause_until(
            PAUSE_AWAITING_HUMAN_REVIEW,
            metadata={
                "fence_point": "evaluate.accept",
                "proposal": "accept",
                "artifact": revised,
                "rubric_id": (payload.get("fence") or {}).get("rubric_id"),
                "rubric_revision": (payload.get("fence") or {}).get("rubric_revision"),
            },
        )

    def _accept_revision(self, payload: dict[str, Any], ctx: NodeContext) -> _PhaseIO:
        """Second visit: emit the artifact the durable pause proposed, accepted."""
        prior = resumed_pause(ctx)
        own = _own_answer(ctx)
        # The accepted artifact is the one the durable pause proposed — read
        # from the pause evidence the answer carried, never rebuilt from the
        # walked-down payload (whose artifact is still the unevidenced first
        # Execute output). The pause's `proposal` value is the string marker
        # "accept"; the artifact sits beside it.
        proposal_artifact = _plain(prior.get("artifact"))
        if not isinstance(proposal_artifact, dict) or not proposal_artifact:
            raise ValueError(
                "refine accept answered but the durable pause carried no "
                "proposed artifact; refusing to accept from caller memory"
            )
        payload["artifact"] = proposal_artifact
        # The accepted artifact itself names the winning Attempt: the
        # acceptance receipt rides on the artifact, so the artifact the fence
        # accepted and the artifact lineage later traces are one object.
        proposal_artifact["accepted"] = {
            "decision": "accept",
            "rubric_id": own.get("rubric_id"),
            "rubric_revision": own.get("rubric_revision"),
            "re_eval_attempt_id": own.get("re_eval_attempt_id"),
            "produced_by_attempt": (proposal_artifact.get("refined_by") or {}).get("attempt_id"),
            "answered_at": own.get("answered_at"),
        }
        payload["accepted"] = dict(proposal_artifact["accepted"])
        return _PhaseIO(payload=payload)


def _with_claim_evidence(artifact: dict[str, Any]) -> dict[str, Any]:
    """The refine repair: every unevidenced claim gains its evidence citation."""
    revised = dict(artifact)
    claims = [dict(claim) for claim in revised.get("claims") or []]
    for claim in claims:
        if not claim.get("evidence"):
            claim["evidence"] = _CLAIM_EVIDENCE_CITATION
    revised["claims"] = claims
    return revised


def _proof_node_resolver(run_store: RunStore, rubric_store: RubricStore, rubric_id: str) -> Any:
    """Resolve each pack phase kind to its deterministic proof executor."""

    def resolve(node_id: str, graph: Any) -> BaseNode[Any, Any]:
        node_type = next(node.node_type for node in graph.nodes if node.node_id == node_id)
        node: BaseNode[Any, Any]
        if node_type == "pack.explore":
            node = _ExploreNode()
        elif node_type == "pack.execute":
            node = _ExecuteNode()
        elif node_type == "pack.evaluate":
            node = _EvaluateNode(
                run_store=run_store, rubric_store=rubric_store, rubric_id=rubric_id
            )
        elif node_type == "pack.refine":
            node = _RefineNode()
        else:  # pragma: no cover - the pack shape fixes the node kinds
            raise KeyError(f"no proof executor for node kind {node_type!r}")
        return node

    return resolve


class DesignLoopProof(BaseModel):
    """The persisted identity of one completed proof Run — ids and lineage."""

    model_config = {"arbitrary_types_allowed": True}

    run_id: str
    graph_id: str
    graph_content_hash: str
    goal_id: str
    goal_revision: int
    rubric_id: str
    rubric_revision_initial: int
    rubric_revision_redirected: int
    node_run_ids: dict[str, str]
    re_eval_attempt_id: str
    accepted_artifact: dict[str, Any]
    lineage: RunLineage

    def __repr__(self) -> str:
        """A stable, log-safe identity for one completed proof Run."""
        return (
            f"DesignLoopProof(run_id={self.run_id!r}, goal_id={self.goal_id!r}, "
            f"rubric_revision_initial={self.rubric_revision_initial}, "
            f"rubric_revision_redirected={self.rubric_revision_redirected}, "
            f"re_eval_attempt_id={self.re_eval_attempt_id!r})"
        )


def _assert_run_status(record: DurableRunRecord, expected: RunStatus, phase: str) -> None:
    """Pin the post-walk Run status to what the proof scenario requires."""
    if record.run.status is not expected:
        raise AssertionError(f"proof expected the Run {phase}, got {record.run.status!r}")


def _refine_proposed_artifact(record: DurableRunRecord, refine_node_id: str) -> dict[str, Any]:
    """The artifact the refine pause proposed, read from durable pause metadata."""
    pauses = record.graph_state.metadata.get("pauses") or {}
    refine_pause = pauses.get(refine_node_id) or {}
    proposed_artifact = _plain((refine_pause.get("metadata") or {}).get("artifact"))
    if not isinstance(proposed_artifact, dict):
        raise AssertionError("refine proposal carried no durable artifact")
    return proposed_artifact


async def _re_evaluate_refined_artifact(
    run_store: RunStore,
    rubric_store: RubricStore,
    *,
    run_id: str,
    refine_node_id: str,
    rubric_id: str,
    rubric_revision: int,
    proposed_artifact: dict[str, Any],
) -> Attempt:
    """Open and run the re-evaluation Attempt on the parked refine NodeRun.

    Returns the completed Attempt. The Attempt's result is the paused
    continuation the executor's contract requires (status ``"paused"``, reason
    ``awaiting_human_review``, carrying the same proposal metadata the refine
    visit wrote): the fence is still the outstanding fact. Completing it as a
    terminal node result would shadow the pause -- the next walk would accept
    the re-evaluation as the node's prior completion and the person's accept
    answer would never re-execute the refine node.
    """
    re_eval = await open_re_eval_attempt(run_store, run_id, refine_node_id)
    await run_store.transition_attempt(re_eval.attempt_id, AttemptStatus.RUNNING)
    rubric_current = await rubric_store.get(rubric_id)
    assert rubric_current is not None and rubric_current.revision == rubric_revision
    for score in score_artifact_against_rubric(proposed_artifact, rubric_current):
        await run_store.record_eval_score(
            score.model_copy(
                update={
                    "run_id": run_id,
                    "node_run_id": refine_node_id,
                    "attempt_id": re_eval.attempt_id,
                }
            )
        )
    summary = await eval_summary(
        run_store,
        run_id,
        rubric_id=rubric_id,
        rubric_revision=rubric_revision,
        dimension_ids=[d.id for d in rubric_current.dimensions],
    )
    if not summary.passed:
        raise AssertionError(f"re-evaluation did not pass: failed={summary.failed_dimensions}")
    return await run_store.transition_attempt(
        re_eval.attempt_id,
        AttemptStatus.COMPLETED,
        result={
            "success": True,
            "status": "paused",
            "output": None,
            "metadata": {
                "paused_reason": PAUSE_AWAITING_HUMAN_REVIEW,
                "fence_point": "evaluate.accept",
                "proposal": "accept",
                "artifact": proposed_artifact,
                "re_evaluated": True,
                "rubric_id": rubric_id,
                "rubric_revision": rubric_revision,
            },
        },
    )


async def run_design_loop_proof(
    run_store: RunStore,
    rubric_store: RubricStore,
    goals: InMemoryGoalRevisionCatalog,
    *,
    workspace_id: str,
    project_id: str,
    goal_id: str = PROOF_GOAL_ID,
    goal_revision: int = 1,
    canvas_available: bool = False,
    actor: str = "proof-runner",
) -> DesignLoopProof:
    """Execute the whole proof scenario against canonical APIs; return its ids.

    Every fence decision below is the person's, applied to a Run parked in a
    canonical human pause; every score and artifact is read back from the
    store. Nothing here sleeps, polls, or advances on a timer.
    """
    goals.register_goal(
        GoalRevisionSnapshot(
            goal_id=goal_id,
            goal_revision=goal_revision,
            workspace_id=workspace_id,
            project_id=project_id,
        )
    )
    pack = PackRegistry.builtin().get("product")

    # -- Rubric revision 1: instantiated from the pack's catalog, bound to the
    #    live Goal revision; provenance records the pack as supplier only.
    rubric_v1 = await rubric_store.create(
        workspace_id=workspace_id,
        project_id=project_id,
        goal_id=goal_id,
        goal_revision=goal_revision,
        dimensions=pack_rubric_dimensions(pack),
        gate=RubricGate(pass_threshold=80.0),
        provenance=RubricProvenance(authored_by=actor, origin="pack", pack_id=pack.pack_id.value),
    )

    # -- The pack's Graph, materialized as a canonical template, admitted as a
    #    Run with its launch state snapshotted for crash recovery.
    template = pack_graph_template(pack, workspace_id=workspace_id)
    graph = template.instantiate(project_id=project_id)
    launch_inputs = {
        "payload": {"goal_statement": PRODUCT_GOAL_STATEMENT, "canvas_available": canvas_available}
    }
    durable = CanonicalDurableRunStore(run_store, InMemoryGraphContinuationStore())
    admitted = await run_store.create_run(
        graph,
        initial_status=RunStatus.QUEUED,
        actor_principal_id=actor,
        provenance={
            "goal_id": goal_id,
            "goal_revision": goal_revision,
            "rubric_id": rubric_v1.rubric_id,
            "rubric_revision": rubric_v1.revision,
            "pack_id": pack.pack_id.value,
            "proof": "M7-A6",
            **durable_graph_launch_provenance(inputs=launch_inputs),
        },
    )
    resolver = _proof_node_resolver(run_store, rubric_store, rubric_v1.rubric_id)
    # GraphTemplate.instantiate() mints fresh node identities; the template's
    # semantic ids survive as node names, so resolve fence targets through
    # them (never through the pre-instantiation ids).
    node_ids = {node.name: node.node_id for node in graph.nodes}
    record = await run_durable_graph(
        graph,
        store=durable,
        node_resolver=resolver,
        run_id=admitted.run_id,
        run_store=run_store,
        inputs=launch_inputs,
    )
    _assert_run_status(record, RunStatus.PAUSED, "parked on the fence")
    node_run_ids = _name_node_run_ids(record, node_ids)

    # -- Fence decision 1: redirect the *scoring*. A new Rubric revision bound
    #    to the SAME Goal revision; revision 1 is never mutated.
    rubric_v2 = await rubric_store.update_dimensions(
        rubric_v1.rubric_id,
        dimensions=[d.model_copy(deep=True) for d in rubric_v1.dimensions],
    )
    await rubric_store.record_run_binding(admitted.run_id, rubric_v2.rubric_id, rubric_v2.revision)
    fetched = await durable.get(admitted.run_id)
    assert fetched is not None
    record = fetched
    answered = answer_record(
        record,
        node_ids["evaluate.rubric"],
        {
            "decision": "redirect_rubric",
            "rubric_id": rubric_v2.rubric_id,
            "rubric_revision": rubric_v2.revision,
            "reason": "acceptance standard restated; the desired outcome is unchanged",
        },
    )
    await durable.update(answered)
    record = await resume_durable_graph(
        admitted.run_id, store=durable, node_resolver=resolver, run_store=run_store
    )
    _assert_run_status(record, RunStatus.PAUSED, "to have the refine proposal parked")
    node_run_ids.update(_name_node_run_ids(record, node_ids))

    # -- Refine re-evaluation: a new Attempt (open_re_eval_attempt) on the
    #    parked refine NodeRun, scoring the refined artifact — read from the
    #    durable pause metadata, not caller memory — against Rubric revision 2.
    fetched = await durable.get(admitted.run_id)
    assert fetched is not None
    proposed_artifact = _refine_proposed_artifact(fetched, node_ids["refine.revise"])
    re_eval = await _re_evaluate_refined_artifact(
        run_store,
        rubric_store,
        run_id=admitted.run_id,
        refine_node_id=node_run_ids["refine.revise"],
        rubric_id=rubric_v2.rubric_id,
        rubric_revision=rubric_v2.revision,
        proposed_artifact=proposed_artifact,
    )

    # -- Fence decision 2: accept, citing the passing re-evaluation Attempt.
    answered = answer_record(
        record,
        node_ids["refine.revise"],
        {
            "decision": "accept",
            "rubric_id": rubric_v2.rubric_id,
            "rubric_revision": rubric_v2.revision,
            "re_eval_attempt_id": re_eval.attempt_id,
            "reason": "re-evaluation passed the redirected Rubric at the same Goal revision",
        },
    )
    await durable.update(answered)
    record = await resume_durable_graph(
        admitted.run_id, store=durable, node_resolver=resolver, run_store=run_store
    )
    _assert_run_status(record, RunStatus.COMPLETED, "to complete")

    # -- Lineage from the accepted artifact, out of the store only.
    accepted_artifact = _extract_accepted_artifact(record, node_ids["refine.revise"])
    lineage, _node_run, _attempt = await artifact_lineage(
        run_store, admitted.run_id, accepted_artifact
    )
    return DesignLoopProof(
        run_id=admitted.run_id,
        graph_id=lineage.graph_id,
        graph_content_hash=lineage.graph_content_hash,
        goal_id=goal_id,
        goal_revision=goal_revision,
        rubric_id=rubric_v1.rubric_id,
        rubric_revision_initial=rubric_v1.revision,
        rubric_revision_redirected=rubric_v2.revision,
        node_run_ids=node_run_ids,
        re_eval_attempt_id=re_eval.attempt_id,
        accepted_artifact=accepted_artifact,
        lineage=lineage,
    )


def _name_node_run_ids(record: DurableRunRecord, node_ids: Mapping[str, str]) -> dict[str, str]:
    """Map the template's semantic node names to the NodeRuns minted so far."""
    id_to_name = {instantiated: name for name, instantiated in node_ids.items()}
    return {
        id_to_name[node_run.node_id]: node_run.node_run_id
        for node_run in record.node_runs
        if node_run.node_id in id_to_name
    }


def _plain(value: Any) -> Any:
    """Unfreeze durable evidence (frozen mappings, tuples) into plain JSON shapes."""
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _extract_accepted_artifact(record: DurableRunRecord, refine_node_id: str) -> dict[str, Any]:
    """The accepted artifact, read from the completed refine NodeRun's result."""
    refine = next(n for n in record.node_runs if n.node_id == refine_node_id)
    result = _plain(refine.result)
    if isinstance(result, dict):
        payload = result.get("payload")
        if isinstance(payload, dict):
            artifact = payload.get("artifact")
            if isinstance(artifact, dict):
                return dict(artifact)
    raise AssertionError("the accepted Run carries no accepted artifact")
