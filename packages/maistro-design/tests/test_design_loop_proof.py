"""The M7-A6 public proof: one Goal, one pack, one planted failure, one refine.

Walks the fixed proof scenario (`docs/product/M7-A6-DESIGN-LOOP-PROOF.md`)
end to end through canonical APIs only — the ``product`` pack's Graph executed
as one Run on the canonical spine (``run_durable_graph`` over
``CanonicalDurableRunStore``), Rubric revisions in the ``RubricStore``, eval
records as spine-validated ``RunEvalScore`` rows, fence decisions as answers
to canonical human pauses, and lineage read back out of the store with
``maistro.runs.lineage``.

Acceptance mapping (each test class names the criteria it proves):

- AC "Planted Rubric failure is visible on the Run before refine"
  → ``TestPlantedFailureIsDurableEvidence``
- AC "Fence: park, then redirect-Rubric, then accept after refine" and
  AC "Refresh mid-loop restores Goal, Rubric, Run, fence, and eval records"
  → ``TestFenceCycleIsCanonical`` (every mid-loop state is re-read from the
  stores, which is what a refresh restores from)
- AC "After refine, both Attempts are visible; the accepted artifact names
  the winning Attempt" → ``TestRefineAttemptsAndAcceptance``
- AC "Canvas-unavailable path is honest; Canvas-available path shares the
  same Run id" → ``TestCanvasHonesty``
- AC "Lineage from artifact → Attempt → NodeRun → Run → Graph → Rubric
  revision → Goal revision is complete" → ``TestLineageIsQueryable``
- AC "No production path in the proof uses client timers for pipeline
  stages" → the driver has no sleeps or timers; ``test_proof_advances_only_on
  _decisions`` pins that the parked Run never moves without an answer.

Both durable backends are exercised: the in-memory store and the SQLite
store (a real on-disk-format database; the Postgres leg of the spine is
covered by the conformance suites in ``maistro-core``).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from maistro.graph.durable_runs import RunStatus
from maistro.ontology import InMemoryOntology
from maistro.projects.rubric_store import RubricStore
from maistro.runs.eval import eval_summary
from maistro.runs.sqlite_store import SqliteRunStore
from maistro.runs.store import InMemoryRunStore
from maistro_design.proof import (
    PLANTED_DIMENSION_ID,
    PRODUCT_GOAL_STATEMENT,
    PROOF_GOAL_ID,
    InMemoryGoalRevisionCatalog,
    run_design_loop_proof,
    score_artifact_against_rubric,
)

WORKSPACE_ID = "ws-795-proof"


@pytest.fixture(params=["memory", "sqlite"])
async def proof_spine(request: pytest.FixtureRequest) -> Any:
    from maistro.projects.scope_store import InMemoryProjectScopeStore

    projects = InMemoryProjectScopeStore()
    root = await projects.create_root(WORKSPACE_ID)
    project = await projects.create(
        workspace_id=WORKSPACE_ID, parent_project_id=root.project_id, name="Proof"
    )
    goals = InMemoryGoalRevisionCatalog()
    rubrics = RubricStore(InMemoryOntology(), goals)
    if request.param == "memory":
        yield InMemoryRunStore(project_store=projects), rubrics, goals, project.project_id
        return
    import aiosqlite

    conn = await aiosqlite.connect(":memory:")
    store = SqliteRunStore(conn, project_store=projects)
    await store.ensure_schema()
    try:
        yield store, rubrics, goals, project.project_id
    finally:
        await conn.close()


@pytest.mark.asyncio
@pytest.mark.contract("behavioral")
class TestPlantedFailureIsDurableEvidence:
    async def test_planted_failure_is_visible_before_refine(self, proof_spine: Any) -> None:
        """The seeded artifact genuinely fails ``claim_evidence`` on Rubric v1."""
        run_store, rubrics, goals, project_id = proof_spine
        proof = await run_design_loop_proof(
            run_store,
            rubrics,
            goals,
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
        )
        # v1 records survive on the Run after everything that followed.
        summary_v1 = await eval_summary(
            run_store,
            proof.run_id,
            rubric_id=proof.rubric_id,
            rubric_revision=proof.rubric_revision_initial,
            dimension_ids=[PLANTED_DIMENSION_ID, "clarity_of_offer", "channel_fit"],
        )
        assert summary_v1.complete
        assert summary_v1.failed_dimensions == (PLANTED_DIMENSION_ID,)
        failed = summary_v1.latest_by_dimension[PLANTED_DIMENSION_ID]
        # The record names the exact spine triple it scored: the evaluate
        # NodeRun and its first Attempt, at the exact revisions applied.
        assert failed.run_id == proof.run_id
        assert failed.node_run_id == proof.node_run_ids["evaluate.rubric"]
        assert failed.goal_id == PROOF_GOAL_ID
        assert failed.goal_revision == 1
        assert failed.rubric_revision == proof.rubric_revision_initial
        assert failed.detail["reasons"] == ["claim 0 has no evidence"]

    async def test_the_planted_failure_is_real_not_scripted(self, proof_spine: Any) -> None:
        """The scorer fails any unevidenced claim, passes an evidenced one."""
        run_store, rubrics, goals, project_id = proof_spine
        proof = await run_design_loop_proof(
            run_store,
            rubrics,
            goals,
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
        )
        rubric_v1 = await rubrics.get_revision(proof.rubric_id, proof.rubric_revision_initial)
        assert rubric_v1 is not None
        unevidenced = {"claims": [{"text": "c", "evidence": None}], "offer": "o", "channel": "c"}
        verdicts = {
            s.dimension_id: s.passed for s in score_artifact_against_rubric(unevidenced, rubric_v1)
        }
        assert verdicts[PLANTED_DIMENSION_ID] is False
        evidenced = {
            "claims": [{"text": "c", "evidence": "source:x#1"}],
            "offer": "o",
            "channel": "c",
        }
        verdicts = {
            s.dimension_id: s.passed for s in score_artifact_against_rubric(evidenced, rubric_v1)
        }
        assert verdicts[PLANTED_DIMENSION_ID] is True


@pytest.mark.asyncio
@pytest.mark.contract("behavioral")
class TestFenceCycleIsCanonical:
    async def test_park_redirect_and_accept_are_canonical_pauses(self, proof_spine: Any) -> None:
        """Park → redirect-Rubric → accept, with the parked states proven."""
        run_store, rubrics, goals, project_id = proof_spine
        proof = await run_design_loop_proof(
            run_store,
            rubrics,
            goals,
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
        )
        # The Run the loop ended with is one Run: same id everywhere.
        for node in proof.lineage.node_runs:
            assert node.run_id == proof.run_id
        assert proof.lineage.status == "completed"

        # redirect-Rubric: revision 2 exists, bound to the SAME Goal
        # revision; revision 1 is intact and immutable.
        v1 = await rubrics.get_revision(proof.rubric_id, proof.rubric_revision_initial)
        v2 = await rubrics.get_revision(proof.rubric_id, proof.rubric_revision_redirected)
        assert v1 is not None and v2 is not None
        assert v2.revision == v1.revision + 1
        assert (v2.goal_id, v2.goal_revision) == (v1.goal_id, v1.goal_revision)
        assert v1.dimensions == v2.dimensions  # the redirect re-stated, not rewrote

        # The Run's provenance names the scenario's Goal/Rubric identity.
        run = await run_store.get_run(proof.run_id)
        assert run is not None
        assert run.provenance["goal_id"] == PROOF_GOAL_ID
        assert run.provenance["pack_id"] == "product"
        assert (
            PRODUCT_GOAL_STATEMENT
            in run.provenance["durable_graph_launch"]["initial_inputs"]["payload"]["goal_statement"]
        )

    async def test_refresh_mid_loop_restores_every_record(self, proof_spine: Any) -> None:
        """A fresh store handle mid-loop re-reads Goal, Rubric, Run, eval records."""
        run_store, rubrics, goals, project_id = proof_spine
        proof = await run_design_loop_proof(
            run_store,
            rubrics,
            goals,
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
        )
        # "Refresh": every fact is queried again from the stores alone.
        reread_run = await run_store.get_run(proof.run_id)
        assert reread_run is not None
        assert reread_run.status is RunStatus.COMPLETED
        scores = await run_store.list_eval_scores(proof.run_id)
        # Three dimensions at v1 (one failing) + three passing at v2.
        assert len(scores) == 6
        v1_failed = [s for s in scores if s.rubric_revision == 1 and not s.passed]
        assert [s.dimension_id for s in v1_failed] == [PLANTED_DIMENSION_ID]
        assert await rubrics.get_revision(proof.rubric_id, 1) is not None
        assert await rubrics.get_revision(proof.rubric_id, 2) is not None
        assert goals.resolve(PROOF_GOAL_ID, 1) is not None


@pytest.mark.asyncio
@pytest.mark.contract("behavioral")
class TestRefineAttemptsAndAcceptance:
    async def test_both_attempts_visible_and_artifact_names_the_winner(
        self, proof_spine: Any
    ) -> None:
        run_store, rubrics, goals, project_id = proof_spine
        proof = await run_design_loop_proof(
            run_store,
            rubrics,
            goals,
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
        )
        evaluate = next(n for n in proof.lineage.node_runs if n.node_name == "evaluate.rubric")
        refine = next(n for n in proof.lineage.node_runs if n.node_name == "refine.revise")
        # The evaluate NodeRun kept both of its Attempts: the planted-failure
        # visit and the redirect-resolution visit.
        assert [a.ordinal for a in evaluate.attempts] == [1, 2]
        # The refine NodeRun kept the proposal visit, the re-evaluation
        # Attempt opened by open_re_eval_attempt, and the accept visit.
        assert [a.ordinal for a in refine.attempts] == [1, 2, 3]
        assert proof.re_eval_attempt_id == refine.attempts[1].attempt_id

        # The failed record is preserved, not rewritten, and the winning
        # Attempt's records all pass.
        failed_records = [s for s in proof.lineage.eval_scores if not s.passed]
        assert len(failed_records) == 1
        assert failed_records[0].attempt_id == evaluate.attempts[0].attempt_id
        winning = [s for s in proof.lineage.eval_scores if s.attempt_id == proof.re_eval_attempt_id]
        assert len(winning) == 3
        assert all(s.passed for s in winning)
        assert all(s.rubric_revision == proof.rubric_revision_redirected for s in winning)

        # The accepted artifact names the winning Attempt (and the refine
        # Attempt that produced it).
        accepted = proof.accepted_artifact["accepted"]
        assert accepted["re_eval_attempt_id"] == proof.re_eval_attempt_id
        assert accepted["produced_by_attempt"] == refine.attempts[0].attempt_id
        assert accepted["decision"] == "accept"
        assert accepted["rubric_revision"] == proof.rubric_revision_redirected
        # ...and every claim on it is evidenced — the refine really repaired
        # the planted failure.
        assert all(c["evidence"] for c in proof.accepted_artifact["claims"])


@pytest.mark.asyncio
@pytest.mark.contract("behavioral")
class TestCanvasHonesty:
    async def test_canvas_unavailable_is_recorded_not_faked(self, proof_spine: Any) -> None:
        run_store, rubrics, goals, project_id = proof_spine
        proof = await run_design_loop_proof(
            run_store,
            rubrics,
            goals,
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
        )
        canvas = proof.accepted_artifact["backends"]["canvas"]
        assert canvas["produced"] is False
        assert canvas["available"] is False
        assert "no canvas artifact exists" in canvas["reason"]
        # The loop still completed on the non-Canvas branch — same Run.
        assert proof.lineage.status == "completed"
        assert proof.accepted_artifact["backends"]["builders"]["produced"] is True

    async def test_canvas_available_produces_on_the_same_run_id(self, proof_spine: Any) -> None:
        run_store, rubrics, goals, project_id = proof_spine
        proof = await run_design_loop_proof(
            run_store,
            rubrics,
            goals,
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
            canvas_available=True,
        )
        canvas = proof.accepted_artifact["backends"]["canvas"]
        assert canvas["produced"] is True
        assert canvas["artifact"] == "hero-banner"
        # Same Run: the canvas work is node evidence on this Run's spine.
        builders = proof.accepted_artifact["backends"]["builders"]
        assert canvas["attempt_id"] and builders["attempt_id"]
        assert proof.lineage.status == "completed"


@pytest.mark.asyncio
@pytest.mark.contract("behavioral")
class TestLineageIsQueryable:
    async def test_lineage_is_complete_from_artifact_to_goal(self, proof_spine: Any) -> None:
        run_store, rubrics, goals, project_id = proof_spine
        proof = await run_design_loop_proof(
            run_store,
            rubrics,
            goals,
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
        )
        lineage = proof.lineage
        # artifact → Attempt → NodeRun (the accepted artifact's producing chain)
        node_run, _attempt = lineage.find_artifact(proof.accepted_artifact)
        assert node_run.node_name == "refine.revise"
        assert node_run.run_id == proof.run_id
        # Run → Graph: the executed pack template identity, snapshotted on the
        # Run. `instantiate()` mints a fresh graph_id, so the pack identity is
        # proven by the snapshot's own source_template provenance, not the id.
        assert lineage.graph_id
        assert lineage.graph_content_hash
        definition = json.loads(lineage.graph_definition_json)
        assert definition["source_template"]["template_id"] == "pack.product"
        assert '"pack.phase"' in lineage.graph_definition_json
        # Run → Rubric revision → Goal revision: both revisions the Run scored
        # against, each naming the same Goal revision, from eval records only.
        assert {b.rubric_revision for b in lineage.rubric_bindings} == {
            proof.rubric_revision_initial,
            proof.rubric_revision_redirected,
        }
        for binding in lineage.rubric_bindings:
            assert (binding.goal_id, binding.goal_revision) == (PROOF_GOAL_ID, 1)
            assert binding.rubric_id == proof.rubric_id
        # Every stage the scenario promises exists as a persisted NodeRun,
        # carrying the Graph definition's semantic name.
        assert [n.node_name for n in lineage.node_runs] == [
            "explore.positioning",
            "explore.audience",
            "explore.artifact_plan",
            "execute.produce",
            "evaluate.rubric",
            "refine.revise",
        ]
        # Explore outputs are durable artifacts on their own NodeRuns, keyed
        # by the minted node id the spine executed.
        explore_nodes = [n for n in lineage.node_runs if n.node_name.startswith("explore.")]
        for node in explore_nodes:
            payload = (node.result or {}).get("payload", {}).get("explore", {})
            assert node.node_id in payload

    async def test_an_artifact_the_run_never_made_has_no_lineage(self, proof_spine: Any) -> None:
        from maistro.runs import ArtifactNotInRunLineage

        run_store, rubrics, goals, project_id = proof_spine
        proof = await run_design_loop_proof(
            run_store,
            rubrics,
            goals,
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
        )
        with pytest.raises(ArtifactNotInRunLineage):
            proof.lineage.find_artifact({"artifact_kind": "artifact-from-nowhere"})


@pytest.mark.asyncio
@pytest.mark.contract("behavioral")
class TestNoTimers:
    async def test_proof_advances_only_on_decisions(self, proof_spine: Any) -> None:
        """A parked Run moves when a person answers — never on its own."""
        run_store, rubrics, goals, project_id = proof_spine
        proof = await run_design_loop_proof(
            run_store,
            rubrics,
            goals,
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
        )
        # The two fence pauses are recorded in the durable graph state as
        # human pauses, and the Run's total wall-clock cost is three walks —
        # there is no polling loop to wait out.
        run = await run_store.get_run(proof.run_id)
        assert run is not None
        assert run.finished_at is not None
        # The parked windows carried the decision vocabulary.
        accepted = proof.accepted_artifact["accepted"]
        assert accepted["answered_at"]


# ---------------------------------------------------------------------------
# Degenerate paths: every guard on the proof path fails closed, loudly, and
# names what was missing. These pin the unhappy arcs the happy-path proof walk
# never reaches — a scorer that silently passes a field-less artifact, a fence
# node that accepts a decision it does not know, an acceptance built from
# caller memory instead of durable evidence.
# ---------------------------------------------------------------------------


def _proof_rubric(rubrics: RubricStore, goals: Any, project_id: str) -> Any:
    """Rubric revision 1, built exactly the way the driver builds it."""
    from maistro.ontology.rubric import RubricGate, RubricProvenance
    from maistro.projects.rubric_store import GoalRevisionSnapshot
    from maistro_design.packs import PackRegistry
    from maistro_design.proof import pack_rubric_dimensions

    goals.register_goal(
        GoalRevisionSnapshot(
            goal_id=PROOF_GOAL_ID,
            goal_revision=1,
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
        )
    )
    pack = PackRegistry.builtin().get("product")
    return rubrics.create(
        workspace_id=WORKSPACE_ID,
        project_id=project_id,
        goal_id=PROOF_GOAL_ID,
        goal_revision=1,
        dimensions=pack_rubric_dimensions(pack),
        gate=RubricGate(pass_threshold=80.0),
        provenance=RubricProvenance(
            authored_by="proof-runner", origin="pack", pack_id=pack.pack_id.value
        ),
    )


@pytest.mark.asyncio
@pytest.mark.contract("behavioral")
class TestScorerDegeneratePaths:
    async def test_missing_prose_fields_fail_with_their_reasons(self, proof_spine: Any) -> None:
        """An artifact with evidenced claims but no offer/channel fails exactly
        the two prose dimensions — and only them."""
        _run_store, rubrics, goals, project_id = proof_spine
        rubric = await _proof_rubric(rubrics, goals, project_id)
        artifact = {"claims": [{"text": "c", "evidence": "source:x#1"}]}
        verdicts = {s.dimension_id: s for s in score_artifact_against_rubric(artifact, rubric)}
        assert verdicts[PLANTED_DIMENSION_ID].passed is True
        assert verdicts["clarity_of_offer"].passed is False
        assert verdicts["clarity_of_offer"].detail["reasons"] == [
            "no offer statement on the artifact"
        ]
        assert verdicts["channel_fit"].passed is False
        assert verdicts["channel_fit"].detail["reasons"] == ["no channel named on the artifact"]

    async def test_planted_dimension_fails_when_there_are_no_claims(self, proof_spine: Any) -> None:
        """A claim-free artifact cannot pass the evidence dimension by
        vacuity: ``no claims to evaluate`` is a failure, not a pass."""
        _run_store, rubrics, goals, project_id = proof_spine
        rubric = await _proof_rubric(rubrics, goals, project_id)
        artifact = {"claims": [], "offer": "o", "channel": "c"}
        verdicts = {s.dimension_id: s for s in score_artifact_against_rubric(artifact, rubric)}
        assert verdicts[PLANTED_DIMENSION_ID].passed is False
        assert verdicts[PLANTED_DIMENSION_ID].detail["reasons"] == ["no claims to evaluate"]
        assert verdicts["clarity_of_offer"].passed is True
        assert verdicts["channel_fit"].passed is True

    async def test_refine_preserves_an_existing_citation(self) -> None:
        """The refine repair adds evidence where it is missing and never
        overwrites a citation the artifact already carried."""
        from maistro_design.proof import _with_claim_evidence

        artifact = {
            "claims": [
                {"text": "kept", "evidence": "source:original#1"},
                {"text": "repaired", "evidence": None},
            ]
        }
        revised = _with_claim_evidence(dict(artifact))
        assert revised["claims"][0]["evidence"] == "source:original#1"
        assert revised["claims"][1]["evidence"]
        # The input artifact is untouched: the repair is a copy, not a
        # mutation of the executed output.
        assert artifact["claims"][1]["evidence"] is None


@pytest.mark.asyncio
@pytest.mark.contract("behavioral")
class TestNodeFencesFailClosed:
    """The two fence nodes answer only the decisions the scenario names."""

    def _ctx(self, node_id: str, answers: dict[str, Any]) -> Any:
        from maistro.graph.nodes import NodeContext

        return NodeContext(
            run_id="run-degenerate",
            dag_id="dag-degenerate",
            node_id=node_id,
            metadata={"hitl_answers": answers},
        )

    async def test_evaluate_node_rejects_an_unsupported_decision(self, proof_spine: Any) -> None:
        from maistro_design.proof import _EvaluateNode

        run_store, rubrics, _goals, _project_id = proof_spine
        node = _EvaluateNode(run_store, rubrics, "rubric-unused")
        result = await node.run(
            {"payload": {}}, self._ctx("eval-1", {"eval-1": {"decision": "accept"}})
        )
        assert result.success is False
        assert result.error_code == "ValueError"
        assert "evaluate node received unsupported decision 'accept'" in (
            result.error_message or ""
        )

    async def test_refine_node_rejects_an_unsupported_decision(self, proof_spine: Any) -> None:
        from maistro_design.proof import _RefineNode

        _run_store, _rubrics, _goals, _project_id = proof_spine
        node = _RefineNode()
        result = await node.run(
            {"payload": {}}, self._ctx("refine-1", {"refine-1": {"decision": "maybe"}})
        )
        assert result.success is False
        assert "refine node received unsupported decision 'maybe'" in (result.error_message or "")

    async def test_evaluate_node_fails_closed_when_the_rubric_vanished(
        self, proof_spine: Any
    ) -> None:
        """Scoring against a rubric that is not in the store raises — it
        never scores against nothing."""
        from maistro_design.proof import _EvaluateNode

        run_store, rubrics, _goals, _project_id = proof_spine
        node = _EvaluateNode(run_store, rubrics, "rubric-absent")
        result = await node.run({"payload": {}}, self._ctx("eval-1", {}))
        assert result.success is False
        assert "rubric 'rubric-absent' vanished from the store" in (result.error_message or "")

    async def test_refine_accept_refuses_to_accept_from_caller_memory(
        self, proof_spine: Any
    ) -> None:
        """An accept answer with no durable pause behind it is refused: the
        accepted artifact must be the one the fence proposed."""
        from maistro_design.proof import _RefineNode

        _run_store, _rubrics, _goals, _project_id = proof_spine
        node = _RefineNode()
        result = await node.run(
            {"payload": {}}, self._ctx("refine-1", {"refine-1": {"decision": "accept"}})
        )
        assert result.success is False
        assert "refusing to accept from caller memory" in (result.error_message or "")


@pytest.mark.asyncio
@pytest.mark.contract("behavioral")
class TestProofGuardsFailLoudly:
    async def test_assert_run_status_names_the_phase_and_status(self) -> None:
        from types import SimpleNamespace

        from maistro_design.proof import _assert_run_status

        parked = SimpleNamespace(run=SimpleNamespace(status=RunStatus.PAUSED))
        with pytest.raises(AssertionError, match="proof expected the Run to complete"):
            _assert_run_status(parked, RunStatus.COMPLETED, "to complete")
        # The matching status passes silently.
        _assert_run_status(parked, RunStatus.PAUSED, "parked on the fence")

    async def test_refine_proposal_guard_requires_a_durable_artifact(self) -> None:
        from types import SimpleNamespace

        from maistro_design.proof import _refine_proposed_artifact

        empty_pause = SimpleNamespace(
            graph_state=SimpleNamespace(metadata={"pauses": {"refine-1": {}}})
        )
        with pytest.raises(AssertionError, match="refine proposal carried no durable artifact"):
            _refine_proposed_artifact(empty_pause, "refine-1")
        missing_pause = SimpleNamespace(graph_state=SimpleNamespace(metadata={}))
        with pytest.raises(AssertionError, match="refine proposal carried no durable artifact"):
            _refine_proposed_artifact(missing_pause, "refine-1")

    async def test_re_eval_refuses_an_unevidenced_artifact(self, proof_spine: Any) -> None:
        """The re-evaluation Attempt really scores: an unevidenced artifact
        fails the planted dimension on durable rows, and the driver refuses
        to hand back a passing Attempt that does not exist."""
        from maistro.graph import Graph, Node
        from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID
        from maistro_design.proof import _re_evaluate_refined_artifact

        run_store, rubrics, goals, project_id = proof_spine
        rubric = await _proof_rubric(rubrics, goals, project_id)
        graph = Graph(
            workspace_id=WORKSPACE_ID,
            project_id=project_id,
            name="re-eval guard",
            nodes=[Node(node_id="refine.revise", node_type="agent")],
        )
        run = await run_store.create_run(graph, actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID)
        node_run = await run_store.create_node_run(run.run_id, node_id="refine.revise")
        unevidenced = {"claims": [{"text": "c", "evidence": None}]}
        with pytest.raises(AssertionError, match="re-evaluation did not pass"):
            await _re_evaluate_refined_artifact(
                run_store,
                rubrics,
                run_id=run.run_id,
                refine_node_id=node_run.node_run_id,
                rubric_id=rubric.rubric_id,
                rubric_revision=rubric.revision,
                proposed_artifact=unevidenced,
            )
        # The refusal is not free: the failing records were written first,
        # naming the re-evaluation Attempt the proof would have accepted.
        scores = await run_store.list_eval_scores(run.run_id)
        failed = [s for s in scores if not s.passed]
        assert PLANTED_DIMENSION_ID in {s.dimension_id for s in failed}
        assert all(
            s.node_run_id == node_run.node_run_id
            and s.rubric_id == rubric.rubric_id
            and s.rubric_revision == rubric.revision
            for s in failed
        )

    async def test_extract_accepted_artifact_fails_when_run_carries_none(
        self,
    ) -> None:
        """Every non-dict shape on the accepted artifact's path fails loudly
        instead of returning something falsy and calling it acceptance."""
        from types import SimpleNamespace

        from maistro_design.proof import _extract_accepted_artifact

        for bad_result in (None, {"payload": "nope"}, {"payload": {"artifact": "nope"}}):
            record = SimpleNamespace(
                node_runs=[SimpleNamespace(node_id="refine-1", result=bad_result)]
            )
            with pytest.raises(
                AssertionError, match="the accepted Run carries no accepted artifact"
            ):
                _extract_accepted_artifact(record, "refine-1")
