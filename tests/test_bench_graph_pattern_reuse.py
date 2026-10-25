"""Tests for `scripts/bench_graph_pattern_reuse.py` (issue #929, RESEARCH M8-D5).

The root suite is the coverage producer for `scripts/` (quality.yml runs
`--source=scripts`), so an untested research bench would red the diff-coverage
gate on the PR that adds it — same reason `test_bench_outcome_routing.py`
exists. Beyond satisfying the measurement, these tests pin the properties the
research note's disposition rests on:

* the mined corpus rides the real canonical spine — `Run` over a validated
  `GraphSnapshot` with `NodeRun`/`Attempt`/`AttemptResult`/`AcceptedNodeOutcome`
  records — and mining reads only successful Runs;
* induced motifs are real `GraphTemplate` objects in the real store, held at
  ``lifecycle="candidate"``: the execution door (`require_template`) refuses
  them, unversioned resolution ignores them, and `instantiate` produces a
  fresh `Graph` carrying exact-version `TemplateProvenance` — the issue's
  "reused Graphs remain versioned canonical Graph candidates";
* the anti-overfitting filter actually refuses a structure whose support comes
  from one task instance alone;
* the drift world actually drifts (latent validation tightening on one family,
  stated specs unchanged), stale reuse demonstrably fails where scratch
  succeeds on common random numbers, and the guard bounds the damage;
* the forced-transfer probe really serves goals from foreign-family motifs;
* everything is deterministic: same config, same payload, every run.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from maistro.graph.definitions import RUNTIME_STATE_FIELDS
from maistro.graph.templates import (
    GraphTemplateNotFound,
    InMemoryGraphTemplateStore,
    require_template,
)
from maistro.graph.types import AgentRole
from maistro.runs.model import RunStatus

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bench_graph_pattern_reuse.py"

spec = importlib.util.spec_from_file_location("bench_graph_pattern_reuse", SCRIPT)
assert spec and spec.loader
bench = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bench
spec.loader.exec_module(bench)


def _chain(kinds: set[str], spec: bench.GoalSpec | None = None) -> bench.Structure:
    return bench.chain_structure(kinds, spec or bench.GoalSpec("x", frozenset(kinds), ()))


def _corpus(runs: int = 120, seed: int = 0) -> list[Any]:
    return bench.generate_corpus(runs_count=runs, seed=seed)


def _mine(runs: list[Any], support: int = 3, instances: int = 2) -> dict[str, bench.Motif]:
    return bench.mine_motifs(runs, min_support=support, min_instances=instances)


def _induce(
    motifs: dict[str, bench.Motif],
) -> tuple[InMemoryGraphTemplateStore, list[Any]]:
    store = InMemoryGraphTemplateStore()
    templates = asyncio.run(bench.induce_templates(motifs, store, workspace_id="ws-test"))
    return store, templates


# ─── Structures ──────────────────────────────────────────────────────────────


class TestStructures:
    def test_signature_is_the_kind_level_isomorphism_class(self) -> None:
        # The signature abstracts node identities: two Graphs over the same
        # kind topology with different node ids reduce to one signature.
        structure = bench.Structure(
            frozenset({AgentRole.SCOUT, AgentRole.REVIEWER}),
            ((AgentRole.SCOUT, AgentRole.REVIEWER),),
        )
        graph_a = bench.build_graph(structure, workspace_id="ws", project_id="pj")
        renamed = {node.node_id: f"other-{node.node_type}" for node in graph_a.nodes}
        graph_b = graph_a.model_copy(
            update={
                "nodes": [
                    node.model_copy(update={"node_id": renamed[node.node_id]})
                    for node in graph_a.nodes
                ],
                "edges": [
                    edge.model_copy(
                        update={
                            "edge_id": "other-edge",
                            "from_node": renamed[edge.from_node],
                            "to_node": renamed[edge.to_node],
                        }
                    )
                    for edge in graph_a.edges
                ],
            }
        )
        assert bench.structure_of(graph_a) == structure
        assert bench.structure_of(graph_b) == structure
        # Different kind topology, different signature.
        different = bench.Structure(
            frozenset({AgentRole.SCOUT, AgentRole.PLANNER, AgentRole.REVIEWER}),
            ((AgentRole.SCOUT, AgentRole.PLANNER), (AgentRole.PLANNER, AgentRole.REVIEWER)),
        )
        assert different.signature != structure.signature
        # Edge direction is part of the shape.
        flipped = bench.Structure(
            frozenset({AgentRole.SCOUT, AgentRole.REVIEWER}),
            ((AgentRole.REVIEWER, AgentRole.SCOUT),),
        )
        assert flipped.signature != structure.signature

    def test_validated_requires_reviewer_downstream_of_every_producer(self) -> None:
        spec = bench.FAMILY_BY_NAME["data-extract"].base
        validated = bench.chain_structure({"transform.extract_field", AgentRole.REVIEWER}, spec)
        assert validated.validated()
        lean = bench.chain_structure({"transform.extract_field"}, spec)
        assert not lean.validated()
        # Reviewer upstream of the producer is not validation.
        backwards = bench.Structure(
            frozenset({AgentRole.REVIEWER, "transform.extract_field"}),
            ((AgentRole.REVIEWER, "transform.extract_field"),),
        )
        assert not backwards.validated()

    def test_orderings_satisfied_by_path_not_only_direct_edge(self) -> None:
        spec = bench.GoalSpec("f", frozenset({"a", "b", "c"}), (("a", "c"),))
        via_path = bench.Structure(frozenset({"a", "b", "c"}), (("a", "b"), ("b", "c")))
        assert via_path.orderings_satisfiable(spec)
        cyclic = bench.Structure(frozenset({"a", "c"}), (("a", "c"), ("c", "a")))
        assert not cyclic.orderings_satisfiable(spec)
        # A required kind that is missing fails outright.
        assert not bench.Structure(frozenset({"a"}), ()).satisfies(spec)

    def test_chain_structure_orders_reviewer_last(self) -> None:
        # Without a stated ordering, the reviewer still lands after production,
        # so enumerated candidates can be validated structures at all.
        structure = _chain({"transform.extract_field", AgentRole.REVIEWER})
        assert (structure.edges) == (("transform.extract_field", AgentRole.REVIEWER),)
        # Stated orderings are honored first; extra kinds join before the
        # reviewer so validation stays downstream.
        family = bench.FAMILY_BY_NAME["research-report"]
        with_planner = bench.chain_structure(
            {"scout", "planner", "llm.summarize", AgentRole.REVIEWER}, family.base
        )
        assert with_planner.validated()
        assert with_planner.reaches("planner", AgentRole.REVIEWER)

    def test_chain_structure_honors_stated_orderings(self) -> None:
        family = bench.FAMILY_BY_NAME["code-change"]
        structure = bench.chain_structure(
            {AgentRole.SCOUT, AgentRole.CODER, AgentRole.REVIEWER}, family.base
        )
        assert (AgentRole.SCOUT, AgentRole.CODER) in structure.edges
        assert (AgentRole.CODER, AgentRole.REVIEWER) in structure.edges


# ─── World truth ─────────────────────────────────────────────────────────────


class TestWorldTruth:
    def test_each_quality_term_moves_the_probability(self) -> None:
        spec = bench.FAMILY_BY_NAME["triage"].base
        lean = bench.chain_structure({AgentRole.SCOUT}, spec)
        covered = bench.chain_structure({AgentRole.SCOUT, AgentRole.REVIEWER}, spec)
        assert bench.true_success_prob(covered, spec) > bench.true_success_prob(lean, spec)
        # Validation adds the (small) pre-drift bonus on top of coverage.
        assert bench.true_success_prob(covered, spec) > bench.PROB_FLOOR

    def test_drift_hits_only_the_drift_family_only_when_unvalidated(self) -> None:
        family = bench.FAMILY_BY_NAME["data-extract"]
        spec = family.base
        lean = bench.chain_structure({"transform.extract_field"}, spec)
        validated = bench.chain_structure({"transform.extract_field", AgentRole.REVIEWER}, spec)
        p_lean_pre = bench.true_success_prob(lean, spec)
        p_lean_post = bench.true_success_prob(lean, spec, drifted=True)
        assert p_lean_pre > p_lean_post  # the stale-pattern trap
        assert bench.true_success_prob(validated, spec) == bench.true_success_prob(
            validated, spec, drifted=True
        )
        # No other family feels anything.
        other = bench.FAMILY_BY_NAME["triage"].base
        triage_lean = bench.chain_structure({AgentRole.SCOUT}, other)
        assert bench.true_success_prob(triage_lean, other) == bench.true_success_prob(
            triage_lean, other, drifted=True
        )

    def test_drift_leaves_stated_specs_untouched(self) -> None:
        # The point of the silent drift: the planner's inputs do not change.
        spec = bench.FAMILY_BY_NAME["data-extract"].base
        assert spec.required == frozenset({"transform.extract_field"})
        assert spec.orderings == ()

    def test_probability_is_clamped(self) -> None:
        spec = bench.GoalSpec("f", frozenset(), ())
        tiny = bench.Structure(frozenset(), ())
        assert bench.PROB_FLOOR <= bench.true_success_prob(tiny, spec) <= bench.PROB_CEIL


# ─── The canonical spine: recorded Runs ──────────────────────────────────────


class TestRecordedRuns:
    def test_successful_run_completes_every_node_through_an_accepted_outcome(
        self,
    ) -> None:
        structure = _chain({"a", "b"})
        run, node_runs = bench.record_run(
            structure,
            success=True,
            actor_principal_id="p1",
            provenance={"goal_family": "f", "goal_instance": 1},
        )
        assert run.status is RunStatus.COMPLETED
        assert run.error is None
        assert run.graph.content_hash
        # The snapshot materializes to a graph with the recorded structure.
        graph = run.graph.materialize()
        assert bench.structure_of(graph) == structure
        assert len(node_runs) == 2
        for node_run in node_runs:
            assert node_run.status is RunStatus.COMPLETED
            assert node_run.accepted_outcome is not None
            assert node_run.accepted_outcome.attempt_result.status.name == "COMPLETED"

    def test_failed_run_fails_exactly_one_node_run_without_accepting(self) -> None:
        structure = _chain({"a", "b", "c"})
        run, node_runs = bench.record_run(
            structure,
            success=False,
            actor_principal_id="p1",
            provenance={"goal_family": "f", "goal_instance": 1},
        )
        assert run.status is RunStatus.FAILED
        assert run.error
        failed = [nr for nr in node_runs if nr.status is RunStatus.FAILED]
        assert len(failed) == 1
        assert failed[0].accepted_outcome is None
        assert sum(1 for nr in node_runs if nr.accepted_outcome is not None) == len(node_runs) - 1

    def test_mining_reads_only_successful_runs(self) -> None:
        runs = _corpus(runs=40)
        statuses = {run.status for run in runs}
        assert RunStatus.FAILED in statuses  # the corpus carries failures
        motifs = _mine(runs)
        # Every inducted motif's support counts only COMPLETED runs.
        completed_by_sig: dict[str, int] = {}
        for run in runs:
            if run.status is RunStatus.COMPLETED:
                sig = bench.structure_of(run.graph.materialize()).signature
                completed_by_sig[sig] = completed_by_sig.get(sig, 0) + 1
        for motif in motifs.values():
            assert motif.support == completed_by_sig[motif.signature]
        # Every recorded run carries goal provenance for clustering.
        for run in runs:
            assert "goal_family" in run.provenance
            assert "goal_instance" in run.provenance


# ─── Mining ──────────────────────────────────────────────────────────────────


class TestMining:
    def test_support_and_distinct_instance_filters(self) -> None:
        runs = _corpus(runs=200)
        strict = _mine(runs, support=10**6)
        assert strict == {}
        loose = _mine(runs, support=1, instances=1)
        assert loose
        normal = _mine(runs, support=3, instances=2)
        assert set(normal) <= set(loose)

    def test_single_instance_structure_is_refused_as_an_overfit_trap(self) -> None:
        # One structure seen on many runs of ONE instance: high support, but it
        # says nothing about the next task instance.
        structure = _chain({"a", "b"})
        runs = [
            bench.record_run(
                structure,
                success=True,
                actor_principal_id="p",
                provenance={"goal_family": "f", "goal_instance": 7},
            )[0]
            for _ in range(5)
        ]
        assert _mine(runs, support=3, instances=2) == {}
        assert _mine(runs, support=3, instances=1).keys() == {structure.signature}

    def test_clusters_record_families(self) -> None:
        motifs = _mine(_corpus(runs=200))
        families = set()
        for motif in motifs.values():
            assert motif.families
            families |= motif.families
        assert families == {family.name for family in bench.FAMILIES}


# ─── Induction into canonical Graph candidates ───────────────────────────────


class TestInduction:
    def test_motifs_become_real_candidate_templates(self) -> None:
        motifs = _mine(_corpus(runs=200))
        store, templates = _induce(motifs)
        assert len(templates) == len(motifs)
        for template in templates:
            assert template.workspace_id == "ws-test"
            assert (
                asyncio.run(store.lifecycle_of(template.template_id, template.version))
                == "candidate"
            )

    def test_the_execution_door_refuses_candidates(self) -> None:
        _motifs = _mine(_corpus(runs=200))
        store, templates = _induce(_motifs)
        template = templates[0]
        # Unversioned resolution never hands back a candidate...
        assert asyncio.run(store.get(template.template_id)) is None
        # ...and the execution path refuses, both unversioned...
        with pytest.raises(GraphTemplateNotFound, match="no active version"):
            asyncio.run(require_template(store, template.template_id))
        # ...and at an exact pinned version.
        with pytest.raises(GraphTemplateNotFound, match="not active"):
            asyncio.run(require_template(store, template.template_id, version=template.version))
        # Inspection by exact version stays available — that is the point.
        assert asyncio.run(store.get(template.template_id, version=template.version)) is not None

    def test_instantiate_yields_a_fresh_graph_with_exact_provenance(self) -> None:
        motifs = _mine(_corpus(runs=200))
        _store, templates = _induce(motifs)
        assert templates
        for template in templates:
            graph = template.instantiate(project_id="pj-x")
            assert graph.source_template is not None
            assert graph.source_template.template_id == template.template_id
            assert graph.source_template.template_version == template.version
            assert graph.source_template.template_hash == template.content_hash
            # The instantiated Graph carries the mined structure — fresh node
            # identities, same kind topology (the name embeds the signature
            # prefix, which is unique at 40 chars for this corpus).
            mined = next(m for m in motifs.values() if m.signature[:40] in template.name)
            assert {node.node_type for node in graph.nodes} == mined.structure.kinds
            fresh = template.instantiate(project_id="pj-y")
            assert {n.node_id for n in fresh.nodes}.isdisjoint({n.node_id for n in graph.nodes})

    def test_templates_document_their_evidence_without_execution_identity(self) -> None:
        motifs = _mine(_corpus(runs=200))
        _store, templates = _induce(motifs)
        for template in templates:
            assert "support=" in template.description
            assert "distinct_instances=" in template.description
            induction = template.metadata["induction"]
            assert induction["support"] >= 3
            assert len(induction["distinct_instances"]) >= 2
            assert template.metadata[bench.SOURCES_KEY]
            # No execution identity may leak into reusable content.
            for forbidden in ("run_id", "node_run_id", "attempt_id", "actor_principal_id"):
                assert forbidden not in json.dumps(template.metadata)

    def test_runtime_state_in_metadata_is_refused_by_the_real_validator(self) -> None:
        # The guard the induction pipeline relies on: R12 refuses execution
        # identity in template content, so mining cannot quietly record a Run.
        assert "run_id" in RUNTIME_STATE_FIELDS
        structure = _chain({"a", "b"})
        graph = bench.build_graph(structure, workspace_id="ws", project_id="pj")
        graph = graph.model_copy(update={"metadata": {"run_id": "r-1"}})
        with pytest.raises(ValidationError, match="carries live execution state"):
            bench.GraphTemplate.from_graph(graph, name="stale")


# ─── Planners ────────────────────────────────────────────────────────────────


class TestScratchPlanner:
    def test_picks_a_validated_spec_satisfying_structure(self) -> None:
        spec = bench.FAMILY_BY_NAME["data-extract"].base
        plan = bench.ScratchPlanner().plan(spec)
        assert plan.structure.satisfies(spec)
        assert plan.structure.validated()

    def test_cost_is_deterministic_and_grows_with_the_search(self) -> None:
        spec = bench.FAMILY_BY_NAME["triage"].base
        plan = bench.ScratchPlanner().plan(spec)
        assert plan.tokens == (
            bench.SCRATCH_PROMPT_TOKENS
            + bench.SCRATCH_TOKENS_PER_CANDIDATE * plan.roundtrips
            + bench.SCRATCH_TOKENS_PER_NODE * len(plan.structure.kinds)
        )
        assert plan.roundtrips <= 60
        tight = bench.ScratchPlanner(budget=2).plan(spec)
        assert tight.roundtrips <= 2
        assert tight.tokens < plan.tokens

    def test_unsatisfiable_goal_still_yields_the_best_found(self) -> None:
        # A spec naming a kind outside the vocabulary cannot be covered; the
        # planner must not crash and must pay for its search.
        spec = bench.GoalSpec("f", frozenset({"nonexistent-kind"}), ())
        plan = bench.ScratchPlanner().plan(spec)
        assert plan.roundtrips > 0


class TestReusePlanner:
    def _planner(self, **kwargs: Any) -> bench.ReusePlanner:
        motifs = _mine(_corpus(runs=200))
        return bench.ReusePlanner(motifs=motifs, scratch=bench.ScratchPlanner(), **kwargs)

    def test_retrieves_best_motif_and_adapts_without_edits_on_cover(self) -> None:
        planner = self._planner()
        spec = bench.FAMILY_BY_NAME["data-extract"].base
        plan = planner.plan(spec)
        assert plan.reused and plan.motif is not None and not plan.fallback
        assert plan.structure.kinds == plan.motif.structure.kinds | spec.required
        assert plan.tokens == bench.RETRIEVE_TOKENS

    def test_adaptation_edits_when_the_motif_misses_a_required_kind(self) -> None:
        planner = self._planner()
        # A spec whose required set is wider than any single stored motif:
        # force one by asking for kinds the best motif does not carry.
        spec = bench.GoalSpec(
            "data-extract",
            frozenset({"transform.extract_field", "llm.summarize"}),
            (),
        )
        plan = planner.plan(spec)
        if plan.reused:  # a motif cleared the similarity bar
            assert plan.edits >= 1
            assert plan.structure.satisfies(spec)
            assert plan.tokens == bench.RETRIEVE_TOKENS + bench.ADAPT_TOKENS_PER_EDIT * plan.edits
        else:
            assert plan.fallback

    def test_fallback_when_nothing_retrieves(self) -> None:
        planner = self._planner(retrieve_threshold=1.1)
        plan = planner.plan(bench.FAMILY_BY_NAME["triage"].base)
        assert plan.fallback and not plan.reused
        assert plan.tokens > bench.SCRATCH_PROMPT_TOKENS

    def test_quarantined_motifs_are_skipped_and_stay_skipped(self) -> None:
        planner = self._planner()
        spec = bench.FAMILY_BY_NAME["data-extract"].base
        first = planner.plan(spec)
        assert first.motif is not None
        planner.quarantined.add(first.motif.signature)
        second = planner.plan(spec)
        if second.reused:
            assert second.motif.signature != first.motif.signature

    def test_guard_quarantines_once_after_the_window_fills(self) -> None:
        planner = self._planner()
        signature = "sig"
        fired = [planner.observe(signature, False) for _ in range(planner.guard_min)]
        # The quarantine fires exactly once, when the trailing mean crosses.
        assert fired.count(True) == 1
        assert fired[-1] is True
        assert fired[: planner.guard_min - 1] == [False] * (planner.guard_min - 1)
        # Further failures never re-fire.
        assert not planner.observe(signature, False)

    def test_guard_needs_the_minimum_window(self) -> None:
        planner = self._planner()
        # guard_min - 1 straight failures: not enough evidence, no quarantine.
        for _ in range(planner.guard_min - 1):
            assert not planner.observe("s", False)
        assert planner.quarantined == set()

    def test_forced_transfer_skips_own_family_motifs(self) -> None:
        planner = self._planner(exclude_own_family=True)
        spec = bench.FAMILY_BY_NAME["data-extract"].base
        plan = planner.plan(spec)
        if plan.reused and plan.motif is not None:
            assert spec.family not in plan.motif.families


# ─── The experiment ──────────────────────────────────────────────────────────

SMALL: dict[str, Any] = {
    "corpus_runs": 120,
    "episodes": 200,
    "drift_at": 60,
    "reindex_every": 20,
    "min_support": 3,
    "min_instances": 2,
    "budget": 60,
}


class TestExperiment:
    def test_run_seed_is_deterministic(self) -> None:
        first = bench.run_seed(0, **SMALL)
        second = bench.run_seed(0, **SMALL)
        assert first == second

    def test_payload_shape(self) -> None:
        result = bench.run_seed(0, **SMALL)
        assert set(result) >= {
            "seed",
            "drift_at",
            "episodes",
            "motifs_inducted_initial",
            "motifs_inducted_final",
            "arms",
            "inspectability",
            "checkpoints",
        }
        assert set(result["arms"]) == {
            "scratch",
            "reuse-naive",
            "reuse-guarded",
            "reuse-transfer",
        }
        for arm in result["arms"].values():
            assert arm["episodes"] == SMALL["episodes"]
        for report in result["inspectability"].values():
            assert report is not None
            assert report["all_candidates_not_active"] is True
            assert report["provenance_on_instantiate"] is True
            assert report["execution_door_closed"] is True
            assert report["documented_fraction"] == 1.0

    def test_reuse_is_dramatically_cheaper_than_scratch(self) -> None:
        arms = bench.run_seed(0, **SMALL)["arms"]
        assert arms["reuse-naive"]["mean_tokens"] < 0.2 * arms["scratch"]["mean_tokens"]
        assert arms["reuse-naive"]["mean_roundtrips"] < arms["scratch"]["mean_roundtrips"]

    def test_drift_creates_stale_failures_and_the_guard_bounds_them(self) -> None:
        # Across every seed: naive reuse bleeds stale-attributable failures
        # after the drift; the guard's quarantine bounds the damage; scratch
        # has none by construction.
        for seed in range(5):
            arms = bench.run_seed(seed, **SMALL)["arms"]
            assert arms["scratch"]["stale_attributable_failures"] == 0
            assert arms["reuse-naive"]["stale_attributable_failures"] > 0
            assert (
                arms["reuse-guarded"]["stale_attributable_failures"]
                < arms["reuse-naive"]["stale_attributable_failures"]
            )
            assert arms["reuse-guarded"]["guard_quarantines"] >= 1

    def test_transfer_probe_serves_goals_from_foreign_families(self) -> None:
        arms = bench.run_seed(0, **SMALL)["arms"]
        transfer = arms["reuse-transfer"]
        assert transfer["cross_family_hits"] > 0
        assert transfer["scratch_fallbacks"] > 0
        # Foreign motifs that clear the bar still succeed at a healthy rate —
        # structure, not family identity, is what carries a Graph.
        assert transfer["cross_family_success_rate"] is not None
        assert transfer["cross_family_success_rate"] > 0.5

    def test_naive_reuse_loses_success_to_stale_patterns(self) -> None:
        # The issue's hypothesis has a real downside arm: on every seed here,
        # unguarded reuse is measurably worse than planning from scratch even
        # though it is ~13x cheaper.
        for seed in range(5):
            arms = bench.run_seed(seed, **SMALL)["arms"]
            assert arms["reuse-naive"]["success_rate"] < arms["scratch"]["success_rate"]

    def test_checkpoints_mark_the_drift_boundary(self) -> None:
        result = bench.run_seed(0, **SMALL)
        drifted = {cp["episode"]: cp for cp in result["checkpoints"]}
        assert drifted[SMALL["drift_at"] - 1]["drifted"] is False
        assert drifted[SMALL["drift_at"]]["drifted"] is True

    def test_reindex_grows_the_mined_library(self) -> None:
        result = bench.run_seed(0, **SMALL)
        assert result["motifs_inducted_final"]["reuse-naive"] >= result["motifs_inducted_initial"]


# ─── Aggregation, verdict, CLI ───────────────────────────────────────────────


class TestAggregationAndCLI:
    @staticmethod
    def _arm_row(success_rate: float, tokens: float) -> dict[str, Any]:
        return {
            "success_rate": success_rate,
            "mean_tokens": tokens,
            "mean_roundtrips": 1.0,
            "mean_adaptation_edits": 0.0,
            "stale_attributable_failures": 0,
            "guard_quarantines": 0,
            "cross_family_hits": 0,
        }

    def test_aggregate_computes_mean_and_std(self) -> None:
        per_seed = [
            {"arms": {"scratch": self._arm_row(0.8, 100.0)}},
            {"arms": {"scratch": self._arm_row(0.6, 200.0)}},
        ]
        summary = bench.aggregate(per_seed)
        # Sample std (n-1 denominator), rounded to 4 places.
        assert summary["scratch"]["success_rate"] == {"mean": 0.7, "std": 0.1414}
        assert summary["scratch"]["mean_tokens"]["mean"] == 150.0

    def test_aggregate_handles_a_single_seed(self) -> None:
        summary = bench.aggregate([{"arms": {"scratch": self._arm_row(0.5, 10.0)}}])
        assert summary["scratch"]["success_rate"] == {"mean": 0.5, "std": 0.0}

    def _summary(self, **overrides: float) -> dict[str, Any]:
        base = {
            "reuse-naive": {
                "mean_tokens": {"mean": 120.0},
                "success_rate": {"mean": 0.69},
                "stale_attributable_failures": {"mean": 18.0},
            },
            "reuse-guarded": {
                "mean_tokens": {"mean": 180.0},
                "success_rate": {"mean": 0.72},
                "stale_attributable_failures": {"mean": 7.0},
            },
            "scratch": {
                "mean_tokens": {"mean": 1580.0},
                "success_rate": {"mean": 0.74},
                "stale_attributable_failures": {"mean": 0.0},
            },
        }
        for arm, fields in overrides.items():
            base[arm].update(fields)
        return base

    def test_verdict_incubates_when_cost_win_and_guard_bounds(self) -> None:
        assert bench.verdict(self._summary()) == "INCUBATE"

    def test_verdict_watches_when_the_guard_fails(self) -> None:
        watched = self._summary(
            **{
                "reuse-guarded": {
                    "success_rate": {"mean": 0.60},
                    "stale_attributable_failures": {"mean": 20.0},
                }
            }
        )
        assert bench.verdict(watched) == "WATCH"
        # No cost win is equally disqualifying.
        expensive = self._summary(**{"reuse-guarded": {"mean_tokens": {"mean": 9000.0}}})
        assert bench.verdict(expensive) == "WATCH"

    def test_main_writes_the_payload_and_exits_cleanly(self, tmp_path: Path) -> None:
        out = tmp_path / "results.json"
        rc = bench.main(
            [
                "--corpus-runs",
                "40",
                "--episodes",
                "20",
                "--seeds",
                "1",
                "--drift-at",
                "10",
                "--reindex-every",
                "10",
                "--output",
                str(out),
            ]
        )
        assert rc == 0
        payload = json.loads(out.read_text())
        assert payload["issue"] == 929
        assert payload["verdict"] in ("INCUBATE", "WATCH")
        assert payload["config"]["episodes"] == 20
        assert set(payload["summary"]) == {
            "scratch",
            "reuse-naive",
            "reuse-guarded",
            "reuse-transfer",
        }
        # The cost model is published with the numbers, not hidden.
        assert payload["cost_model"]["retrieve_tokens"] == bench.RETRIEVE_TOKENS

    def test_parser_defaults_match_the_research_configuration(self) -> None:
        args = bench.build_parser().parse_args([])
        assert (args.corpus_runs, args.episodes, args.seeds) == (600, 400, 5)
        assert (args.drift_at, args.reindex_every) == (200, 50)
        assert (args.min_support, args.min_instances, args.budget) == (3, 2, 60)
