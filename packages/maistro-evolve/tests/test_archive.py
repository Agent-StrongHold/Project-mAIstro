"""M4-A6: candidate lineage/archive + historical-retention evaluation.

Covers the four seams the issue names:

- candidate records identify parent(s), mutation/operator, source objective,
  prompt/template version, and evaluation Runs (stamped by every producer);
- the archive stores immutable snapshots, survives retirement, and supports
  branching from non-champion candidates;
- the prior proven scenario set is replayed/sampled under a declared
  retention policy;
- historical regressions block promotion unless an explicit governance
  decision changes the objective.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from maistro_evolve.archive import (
    CandidateArchive,
    GovernanceDecision,
    HistoricalRegressionBlocked,
    OperatorKind,
    ProvenanceIncomplete,
    RetentionGate,
    RetentionPolicy,
    apply_objective,
    complete_provenance,
    evaluation_run_ids,
    promote_with_retention,
    prompt_version,
    proven_scenario_scores,
    resolve_lineage,
    stamp_provenance,
)
from maistro_evolve.audit import GenomeAuditTrail
from maistro_evolve.cycle import EvolutionConfig, EvolutionCycle
from maistro_evolve.harness import EvalHarness
from maistro_evolve.population import PopulationStore
from maistro_evolve.types import (
    DAGTopology,
    EvalResult,
    EvalWeights,
    NodeGenome,
    PipelineGenome,
)


def _genome(genome_id: str, **overrides: object) -> PipelineGenome:
    fields: dict[str, object] = {
        "id": genome_id,
        "name": genome_id,
        "topology": DAGTopology(
            nodes=[
                NodeGenome(
                    id="q1",
                    role="queen",
                    strategy="react",
                    model="gpt-4",
                    temperature=0.3,
                    max_tokens=4096,
                    system_prompt="test",
                    max_tool_rounds=5,
                )
            ],
            edges=[],
            entry_node="q1",
            max_cycles=3,
            beam_width=1,
            use_scout=False,
        ),
        "eval_weights": EvalWeights(),
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    fields.update(overrides)
    return PipelineGenome(**fields)  # type: ignore[arg-type]


def _stamped(
    genome_id: str,
    *,
    objective: str = "obj",
    scores: dict[str, float] | None = None,
    parents: list[str] | None = None,
) -> PipelineGenome:
    genome = _genome(genome_id)
    genome.eval_scores = scores or {}
    if parents:
        genome.parent_a_id = parents[0]
    return stamp_provenance(
        genome, parents=parents or [], operator=OperatorKind.SEED, objective=objective
    )


class _AuditSink:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def log_delegation(self, peer_name: str, agent_id: str, detail: str) -> None:
        self.calls.append((peer_name, agent_id, detail))


def _audit() -> GenomeAuditTrail:
    return GenomeAuditTrail(_AuditSink())  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# candidate records: provenance stamped by every producer
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mutator", "operator"),
    [
        ("topology", OperatorKind.TOPOLOGY_MUTATION),
        ("node", OperatorKind.NODE_MUTATION),
        ("prompt", OperatorKind.PROMPT_MUTATION),
        ("weights", OperatorKind.EVAL_WEIGHTS_MUTATION),
        ("fixer", OperatorKind.FIXER_MUTATION),
    ],
)
def test_mutation_operators_stamp_provenance(mutator: str, operator: OperatorKind) -> None:
    from maistro_evolve.mutate import (
        mutate_eval_weights,
        mutate_fixer_genome,
        mutate_node,
        mutate_prompt,
        mutate_topology,
    )

    parent = _stamped("parent", scores={"proxy_ifeval": 0.5})
    fns = {
        "topology": lambda g: mutate_topology(g, 1.0),
        "node": lambda g: mutate_node(g, 1.0),
        "prompt": lambda g: mutate_prompt(g, 1.0),
        "weights": lambda g: mutate_eval_weights(g, 1.0),
        "fixer": lambda g: mutate_fixer_genome(g, 1.0),
    }
    child = fns[mutator](parent)
    assert child.provenance is not None
    assert child.provenance.operator == operator.value
    assert child.provenance.parents == [parent.id]
    assert child.parent_a_id == parent.id
    # objective inherits from the parent's record; version is content-derived
    assert child.provenance.objective == "obj"
    assert child.provenance.prompt_version == prompt_version(child)
    assert child.provenance.prompt_version


def test_mutate_all_lineage_points_at_stored_parent_not_intermediates() -> None:
    from maistro_evolve.mutate import mutate_all

    parent = _stamped("parent")
    child = mutate_all(parent, 1.0)
    # The operator chain builds and discards intermediate children; the
    # returned child must name the parent that actually exists in the store.
    assert child.parent_a_id == parent.id
    assert child.provenance is not None
    assert child.provenance.operator == OperatorKind.ALL_MUTATION.value
    assert child.provenance.parents == [parent.id]


def test_crossover_records_both_parents() -> None:
    from maistro_evolve.crossover import crossover

    a = _stamped("a", objective="shared-obj")
    b = _stamped("b", objective="other-obj")
    child = crossover(a, b)
    assert child.provenance is not None
    assert child.provenance.operator == OperatorKind.CROSSOVER.value
    assert child.provenance.parents == [a.id, b.id]
    assert child.parent_a_id == a.id
    assert child.parent_b_id == b.id
    # objective follows the first (primary) parent
    assert child.provenance.objective == "shared-obj"


def test_crossover_and_mutate_keeps_both_parents() -> None:
    from maistro_evolve.crossover import crossover_and_mutate

    a = _stamped("a")
    b = _stamped("b")
    child = crossover_and_mutate(a, b, 1.0)
    # mutate_all re-parents to its immediate input; the bred child must still
    # record BOTH crossover parents.
    assert child.parent_a_id == a.id
    assert child.parent_b_id == b.id
    assert child.provenance is not None
    assert child.provenance.parents == [a.id, b.id]
    assert child.provenance.operator == OperatorKind.CROSSOVER.value
    assert child.provenance.detail == "crossover+mutate_all"


def test_challengers_stamp_operator_provenance() -> None:
    from maistro_evolve.fixer_genome import FixerGenome
    from maistro_evolve.hyper_mutator import spawn_fixer_challenger
    from maistro_evolve.reflect import spawn_challenger

    parent = _stamped("parent")
    reflect_child = spawn_challenger(parent, "q1", "new prompt text")
    assert reflect_child.provenance is not None
    assert reflect_child.provenance.operator == OperatorKind.REFLECTION.value
    assert reflect_child.provenance.parents == [parent.id]
    assert reflect_child.provenance.objective == "obj"

    hyper_child = spawn_fixer_challenger(parent, FixerGenome())
    assert hyper_child.provenance is not None
    assert hyper_child.provenance.operator == OperatorKind.HYPER_MUTATION.value
    assert hyper_child.provenance.parents == [parent.id]


def test_seeds_are_stamped_candidate_records() -> None:
    from maistro_evolve.diversity import emergency_spawn

    seeds = emergency_spawn([], 3)
    for seed in seeds:
        assert seed.provenance is not None
        assert seed.provenance.operator == OperatorKind.SEED.value
        assert seed.provenance.parents == []


def test_prompt_version_deterministic_and_content_sensitive() -> None:
    g1 = _genome("g1")
    g2 = _genome("g2")
    assert prompt_version(g1) == prompt_version(g2)
    changed = _genome("g3")
    changed.topology.nodes[0].system_prompt = "a different prompt"
    assert prompt_version(changed) != prompt_version(g1)


def test_apply_objective_overrides_record() -> None:
    genome = _stamped("g", objective="old")
    apply_objective(genome, "new")
    assert genome.provenance is not None
    assert genome.provenance.objective == "new"
    assert genome.provenance.operator == OperatorKind.SEED.value
    # empty objective is a no-op, not a wipe
    apply_objective(genome, "")
    assert genome.provenance is not None
    assert genome.provenance.objective == "new"


def test_genomes_without_provenance_still_validate() -> None:
    genome = _genome("legacy")
    assert genome.provenance is None
    with pytest.raises(ProvenanceIncomplete):
        complete_provenance(genome)


def test_evaluation_run_ids_fold_canonical_refs() -> None:
    genome = _stamped("g")
    genome.provenance.evaluation_run_ids = ["run-1"]  # type: ignore[union-attr]
    genome.harness_params["evaluation_runs"] = [
        {"run_id": "run-1", "node_run_id": "nr1", "attempt_id": "at1"},
        {"run_id": "run-2", "node_run_id": "nr2", "attempt_id": "at2"},
    ]
    assert evaluation_run_ids(genome) == ["run-1", "run-2"]


# --------------------------------------------------------------------------
# the archive: immutable snapshots, retirement, branching, lineage
# --------------------------------------------------------------------------


def test_archive_snapshots_are_immutable() -> None:
    archive = CandidateArchive()
    genome = _stamped("g", scores={"proxy_ifeval": 0.9})
    archive.record(genome, event="created")
    genome.eval_scores["proxy_ifeval"] = 0.0
    genome.name = "mutated-in-place"
    snapshot = archive.get("g")
    assert snapshot is not None
    assert snapshot.eval_scores["proxy_ifeval"] == 0.9
    assert snapshot.name == "g"


def test_cull_bottom_archives_retired_candidates() -> None:
    population = PopulationStore()
    archive = CandidateArchive()
    weak = _stamped("weak", scores={"proxy_ifeval": 0.1})
    strong = _stamped("strong", scores={"proxy_ifeval": 0.9})
    weak.fitness_score = 0.1
    strong.fitness_score = 0.9
    population.add(weak)
    population.add(strong)

    removed = population.cull_bottom(0.5, archive=archive)
    assert removed == 1
    assert population.get("weak") is None
    # retired, yet inspectable
    assert [g.id for g in archive.list_retired()] == ["weak"]
    snapshot = archive.get("weak")
    assert snapshot is not None
    assert snapshot.eval_scores["proxy_ifeval"] == 0.1


def test_cull_bottom_without_archive_unchanged() -> None:
    population = PopulationStore()
    weak = _stamped("weak", scores={"proxy_ifeval": 0.1})
    weak.fitness_score = 0.1
    population.add(weak)
    assert population.cull_bottom(0.5) == 1
    assert population.get("weak") is None


def test_resolve_lineage_survives_retirement() -> None:
    population = PopulationStore()
    archive = CandidateArchive()
    grandparent = _stamped("gp")
    parent = _stamped("p", parents=["gp"])
    child = _stamped("c", parents=["p"])
    for g in (grandparent, parent, child):
        g.fitness_score = 0.5
        population.add(g)
        archive.record(g, event="created")
    population.cull_bottom(0.34, archive=archive)  # retires the weakest
    assert population.get("gp") is None or population.get("c") is not None

    chain = resolve_lineage(population, archive, "c")
    assert [g.id for g in chain] == ["c", "p", "gp"]


def test_archive_branch_from_non_champion() -> None:
    archive = CandidateArchive()
    champion = _stamped("champ", scores={"proxy_ifeval": 0.95})
    stepping_stone = _stamped("stone", scores={"proxy_ifeval": 0.2}, parents=["champ"])
    archive.record(champion, event="created")
    archive.record(stepping_stone, event="retired")

    child = archive.branch("stone")
    assert child.id != stepping_stone.id
    assert child.parent_a_id == stepping_stone.id
    assert child.provenance is not None
    assert child.provenance.operator == OperatorKind.ARCHIVE_BRANCH.value
    assert child.provenance.parents == [stepping_stone.id]
    assert child.generation == stepping_stone.generation + 1
    assert child.eval_scores == {}
    assert child.fitness_score is None
    # the branch event itself is recorded
    assert archive.latest_event(child.id) == "branched"


def test_archive_branch_from_unknown_candidate_raises() -> None:
    archive = CandidateArchive()
    with pytest.raises(KeyError):
        archive.branch("nope")


def test_archive_sqlite_persistence(tmp_path) -> None:
    db = tmp_path / "archive.db"
    archive = CandidateArchive(db_path=db)
    archive.record(_stamped("g"), event="created")

    reopened = CandidateArchive(db_path=db)
    assert reopened.get("g") is not None
    assert reopened.latest_event("g") == "created"


# --------------------------------------------------------------------------
# retention: declared policy, replay/sample, regression blocking
# --------------------------------------------------------------------------


def test_replay_policy_selects_every_proven_scenario() -> None:
    gate = RetentionGate(RetentionPolicy(mode="replay"))
    scenarios = gate.select_scenarios({"b": 0.5, "a": 0.9, "c": 0.1})
    assert scenarios == ["a", "b", "c"]


def test_sample_policy_is_deterministic_and_honors_declared_size() -> None:
    proven = {f"s{i}": 0.5 for i in range(10)}
    gate_a = RetentionGate(RetentionPolicy(mode="sample", sample_size=4))
    gate_b = RetentionGate(RetentionPolicy(mode="sample", sample_size=4))
    picked_a = gate_a.select_scenarios(proven)
    assert picked_a == gate_b.select_scenarios(proven)
    assert len(picked_a) == 4
    assert set(picked_a) <= set(proven)
    # a declared sample at least as large as the set degenerates to replay
    gate_big = RetentionGate(RetentionPolicy(mode="sample", sample_size=10))
    assert gate_big.select_scenarios(proven) == sorted(proven)


def test_retention_report_flags_regression_and_coverage() -> None:
    gate = RetentionGate(RetentionPolicy())
    candidate = _stamped("c", scores={"ifeval": 0.5})
    report = gate.evaluate(candidate, {"ifeval": 0.9, "bfcl": 0.8})
    assert report.blocked
    assert report.regressed == ["ifeval"]
    assert report.not_evaluated == ["bfcl"]


def test_retention_tolerance_allows_declared_slack() -> None:
    gate = RetentionGate(RetentionPolicy(regression_tolerance=0.2))
    candidate = _stamped("c", scores={"ifeval": 0.75})
    report = gate.evaluate(candidate, {"ifeval": 0.9})
    assert not report.blocked
    beyond = _stamped("c2", scores={"ifeval": 0.69})
    assert gate.evaluate(beyond, {"ifeval": 0.9}).blocked


def test_proven_scenario_scores_union_best_under_objective() -> None:
    population = PopulationStore()
    archive = CandidateArchive()
    champ = _stamped("champ", objective="obj", scores={"ifeval": 0.8})
    stone = _stamped("stone", objective="obj", scores={"ifeval": 0.9})
    other = _stamped("other", objective="different", scores={"ifeval": 1.0, "bfcl": 0.4})
    for g in (champ, other):
        population.add(g)
    archive.record(stone, event="retired")

    proven = proven_scenario_scores(population, archive, objective="obj")
    # best-ever across live AND archived candidates under the SAME objective;
    # the other objective's evidence is not this objective's baseline.
    assert proven == {"ifeval": 0.9}


def _retention_env() -> tuple[PopulationStore, CandidateArchive]:
    population = PopulationStore()
    archive = CandidateArchive()
    # historical evidence: a live champion and a retired stepping stone
    champ = _stamped("champ", objective="obj", scores={"ifeval": 0.8, "bfcl": 0.7})
    champ.fitness_score = 0.8
    champ.approved_for_promotion = False
    population.add(champ)
    stone = _stamped("stone", objective="obj", scores={"ifeval": 0.95}, parents=["champ"])
    archive.record(stone, event="retired")
    return population, archive


def _challenger(genome_id: str, scores: dict[str, float]) -> PipelineGenome:
    challenger = _stamped(genome_id, objective="obj", parents=["champ"], scores=scores)
    challenger.fitness_score = max(scores.values())
    challenger.approved_for_promotion = True
    return challenger


async def test_promotion_blocked_by_historical_regression() -> None:
    population, archive = _retention_env()
    challenger = _challenger("new", scores={"ifeval": 0.85, "bfcl": 0.75})
    population.add(challenger)
    archive.record(challenger, event="created")

    audit = _audit()
    with pytest.raises(HistoricalRegressionBlocked) as excinfo:
        await promote_with_retention(
            population, archive, "new", audit, RetentionGate(RetentionPolicy())
        )
    report = excinfo.value.report
    # 0.85 regresses against the stepping stone's proven 0.95
    assert report.regressed == ["ifeval"]
    # nothing changed: no audit events, still no active genome
    assert audit.entries == []
    assert population.get_active() is None
    # the refused attempt is inspectable evidence, not a silent drop; the
    # candidate itself is NOT retired (it stays live in the population)
    assert archive.latest_event("new") == "blocked"
    assert population.get("new") is not None


async def test_promotion_blocked_when_proven_set_not_replayed() -> None:
    population, archive = _retention_env()
    challenger = _challenger("new", scores={"ifeval": 0.99})  # bfcl never faced
    population.add(challenger)
    with pytest.raises(HistoricalRegressionBlocked) as excinfo:
        await promote_with_retention(
            population, archive, "new", _audit(), RetentionGate(RetentionPolicy())
        )
    assert excinfo.value.report.not_evaluated == ["bfcl"]


async def test_promotion_succeeds_when_retention_holds() -> None:
    population, archive = _retention_env()
    challenger = _challenger("new", scores={"ifeval": 0.99, "bfcl": 0.8})
    population.add(challenger)
    promoted = await promote_with_retention(
        population, archive, "new", _audit(), RetentionGate(RetentionPolicy())
    )
    assert promoted.id == "new"
    assert population.get_active() is not None
    assert population.get_active().id == "new"  # type: ignore[union-attr]
    assert archive.latest_event("new") == "promoted"


async def test_governance_override_requires_objective_change() -> None:
    population, archive = _retention_env()

    # a decision that re-asserts the same objective overrides nothing
    challenger = _challenger("same-obj", scores={"ifeval": 0.5, "bfcl": 0.5})
    population.add(challenger)
    with pytest.raises(HistoricalRegressionBlocked):
        await promote_with_retention(
            population,
            archive,
            "same-obj",
            _audit(),
            RetentionGate(RetentionPolicy()),
            governance=GovernanceDecision(
                rationale="we like it", decided_by="gov", new_objective="obj"
            ),
        )

    # an explicit decision that CHANGES the objective unlocks the promotion
    challenger2 = _challenger("new-obj", scores={"ifeval": 0.5, "bfcl": 0.5})
    population.add(challenger2)
    promoted = await promote_with_retention(
        population,
        archive,
        "new-obj",
        _audit(),
        RetentionGate(RetentionPolicy()),
        governance=GovernanceDecision(
            rationale="pivot: objective changes",
            decided_by="gov",
            new_objective="obj-v2",
        ),
    )
    assert promoted.id == "new-obj"
    assert population.get_active() is not None
    assert population.get_active().id == "new-obj"  # type: ignore[union-attr]


async def test_promotion_requires_complete_provenance() -> None:
    population, archive = _retention_env()
    challenger = _challenger("bare", scores={"ifeval": 0.99, "bfcl": 0.99})
    challenger.provenance = None
    population.add(challenger)
    with pytest.raises(ProvenanceIncomplete):
        await promote_with_retention(
            population, archive, "bare", _audit(), RetentionGate(RetentionPolicy())
        )


async def test_first_candidate_under_objective_has_nothing_to_defend() -> None:
    population = PopulationStore()
    archive = CandidateArchive()
    first = _challenger("first", scores={"ifeval": 0.1})
    population.add(first)
    # no archived/other candidates: no prior proven set, promotion proceeds
    promoted = await promote_with_retention(
        population, archive, "first", _audit(), RetentionGate(RetentionPolicy())
    )
    assert promoted.id == "first"


async def test_unknown_candidate_rejected() -> None:
    with pytest.raises(ValueError):
        await promote_with_retention(
            PopulationStore(),
            CandidateArchive(),
            "ghost",
            _audit(),
            RetentionGate(RetentionPolicy()),
        )


# --------------------------------------------------------------------------
# cycle integration: the production path archives lineage automatically
# --------------------------------------------------------------------------


def _fake_harness(score: float = 0.5) -> EvalHarness:
    harness = EvalHarness()
    harness._benchmarks.clear()

    async def fake_runner(
        genome: PipelineGenome, llm_call: object, _score: float = score
    ) -> EvalResult:
        return EvalResult(
            benchmark="b1",
            score=_score,
            cost_usd=0.0,
            duration_seconds=0.0,
            samples_evaluated=1,
            metadata={"fidelity": "proxy"},
        )

    harness.register_benchmark("b1", fake_runner)
    return harness


async def test_run_cycle_archives_retired_candidates_and_created_children() -> None:
    population = PopulationStore()
    archive = CandidateArchive()
    weak = _stamped("weak", scores={"b1": 0.1})
    strong = _stamped("strong", scores={"b1": 0.9})
    weak.fitness_score = 0.1
    strong.fitness_score = 0.9
    population.add(weak)
    population.add(strong)

    cycle = EvolutionCycle(
        harness=_fake_harness(),
        tournament=None,
        archive=archive,
    )
    config = EvolutionConfig(
        target_benchmarks=["b1"],
        cull_pct=0.5,
        population_size=4,
        self_improve=False,
        goal="test-objective",
    )
    evolved = await cycle.run_cycle(population, llm_call=None, config=config)
    # cull archived the retired candidate; it stays inspectable
    assert "weak" not in {g.id for g in evolved.list_all()}
    assert "weak" in {g.id for g in archive.list_retired()}
    # children bred this cycle were snapshotted as created candidates
    created = [
        e.candidate.id
        for e in archive.entries_for(archive.candidates()[-1])
        if e.event == "created"
    ]
    assert created  # at least one snapshot exists
    for genome in evolved.list_all():
        if genome.id in {"weak", "strong"}:
            continue
        entry = archive.get(genome.id)
        assert entry is not None, f"child {genome.id} never archived"
        # the run's declared source objective is on the candidate record
        assert genome.provenance is not None
        assert genome.provenance.objective == "test-objective"


async def test_run_cycle_without_archive_unchanged() -> None:
    population = PopulationStore()
    weak = _stamped("weak", scores={"b1": 0.1})
    weak.fitness_score = 0.1
    population.add(weak)
    cycle = EvolutionCycle(harness=_fake_harness())
    config = EvolutionConfig(target_benchmarks=["b1"], cull_pct=0.5, population_size=2)
    evolved = await cycle.run_cycle(population, llm_call=None, config=config)
    assert "weak" not in {g.id for g in evolved.list_all()}
