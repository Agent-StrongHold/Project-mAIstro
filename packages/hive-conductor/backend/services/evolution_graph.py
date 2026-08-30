"""Canonical Graph/Run execution adapter for the Evolve product path (#51).

Evolve keeps ownership of population, genome, fitness, lineage and tournament
state. This module maps one evolution cycle to one canonical Run, each genome
evaluation to a NodeRun, each actual tournament pair to a NodeRun, and cycle
finalization to a NodeRun. The public durable Graph entry point supplies the
physical Attempt layer beneath every NodeRun.

The standalone ``EvolutionCycle.run_cycle`` API remains a library surface. The
Conductor no longer calls it directly because that would make the Evolve loop a
second execution lifecycle alongside Run/NodeRun/Attempt.
"""

from __future__ import annotations

import logging
import random
from itertools import pairwise
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from maistro.graph.definitions import Edge, Graph, Node
from maistro.graph.durable_runs import DurableRunRecord, run_durable_graph
from maistro.graph.nodes.base import BaseNode, NodeContext
from maistro.runs.model import RunStatus

logger = logging.getLogger(__name__)

_ADMISSION_SOURCE = "evolve"
_EVALUATE_KIND = "evolve.evaluate_genome"
_PAIR_KIND = "evolve.plan_tournament_pairs"
_BATTLE_KIND = "evolve.tournament_pair"
_FINALIZE_KIND = "evolve.finalize_cycle"


class _EvaluateInput(BaseModel):
    genome_id: str


class _EvaluateOutput(BaseModel):
    genome_id: str
    benchmarks: dict[str, float] = Field(default_factory=dict)
    evaluation_run_id: str
    evaluation_node_run_id: str
    evaluation_attempt_id: str


class _IgnoreInput(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _PairPlanOutput(BaseModel):
    pair_count: int
    has_battles: bool


class _BattleOutput(BaseModel):
    genome_a_id: str
    genome_b_id: str
    benchmarks: list[str] = Field(default_factory=list)
    has_more: bool = False


class _FinalizeOutput(BaseModel):
    population_size: int
    new_genome_ids: list[str] = Field(default_factory=list)


def _append_execution_ref(genome: Any, ctx: NodeContext) -> None:
    """Attach canonical evaluation evidence to the domain object that consumed it."""
    refs = genome.harness_params.setdefault("evaluation_runs", [])
    ref = {
        "run_id": ctx.run_id,
        "node_run_id": ctx.node_run_id,
        "attempt_id": ctx.attempt_id,
    }
    if not any(item.get("attempt_id") == ctx.attempt_id for item in refs if isinstance(item, dict)):
        refs.append(ref)


async def _evaluate_one(
    cycle: Any,
    population: Any,
    config: Any,
    llm_call: Any,
    genome_id: str,
    ctx: NodeContext,
) -> _EvaluateOutput:
    """Run the existing Evolve evaluation semantics for exactly one genome."""
    from datetime import UTC, datetime

    genome = population.get(genome_id)
    if genome is None:
        raise ValueError(f"evolution genome {genome_id!r} disappeared before evaluation")

    results = await cycle.harness.evaluate_genome(genome, config.target_benchmarks, llm_call)
    for result in results:
        cycle._fold_score(
            genome,
            result.benchmark,
            result.score,
            bool(result.metadata.get("stub")),
            config.eval_ema_alpha,
        )
        genome.harness_params["total_cost_usd"] = (
            genome.harness_params.get("total_cost_usd", 0.0) + result.cost_usd
        )
        genome.harness_params["avg_latency_seconds"] = (
            genome.harness_params.get("avg_latency_seconds", 0.0) + result.duration_seconds
        ) / max(len(genome.eval_scores), 1)

    _append_execution_ref(genome, ctx)
    genome.updated_at = datetime.now(UTC).isoformat()
    population.add(genome)
    return _EvaluateOutput(
        genome_id=genome.id,
        benchmarks=dict(genome.eval_scores),
        evaluation_run_id=ctx.run_id,
        evaluation_node_run_id=ctx.node_run_id,
        evaluation_attempt_id=ctx.attempt_id,
    )


class _EvaluateNode(BaseNode[_EvaluateInput, _EvaluateOutput]):
    kind: ClassVar[str] = _EVALUATE_KIND
    input_schema: ClassVar[type[BaseModel]] = _EvaluateInput
    output_schema: ClassVar[type[BaseModel]] = _EvaluateOutput
    display_name: ClassVar[str] = "Evaluate Evolve genome"
    description: ClassVar[str] = "Evaluate one genome and record canonical execution provenance."

    def __init__(self, *, cycle: Any, population: Any, config: Any, llm_call: Any) -> None:
        self._cycle = cycle
        self._population = population
        self._config = config
        self._llm_call = llm_call

    async def _execute(self, inputs: _EvaluateInput, ctx: NodeContext) -> _EvaluateOutput:
        return await _evaluate_one(
            self._cycle,
            self._population,
            self._config,
            self._llm_call,
            inputs.genome_id,
            ctx,
        )


class _BattlePlan:
    """Choose tournament pairs only after evaluation NodeRuns have settled."""

    def __init__(self, *, cycle: Any, population: Any) -> None:
        self._cycle = cycle
        self._population = population
        self._pairs: list[tuple[str, str]] | None = None
        self._cursor = 0

    def prepare(self) -> _PairPlanOutput:
        if self._pairs is None:
            scored = [genome for genome in self._population.list_all() if genome.eval_scores]
            shuffled = list(scored)
            random.shuffle(shuffled)
            self._pairs = [
                (shuffled[index].id, shuffled[index + 1].id)
                for index in range(0, len(shuffled) - 1, 2)
            ]
        return _PairPlanOutput(pair_count=len(self._pairs), has_battles=bool(self._pairs))

    def next(self) -> _BattleOutput:
        if self._pairs is None:
            raise RuntimeError("tournament pair plan was not prepared")
        if self._cursor >= len(self._pairs):
            raise RuntimeError("tournament graph requested a battle after the pair plan was exhausted")

        genome_a_id, genome_b_id = self._pairs[self._cursor]
        self._cursor += 1
        genome_a = self._population.get(genome_a_id)
        genome_b = self._population.get(genome_b_id)
        if genome_a is None or genome_b is None:
            raise ValueError("a tournament genome disappeared after pair selection")

        common = sorted(set(genome_a.eval_scores) & set(genome_b.eval_scores))
        for benchmark in common:
            self._cycle.tournament.record_battle(
                benchmark=benchmark,
                genome_a_id=genome_a.id,
                genome_b_id=genome_b.id,
                score_a=genome_a.eval_scores[benchmark],
                score_b=genome_b.eval_scores[benchmark],
            )

        has_more = self._cursor < len(self._pairs)
        if not has_more:
            self._update_elos()
        return _BattleOutput(
            genome_a_id=genome_a.id,
            genome_b_id=genome_b.id,
            benchmarks=common,
            has_more=has_more,
        )

    def _update_elos(self) -> None:
        for genome in self._population.list_all():
            if not genome.eval_scores:
                continue
            avg_elo = self._cycle.tournament.get_avg_elo(genome.id)
            if avg_elo > 0:
                genome.harness_params["avg_elo"] = avg_elo
                self._population.add(genome)


class _PairPlanNode(BaseNode[_IgnoreInput, _PairPlanOutput]):
    kind: ClassVar[str] = _PAIR_KIND
    input_schema: ClassVar[type[BaseModel]] = _IgnoreInput
    output_schema: ClassVar[type[BaseModel]] = _PairPlanOutput
    display_name: ClassVar[str] = "Plan Evolve tournament pairs"
    description: ClassVar[str] = "Freeze this cycle's scored tournament pair ordering."

    def __init__(self, plan: _BattlePlan) -> None:
        self._plan = plan

    async def _execute(self, inputs: _IgnoreInput, ctx: NodeContext) -> _PairPlanOutput:
        return self._plan.prepare()


class _BattleNode(BaseNode[_IgnoreInput, _BattleOutput]):
    kind: ClassVar[str] = _BATTLE_KIND
    input_schema: ClassVar[type[BaseModel]] = _IgnoreInput
    output_schema: ClassVar[type[BaseModel]] = _BattleOutput
    display_name: ClassVar[str] = "Run Evolve tournament pair"
    description: ClassVar[str] = "Record one selected tournament pair as canonical work."

    def __init__(self, plan: _BattlePlan) -> None:
        self._plan = plan

    async def _execute(self, inputs: _IgnoreInput, ctx: NodeContext) -> _BattleOutput:
        return self._plan.next()


def _source_evaluation_refs(population: Any, genome: Any) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    seen: set[str] = set()
    for parent_id in (getattr(genome, "parent_a_id", None), getattr(genome, "parent_b_id", None)):
        if not parent_id:
            continue
        parent = population.get(parent_id)
        if parent is None:
            continue
        for item in parent.harness_params.get("evaluation_runs", []):
            if not isinstance(item, dict):
                continue
            attempt_id = str(item.get("attempt_id") or "")
            if not attempt_id or attempt_id in seen:
                continue
            seen.add(attempt_id)
            refs.append(
                {
                    "run_id": str(item.get("run_id") or ""),
                    "node_run_id": str(item.get("node_run_id") or ""),
                    "attempt_id": attempt_id,
                }
            )
    return refs


async def _finalize_cycle(cycle: Any, population: Any, config: Any, llm_call: Any) -> _FinalizeOutput:
    """Run post-tournament domain semantics without creating another lifecycle."""
    from maistro_evolve.population import IslandPopulation, migrate_islands

    before = {genome.id for genome in population.list_all()}
    cycle._compute_all_fitness(population)
    population.cull_bottom(config.cull_pct)

    if cycle._island_pop is None or cycle._island_pop.island_count != config.island_count:
        cycle._island_pop = IslandPopulation(config.island_count)
    island_pop = cycle._island_pop

    for genome in population.list_all():
        island_pop.assign(genome)

    island_size_cap = max(1, config.population_size // config.island_count)
    for island_id in island_pop.all_islands():
        cycle._breed_island(island_pop, island_id, population, config, island_size_cap)

    await cycle._self_improve_top(population, config, llm_call)
    for genome in population.list_all():
        island_pop.assign(genome)

    cycle._cycle_count += 1
    if cycle._cycle_count % config.migration_interval == 0:
        migrate_islands(island_pop, population)

    after = population.list_all()
    new_ids = sorted(genome.id for genome in after if genome.id not in before)
    new_id_set = set(new_ids)
    for genome in after:
        if genome.id not in new_id_set:
            continue
        refs = _source_evaluation_refs(population, genome)
        if refs:
            genome.harness_params["source_evaluation_runs"] = refs
            population.add(genome)

    return _FinalizeOutput(population_size=len(population.list_all()), new_genome_ids=new_ids)


class _FinalizeNode(BaseNode[_IgnoreInput, _FinalizeOutput]):
    kind: ClassVar[str] = _FINALIZE_KIND
    input_schema: ClassVar[type[BaseModel]] = _IgnoreInput
    output_schema: ClassVar[type[BaseModel]] = _FinalizeOutput
    display_name: ClassVar[str] = "Finalize Evolve cycle"
    description: ClassVar[str] = "Compute fitness, breed, improve, and migrate domain state."

    def __init__(self, *, cycle: Any, population: Any, config: Any, llm_call: Any) -> None:
        self._cycle = cycle
        self._population = population
        self._config = config
        self._llm_call = llm_call

    async def _execute(self, inputs: _IgnoreInput, ctx: NodeContext) -> _FinalizeOutput:
        return await _finalize_cycle(
            self._cycle,
            self._population,
            self._config,
            self._llm_call,
        )


def _evaluation_ids(population: Any, config: Any) -> list[str]:
    unevaluated = [
        genome
        for genome in population.list_all()
        if genome.fitness_score is None or not genome.eval_scores
    ]
    return [genome.id for genome in unevaluated[: config.eval_batch_size]]


def _build_graph(*, workspace_id: str, project_id: str, population: Any, config: Any) -> Graph:
    evaluation_ids = _evaluation_ids(population, config)
    nodes: list[Node] = []
    edges: list[Edge] = []

    evaluation_node_ids: list[str] = []
    for index, genome_id in enumerate(evaluation_ids, start=1):
        node_id = f"evolve-evaluate-{index}"
        evaluation_node_ids.append(node_id)
        nodes.append(
            Node(
                node_id=node_id,
                node_type=_EVALUATE_KIND,
                name=f"Evaluate genome {genome_id}",
                parameters={"genome_id": genome_id},
            )
        )

    battle_slots = len(population.list_all()) // 2
    pair_plan_id = "evolve-plan-pairs" if battle_slots else None
    if pair_plan_id is not None:
        nodes.append(Node(node_id=pair_plan_id, node_type=_PAIR_KIND, name="Plan tournament pairs"))

    battle_node_ids: list[str] = []
    for index in range(1, battle_slots + 1):
        node_id = f"evolve-battle-{index}"
        battle_node_ids.append(node_id)
        nodes.append(Node(node_id=node_id, node_type=_BATTLE_KIND, name=f"Tournament pair {index}"))

    final_id = "evolve-finalize"
    nodes.append(Node(node_id=final_id, node_type=_FINALIZE_KIND, name="Finalize cycle"))

    for left, right in pairwise(evaluation_node_ids):
        edges.append(Edge(from_node=left, to_node=right))

    after_evaluations = pair_plan_id or final_id
    if evaluation_node_ids:
        edges.append(Edge(from_node=evaluation_node_ids[-1], to_node=after_evaluations))

    if pair_plan_id is not None:
        edges.append(
            Edge(
                from_node=pair_plan_id,
                to_node=battle_node_ids[0],
                condition="has_battles == True",
            )
        )
        edges.append(
            Edge(
                from_node=pair_plan_id,
                to_node=final_id,
                condition="has_battles == False",
            )
        )

    for index, battle_id in enumerate(battle_node_ids):
        if index + 1 < len(battle_node_ids):
            edges.append(
                Edge(
                    from_node=battle_id,
                    to_node=battle_node_ids[index + 1],
                    condition="has_more == True",
                )
            )
        edges.append(
            Edge(
                from_node=battle_id,
                to_node=final_id,
                condition="has_more == False",
            )
        )

    entry = evaluation_node_ids[0] if evaluation_node_ids else pair_plan_id or final_id
    return Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name="Evolve cycle",
        nodes=nodes,
        edges=edges,
        metadata={"entry_node": entry, "execution_owner": "canonical_run", "product": "evolve"},
    )


def _resolver(*, cycle: Any, population: Any, config: Any, llm_call: Any):
    plan = _BattlePlan(cycle=cycle, population=population)
    evaluate = _EvaluateNode(cycle=cycle, population=population, config=config, llm_call=llm_call)
    pair_plan = _PairPlanNode(plan)
    battle = _BattleNode(plan)
    finalize = _FinalizeNode(cycle=cycle, population=population, config=config, llm_call=llm_call)

    def resolve(node_id: str, graph: Graph) -> BaseNode[Any, Any]:
        spec = next((item for item in graph.nodes if item.node_id == node_id), None)
        if spec is None:
            raise KeyError(f"unknown evolution graph node {node_id!r}")
        if spec.node_type == _EVALUATE_KIND:
            return evaluate
        if spec.node_type == _PAIR_KIND:
            return pair_plan
        if spec.node_type == _BATTLE_KIND:
            return battle
        if spec.node_type == _FINALIZE_KIND:
            return finalize
        raise KeyError(f"unsupported evolution node type {spec.node_type!r}")

    return resolve


def _engine_container() -> Any:
    from services.engine import get_engine

    engine = get_engine()
    container = getattr(getattr(engine, "_agent_port", None), "container", None)
    if container is None:
        raise RuntimeError("Evolve requires the canonical engine Container (#51)")
    return container


async def run_canonical_evolution_cycle(
    *,
    population: Any,
    tournament: Any,
    config: Any,
    harness: Any,
    llm_call: Any = None,
    actor_principal_id: str | None = None,
    cycle_number: int | None = None,
    container: Any | None = None,
) -> DurableRunRecord:
    """Execute one Evolve cycle as canonical Graph -> Run -> NodeRun -> Attempt work."""
    from maistro_evolve.cycle import EvolutionCycle

    owner = container or _engine_container()
    if owner.run_store is None or owner.graph_run_store is None or owner.project_scope_store is None:
        raise RuntimeError("Evolve canonical execution spine is unavailable (#51)")

    workspace_id = str(owner.config.workspace_id)
    project = await owner.project_scope_store.root_for_workspace(workspace_id)
    cycle = EvolutionCycle(harness=harness, tournament=tournament)
    if cycle.harness.fidelity != "real":
        logger.warning(
            "evolve_cycle_fidelity: this run's fitness signal is '%s' — proxy scoring, not official benchmarks",
            cycle.harness.fidelity,
        )

    graph = _build_graph(
        workspace_id=workspace_id,
        project_id=project.project_id,
        population=population,
        config=config,
    )
    provenance = {
        "admission_source": _ADMISSION_SOURCE,
        "product": "evolve",
        "cycle_number": cycle_number,
    }
    admitted = await owner.run_store.create_run(
        graph,
        actor_principal_id=actor_principal_id,
        provenance=provenance,
        initial_status=RunStatus.QUEUED,
    )
    return await run_durable_graph(
        graph,
        store=owner.graph_run_store,
        node_resolver=_resolver(cycle=cycle, population=population, config=config, llm_call=llm_call),
        actor_principal_id=actor_principal_id,
        run_id=admitted.run_id,
        provenance=provenance,
        run_store=owner.run_store,
    )


__all__ = ["run_canonical_evolution_cycle"]
