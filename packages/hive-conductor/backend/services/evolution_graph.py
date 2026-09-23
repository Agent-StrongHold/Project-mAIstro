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

<<<<<<< HEAD
import hashlib
import logging
import random
from collections.abc import Sequence
=======
import contextlib
import hashlib
import logging
import random
from collections.abc import AsyncIterator, Sequence
>>>>>>> 0221d2cd799ec075e30c33e0b2e2fda573865aef
from copy import deepcopy
from itertools import pairwise
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from maistro.graph.definitions import Edge, Graph, Node
from maistro.graph.durable_runs import (
    DurableRunRecord,
    NodeResolver,
    recover_queued_graph_runs,
    resume_due_graph_runs,
    run_durable_graph,
)
from maistro.graph.nodes.base import BaseNode, NodeContext
from maistro.runs.model import TERMINAL_RUN_STATUSES, Run, RunStatus
from services.scan_continuations import scan_continuation

logger = logging.getLogger(__name__)

_ADMISSION_SOURCE = "evolve"
_EVALUATE_KIND = "evolve.evaluate_genome"
_PAIR_KIND = "evolve.plan_tournament_pairs"
_BATTLE_KIND = "evolve.tournament_pair"
_FINALIZE_KIND = "evolve.finalize_cycle"


class CanonicalExecutionUnavailable(RuntimeError):
    """The engine cannot admit Evolve work onto the canonical Run spine."""

    def __init__(self, message: str, *, availability: str = "unavailable") -> None:
        super().__init__(message)
        self.availability = availability


<<<<<<< HEAD
=======
class EvolveRecoveryBlocked(RuntimeError):
    """A stranded/due Evolve Run cannot be safely resumed by this process (#1064).

    Evolve's population/tournament/cycle domain state is process-local (an
    in-memory ``PopulationStore``/``EloTournament`` unless a deployment opts a
    SQLite ``db_path`` into ``PopulationStore``, which this app does not).
    There is therefore no durable cross-process domain state a genuinely
    different process could reconstruct. Raising this — rather than silently
    resuming against a fabricated fresh population/tournament (silent domain
    corruption) — is the honest disposition. See ``_recovery_resolver``'s
    docstring for exactly how each recovery seam disposes of this: a Run
    already RUNNING/WAITING reaches a terminal FAILED Run with this
    diagnostic; a Run still QUEUED is isolated and retried on a later tick,
    never resumed against the wrong population and never faked as success.
    """


class FinalizeReconciliationRequired(RuntimeError):
    """A prior finalize Attempt mutated domain state but never committed (#1064).

    ``_finalize_cycle`` cannot stage its many mutations (cull, breed,
    self-improve, migrate, lineage) on a private copy the way evaluation
    stages a single genome, so a fault partway through leaves population/
    tournament state partially advanced with no committed NodeRun evidence.
    Blindly retrying would redo mutations already applied (double cull,
    double breed, a second paid self-improve pass); silently succeeding on
    retry would hide that the first attempt's effects are unaccounted for.
    Neither is safe, so a retry of a NodeRun found in this state fails
    closed with this diagnostic instead, requiring explicit operator
    reconciliation of the affected population before the cycle can be
    retried as a new logical Run.
    """


>>>>>>> 0221d2cd799ec075e30c33e0b2e2fda573865aef
class _EvaluateInput(BaseModel):
    genome_id: str


class _EvaluateOutput(BaseModel):
    # Deliberately omit genome_id. Canonical predecessor outputs override a
    # successor's static inputs, so emitting it would make evaluation N+1
    # inherit evaluation N's genome instead of its own Graph parameter.
    benchmarks: dict[str, float] = Field(default_factory=dict)
    evaluation_run_id: str
    evaluation_node_run_id: str
    evaluation_attempt_id: str


class _IgnoreInput(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _PairPlanOutput(BaseModel):
    # The selected order is execution state, not Evolve domain state. Carry it
    # in the canonical NodeRun result so process recovery never depends on an
    # in-memory random shuffle surviving.
    pairs: list[tuple[str, str]] = Field(default_factory=list)
    pair_index: int = 0
    pair_count: int
    has_battles: bool


class _BattleInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    pairs: list[tuple[str, str]]
    pair_index: int = 0


class _BattleOutput(BaseModel):
    # Re-emit the plan and cursor so every next battle can reconstruct its work
    # exclusively from its persisted immediate-predecessor result.
    pairs: list[tuple[str, str]] = Field(default_factory=list)
    pair_index: int
    genome_a_id: str
    genome_b_id: str
    benchmarks: list[str] = Field(default_factory=list)
    has_more: bool = False
    # The logical NodeRun this battle was published under. Canonical
    # publication evidence (#1064), mirroring evaluation's
    # evaluation_node_run_id: lets later inspection confirm which NodeRun a
    # domain GenomeBattle came from without re-deriving it from timing.
    battle_node_run_id: str = ""


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


def _published_evaluation_ref(genome: Any, node_run_id: str) -> dict[str, str] | None:
    """Return evidence when this logical evaluation NodeRun already published domain state."""
    for item in genome.harness_params.get("evaluation_runs", []):
        if not isinstance(item, dict) or str(item.get("node_run_id") or "") != node_run_id:
            continue
        run_id = str(item.get("run_id") or "")
        attempt_id = str(item.get("attempt_id") or "")
        if run_id and attempt_id:
            return {
                "run_id": run_id,
                "node_run_id": node_run_id,
                "attempt_id": attempt_id,
            }
    return None


async def _evaluate_one(
    cycle: Any,
    population: Any,
    config: Any,
    llm_call: Any,
    genome_id: str,
    ctx: NodeContext,
) -> _EvaluateOutput:
    """Evaluate one genome and publish domain changes at most once per logical NodeRun."""
    from datetime import UTC, datetime

    genome = population.get(genome_id)
    if genome is None:
        raise ValueError(f"evolution genome {genome_id!r} disappeared before evaluation")

    # Process-loss recovery creates a fresh Attempt beneath the same NodeRun.
    # If the prior process committed the domain state but died before its
    # Attempt could be terminalized, the persisted NodeRun marker is the
    # idempotency key: accept the already-published score instead of evaluating
    # and folding it a second time. A genuine logical retry is a new NodeRun, so
    # it still evaluates normally.
    published = _published_evaluation_ref(genome, ctx.node_run_id)
    if published is not None:
        return _EvaluateOutput(
            benchmarks=dict(genome.eval_scores),
            evaluation_run_id=published["run_id"],
            evaluation_node_run_id=published["node_run_id"],
            evaluation_attempt_id=published["attempt_id"],
        )

    # Evaluation is physical work beneath one Attempt. Stage every score/cost
    # mutation on a private copy so an exception anywhere in the Attempt leaves
    # the population unchanged. A later logical retry therefore gets a new
    # NodeRun/Attempt and re-evaluates the last committed genome rather than
    # folding over a partial failed score.
    working = deepcopy(genome)
    results = await cycle.harness.evaluate_genome(
        working,
        config.target_benchmarks,
        llm_call,
    )
    for result in results:
        cycle._fold_score(
            working,
            result.benchmark,
            result.score,
            bool(result.metadata.get("stub")),
            config.eval_ema_alpha,
        )
        working.harness_params["total_cost_usd"] = (
            working.harness_params.get("total_cost_usd", 0.0) + result.cost_usd
        )
        working.harness_params["avg_latency_seconds"] = (
            working.harness_params.get("avg_latency_seconds", 0.0) + result.duration_seconds
        ) / max(len(working.eval_scores), 1)

    _append_execution_ref(working, ctx)
    working.updated_at = datetime.now(UTC).isoformat()
    population.add(working)
    return _EvaluateOutput(
        benchmarks=dict(working.eval_scores),
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

    def __init__(
        self,
        *,
        cycle: Any,
        population: Any,
        config: Any,
        llm_call: Any,
    ) -> None:
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


class _TournamentWork:
    """Apply tournament semantics to the cycle's frozen membership snapshot."""

    def __init__(
        self,
        *,
        cycle: Any,
        population: Any,
        membership_ids: Sequence[str] | None = None,
        battle_slots: int | None = None,
    ) -> None:
        self._cycle = cycle
        self._population = population
        # The default keeps this helper convenient for focused unit tests. The
        # production resolver always supplies the admission-time snapshot.
        self._membership_ids = tuple(
            membership_ids
            if membership_ids is not None
            else (str(genome.id) for genome in population.list_all())
        )
        self._battle_slots = battle_slots

    def prepare(self) -> _PairPlanOutput:
        scored = []
        for genome_id in self._membership_ids:
            genome = self._population.get(genome_id)
            if genome is None:
                raise RuntimeError(
                    f"frozen evolution genome {genome_id!r} disappeared before pair planning"
                )
            if genome.eval_scores:
                scored.append(genome)
        shuffled = list(scored)
        random.shuffle(shuffled)
        pairs = [
            (shuffled[index].id, shuffled[index + 1].id) for index in range(0, len(shuffled) - 1, 2)
        ]
        return _PairPlanOutput(
            pairs=pairs,
            pair_index=0,
            pair_count=len(pairs),
            has_battles=bool(pairs),
        )

    def run_pair(self, inputs: _BattleInput, ctx: NodeContext | None = None) -> _BattleOutput:
        if inputs.pair_index < 0 or inputs.pair_index >= len(inputs.pairs):
            raise RuntimeError(
                "tournament graph requested a battle outside its persisted pair plan"
            )
        if self._battle_slots is not None and inputs.pair_index >= self._battle_slots:
            raise RuntimeError("tournament graph requested a battle beyond its immutable capacity")
        if (
            self._battle_slots is not None
            and inputs.pair_index == self._battle_slots - 1
            and inputs.pair_index + 1 < len(inputs.pairs)
        ):
            # Do this before recording a battle: a malformed plan must fail the
            # canonical Attempt rather than leave an un-routable side effect.
            raise RuntimeError(
                "tournament pair plan has_more=True but the immutable graph has no successor"
            )

        genome_a_id, genome_b_id = inputs.pairs[inputs.pair_index]
        genome_a = self._population.get(genome_a_id)
        genome_b = self._population.get(genome_b_id)
        if genome_a is None or genome_b is None:
            raise ValueError("a tournament genome disappeared after pair selection")

        node_run_id = ctx.node_run_id if ctx is not None else None
        attempt_id = ctx.attempt_id if ctx is not None else None
        common = sorted(set(genome_a.eval_scores) & set(genome_b.eval_scores))
        for benchmark in common:
            # Idempotent per (node_run_id, benchmark): a recovered Attempt for
            # the same logical NodeRun that already published this
            # benchmark's battle is a no-op here rather than a second
            # win/loss/Elo update (#1064). Each benchmark commits
            # independently, so a fault partway through this loop on retry
            # only replays the benchmarks that never published, not the ones
            # that did.
            self._cycle.tournament.record_battle(
                benchmark=benchmark,
                genome_a_id=genome_a.id,
                genome_b_id=genome_b.id,
                score_a=genome_a.eval_scores[benchmark],
                score_b=genome_b.eval_scores[benchmark],
                node_run_id=node_run_id,
                attempt_id=attempt_id,
            )

        next_index = inputs.pair_index + 1
        return _BattleOutput(
            pairs=list(inputs.pairs),
            pair_index=next_index,
            genome_a_id=genome_a.id,
            genome_b_id=genome_b.id,
            benchmarks=common,
            has_more=next_index < len(inputs.pairs),
            battle_node_run_id=node_run_id or "",
        )


class _PairPlanNode(BaseNode[_IgnoreInput, _PairPlanOutput]):
    kind: ClassVar[str] = _PAIR_KIND
    input_schema: ClassVar[type[BaseModel]] = _IgnoreInput
    output_schema: ClassVar[type[BaseModel]] = _PairPlanOutput
    display_name: ClassVar[str] = "Plan Evolve tournament pairs"
    description: ClassVar[str] = "Persist this cycle's scored tournament pair ordering."

    def __init__(self, tournament_work: _TournamentWork) -> None:
        self._tournament_work = tournament_work

    async def _execute(self, inputs: _IgnoreInput, ctx: NodeContext) -> _PairPlanOutput:
        return self._tournament_work.prepare()


class _BattleNode(BaseNode[_BattleInput, _BattleOutput]):
    kind: ClassVar[str] = _BATTLE_KIND
    input_schema: ClassVar[type[BaseModel]] = _BattleInput
    output_schema: ClassVar[type[BaseModel]] = _BattleOutput
    display_name: ClassVar[str] = "Run Evolve tournament pair"
    description: ClassVar[str] = "Record one persisted tournament pair as canonical work."

    def __init__(
        self,
        tournament_work: _TournamentWork,
        *,
        has_more_successor: bool,
        completion_successor: bool,
    ) -> None:
        self._tournament_work = tournament_work
        self._has_more_successor = has_more_successor
        self._completion_successor = completion_successor

    async def _execute(self, inputs: _BattleInput, ctx: NodeContext) -> _BattleOutput:
        has_more = inputs.pair_index + 1 < len(inputs.pairs)
        if has_more and not self._has_more_successor:
            raise RuntimeError(
                "tournament battle returned has_more=True but has no executable successor"
            )
        if not has_more and not self._completion_successor:
            raise RuntimeError(
                "tournament battle completed without an executable finalization successor"
            )
        # Validate graph capacity before recording tournament evidence so a
        # malformed immutable graph cannot leave a domain battle half-applied.
<<<<<<< HEAD
        return self._tournament_work.run_pair(inputs)
=======
        return self._tournament_work.run_pair(inputs, ctx)
>>>>>>> 0221d2cd799ec075e30c33e0b2e2fda573865aef


def _source_evaluation_refs(population: Any, genome: Any) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    seen: set[str] = set()
    for parent_id in (
        getattr(genome, "parent_a_id", None),
        getattr(genome, "parent_b_id", None),
    ):
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


def _publish_tournament_elos(cycle: Any, population: Any) -> None:
    """Fold completed battle-domain ratings into genomes before fitness is computed."""
    for genome in population.list_all():
        if not genome.eval_scores:
            continue
        avg_elo = cycle.tournament.get_avg_elo(genome.id)
        if avg_elo > 0:
            genome.harness_params["avg_elo"] = avg_elo
            population.add(genome)


def _finalize_marker_id(node_run_id: str) -> str:
    return f"finalize:{node_run_id}"


async def _finalize_cycle(
    cycle: Any,
    population: Any,
    config: Any,
    llm_call: Any,
    ctx: NodeContext | None = None,
) -> _FinalizeOutput:
    """Run post-tournament domain semantics without creating another lifecycle.

    Idempotent publication mirrors ``_evaluate_one`` (#1064): before mutating
    anything, check whether this logical NodeRun already committed. Unlike
    evaluation, finalize cannot stage its many mutations (cull, breed,
    self-improve, migrate, lineage) on a private copy and commit them
    atomically at the end -- ``PopulationStore``/``IslandPopulation`` mutate
    in place. So a fault *partway through* this function is recorded as an
    explicit "faulted" marker rather than left to a blind retry, which would
    otherwise double-apply whatever already committed. A later Attempt for
    the same NodeRun that finds a faulted marker fails closed with
    ``FinalizeReconciliationRequired`` instead of silently re-mutating or
    silently succeeding.
    """
    marker_id = _finalize_marker_id(ctx.node_run_id) if ctx is not None else None
    if marker_id is not None:
        marker = population.get_cycle_marker(marker_id)
        if marker is not None:
            status = marker.get("status")
            if status == "committed":
                return _FinalizeOutput.model_validate(marker["output"])
            raise FinalizeReconciliationRequired(
                f"finalize NodeRun {ctx.node_run_id!r} previously faulted after "
                "partially mutating domain state; refusing to retry automatically"
            )
        population.record_cycle_marker(marker_id, {"status": "in_progress"})

    try:
        new_ids = await _apply_finalize_mutations(cycle, population, config, llm_call)
    except Exception:
        if marker_id is not None:
            population.record_cycle_marker(marker_id, {"status": "faulted"})
        raise

    output = _FinalizeOutput(
        population_size=len(population.list_all()),
        new_genome_ids=new_ids,
    )
    if marker_id is not None:
        population.record_cycle_marker(
            marker_id, {"status": "committed", "output": output.model_dump()}
        )
    return output


async def _apply_finalize_mutations(
    cycle: Any, population: Any, config: Any, llm_call: Any
) -> list[str]:
    """The actual cull/breed/self-improve/migrate/lineage mutation sequence.

    Split out of ``_finalize_cycle`` purely so that function's fault-marker
    try/except stays a thin, readable wrapper around this -- not a behavior
    change. Returns the sorted ids of genomes created by this finalize.
    """
    from maistro_evolve.population import IslandPopulation, migrate_islands

    before = {genome.id for genome in population.list_all()}
    _publish_tournament_elos(cycle, population)
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
    return new_ids


class _FinalizeNode(BaseNode[_IgnoreInput, _FinalizeOutput]):
    kind: ClassVar[str] = _FINALIZE_KIND
    input_schema: ClassVar[type[BaseModel]] = _IgnoreInput
    output_schema: ClassVar[type[BaseModel]] = _FinalizeOutput
    display_name: ClassVar[str] = "Finalize Evolve cycle"
    description: ClassVar[str] = "Compute fitness, breed, improve, and migrate domain state."

    def __init__(
        self,
        *,
        cycle: Any,
        population: Any,
        config: Any,
        llm_call: Any,
    ) -> None:
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
            ctx,
        )


def _population_membership(population: Any) -> tuple[str, ...]:
    """Capture the admission-time member ids used by one immutable cycle plan."""
    return tuple(sorted(str(genome.id) for genome in population.list_all()))


def _membership_hash(membership_ids: Sequence[str]) -> str:
    encoded = "\n".join(membership_ids).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _evaluation_ids(
    population: Any,
    config: Any,
    membership_ids: Sequence[str] | None = None,
) -> list[str]:
    ids = membership_ids if membership_ids is not None else _population_membership(population)
    unevaluated = []
    for genome_id in ids:
        genome = population.get(genome_id)
        if genome is None:
            raise RuntimeError(
                f"frozen evolution genome {genome_id!r} disappeared while building the graph"
            )
        if genome.fitness_score is None or not genome.eval_scores:
            unevaluated.append(genome)
    return [genome.id for genome in unevaluated[: config.eval_batch_size]]


def _build_graph(
    *,
    workspace_id: str,
    project_id: str,
    population: Any,
    config: Any,
    membership_ids: Sequence[str] | None = None,
) -> Graph:
    frozen_membership = tuple(
        membership_ids if membership_ids is not None else _population_membership(population)
    )
    evaluation_ids = _evaluation_ids(population, config, frozen_membership)
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

    # Battle capacity is derived from the same admission snapshot as pair
    # planning, never from the live store after evaluation begins.
    battle_slots = len(frozen_membership) // 2
    pair_plan_id = "evolve-plan-pairs" if battle_slots else None
    if pair_plan_id is not None:
        nodes.append(
            Node(
                node_id=pair_plan_id,
                node_type=_PAIR_KIND,
                name="Plan tournament pairs",
            )
        )

    battle_node_ids: list[str] = []
    for index in range(1, battle_slots + 1):
        node_id = f"evolve-battle-{index}"
        battle_node_ids.append(node_id)
        nodes.append(
            Node(
                node_id=node_id,
                node_type=_BATTLE_KIND,
                name=f"Tournament pair {index}",
            )
        )

    final_id = "evolve-finalize"
    nodes.append(
        Node(
            node_id=final_id,
            node_type=_FINALIZE_KIND,
            name="Finalize cycle",
        )
    )

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
        metadata={
            "entry_node": entry,
            "execution_owner": "canonical_run",
            "product": "evolve",
            "evolve_membership_ids": list(frozen_membership),
            "evolve_membership_count": len(frozen_membership),
            "evolve_membership_hash": _membership_hash(frozen_membership),
            "evolve_battle_capacity": battle_slots,
        },
    )


def _resolver(
    *,
    cycle: Any,
    population: Any,
    config: Any,
    llm_call: Any,
    membership_ids: Sequence[str] | None = None,
    battle_slots: int | None = None,
):
    tournament_work = _TournamentWork(
        cycle=cycle,
        population=population,
        membership_ids=membership_ids,
        battle_slots=battle_slots,
    )
    evaluate = _EvaluateNode(
        cycle=cycle,
        population=population,
        config=config,
        llm_call=llm_call,
    )
    pair_plan = _PairPlanNode(tournament_work)
    finalize = _FinalizeNode(
        cycle=cycle,
        population=population,
        config=config,
        llm_call=llm_call,
    )

    def resolve(node_id: str, graph: Graph) -> BaseNode[Any, Any]:
        spec = next((item for item in graph.nodes if item.node_id == node_id), None)
        if spec is None:
            raise KeyError(f"unknown evolution graph node {node_id!r}")
        if spec.node_type == _EVALUATE_KIND:
            return evaluate
        if spec.node_type == _PAIR_KIND:
            return pair_plan
        if spec.node_type == _BATTLE_KIND:
            return _BattleNode(
                tournament_work,
                has_more_successor=any(
                    edge.from_node == node_id and edge.condition == "has_more == True"
                    for edge in graph.edges
                ),
                completion_successor=any(
                    edge.from_node == node_id and edge.condition == "has_more == False"
                    for edge in graph.edges
                ),
            )
        if spec.node_type == _FINALIZE_KIND:
            return finalize
        raise KeyError(f"unsupported evolution node type {spec.node_type!r}")

    return resolve


def canonical_execution_owner(container: Any | None = None) -> Any:
    """Return the already-constructed Container that owns canonical Runs.

    Evolve may inspect this owner, but never constructs or replaces it. The
    same admission check is used by startup/status and by cycle execution so a
    truthful status cannot drift from the path that admits work.
    """
    if container is None:
        from services.engine import get_engine

        try:
            engine = get_engine()
        except RuntimeError as exc:
            raise CanonicalExecutionUnavailable(
                "Evolve requires the canonical engine Container (#51): engine is not started"
            ) from exc
        port = getattr(engine, "agent_port", None)
        if port is None:
            # Keep isolated engine doubles compatible with the public accessor's
            # underlying seam while production uses `agent_port` above.
            port = getattr(engine, "_agent_port", None)
        container = getattr(port, "container", None)

    if container is None:
        raise CanonicalExecutionUnavailable(
            "Evolve requires the canonical engine Container (#51): no Container is available",
            availability="degraded",
        )

    missing = [
        name
        for name in ("run_store", "graph_run_store", "project_scope_store")
        if getattr(container, name, None) is None
    ]
    if missing:
        raise CanonicalExecutionUnavailable(
            f"Evolve canonical execution spine is unavailable (#51): missing {', '.join(missing)}",
            availability="degraded",
        )
    return container


def _engine_container() -> Any:
    return canonical_execution_owner()


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

    owner = canonical_execution_owner(container)
    # This snapshot is the cycle's domain boundary. Later seeds may mutate the
    # live population, but they cannot add evaluation or tournament work here.
    membership_ids = _population_membership(population)

    workspace_id = str(owner.config.workspace_id)
    project = await owner.project_scope_store.root_for_workspace(workspace_id)
    cycle = EvolutionCycle(harness=harness, tournament=tournament)
    if cycle.harness.fidelity != "real":
        logger.warning(
            "evolve_cycle_fidelity: this run's fitness signal is '%s' — "
            "proxy scoring, not official benchmarks",
            cycle.harness.fidelity,
        )

    graph = _build_graph(
        workspace_id=workspace_id,
        project_id=project.project_id,
        population=population,
        config=config,
        membership_ids=membership_ids,
    )
    battle_slots = len(membership_ids) // 2
    provenance = {
        "admission_source": _ADMISSION_SOURCE,
        "product": "evolve",
        "cycle_number": cycle_number,
        "evolve_membership_ids": list(membership_ids),
        "evolve_membership_count": len(membership_ids),
        "evolve_membership_hash": _membership_hash(membership_ids),
        "evolve_battle_capacity": battle_slots,
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
        node_resolver=_resolver(
            cycle=cycle,
            population=population,
            config=config,
            llm_call=llm_call,
            membership_ids=membership_ids,
            battle_slots=battle_slots,
        ),
        actor_principal_id=actor_principal_id,
        run_id=admitted.run_id,
        provenance=provenance,
        run_store=owner.run_store,
    )


def _recovery_resolver(run: Run) -> NodeResolver:
    """Rebuild an Evolve node resolver from durable Run facts for one candidate.

    Evolve's node resolver has always been a closure over LIVE domain objects
    (``EvolutionCycle``, ``PopulationStore``, ``EloTournament``, config,
    llm_call) built fresh inside ``run_canonical_evolution_cycle`` and handed
    straight to ``run_durable_graph`` (#1064) -- nothing reconstructs it for a
    persisted Run at startup/recovery. This is the shipped resolver that
    closes that gap.

    What it can honestly reconstruct: the frozen membership/battle-capacity
    plan (durable Run provenance, #1065) and the *default* config/harness this
    app always uses for a cycle (``services.evolution._run_one_cycle_locked``
    hardcodes both, so replaying them here is not a guess). What it cannot
    reconstruct: the live ``PopulationStore``/``EloTournament`` themselves --
    this app's ``PopulationStore`` is in-memory only (no ``db_path``), so
    there is no durable cross-process domain state to rebuild from. A
    genuinely different process (or this process before
    ``services.evolution.start_evolution`` has run) has nothing to resume
    against.

    Rather than silently resuming against a *fabricated* fresh population/
    tournament (which would corrupt the domain with a different logical
    population under the same Run), this raises :class:`EvolveRecoveryBlocked`
    whenever the prerequisites are not durably available *in this process*.
    What the shared recovery seam (``maistro.graph.durable_runs.recovery``)
    does with that failure depends on which half of recovery called it:

    * ``resume_due_graph_runs`` (a RUNNING/WAITING Run whose Attempt lease or
      timed wait has elapsed -- the crash-mid-node case this issue is really
      about) defers resolver construction into the executor's own failure
      boundary (``_lazy_resolver``), which turns this into a terminal FAILED
      Run carrying a stable, sanitized diagnostic. Never an indefinite hang.
    * ``recover_queued_graph_runs`` (a Run stranded before its first NodeRun
      even started) calls the resolver eagerly and, finding nothing yet
      claimed, isolates the failure as candidate-local and leaves the Run
      QUEUED for a later tick -- the identical documented contract the
      legacy DAG adapter's own resolver already gets there. That is a
      bounded, observable retry (logged every tick), not silent progress and
      never resumption against the wrong population; it resolves itself once
      this process's Evolve service finishes starting, or stays visibly
      retried (never faked as success) if it never will.

    Either way, only a process that still holds the exact frozen membership
    this Run was admitted against may resume it; every other process
    (including a genuine second replica) fails closed the same way, which is
    what keeps concurrent recovery attempts from two replicas from both
    publishing the same NodeRun mutation.
    """
    from maistro_evolve.cycle import EvolutionConfig, EvolutionCycle
    from maistro_evolve.harness import EvalHarness
    from services.evolution import EvolutionServiceNotStarted, get_evolution_service

    graph = run.graph.materialize()
    membership_ids = [str(item) for item in run.provenance.get("evolve_membership_ids") or []]
    if not membership_ids:
        membership_ids = [str(item) for item in graph.metadata.get("evolve_membership_ids") or []]
    battle_slots = run.provenance.get("evolve_battle_capacity")
    if battle_slots is None:
        battle_slots = graph.metadata.get("evolve_battle_capacity")
    if battle_slots is None:
        battle_slots = len(membership_ids) // 2

    try:
        service = get_evolution_service()
    except EvolutionServiceNotStarted as exc:
        raise EvolveRecoveryBlocked(
            f"Evolve Run {run.run_id!r} cannot be recovered: the Evolve service has not "
            "started in this process"
        ) from exc

    population = service.population
    tournament = service.tournament
    if population is None or tournament is None:
        raise EvolveRecoveryBlocked(
            f"Evolve Run {run.run_id!r} cannot be recovered: this process has no live "
            "population/tournament domain state"
        )

    missing = [genome_id for genome_id in membership_ids if population.get(genome_id) is None]
    if missing:
        raise EvolveRecoveryBlocked(
            f"Evolve Run {run.run_id!r} cannot be recovered: this process's live population "
            f"is missing {len(missing)} of its {len(membership_ids)} frozen member genome(s) "
            "-- it is not the population this Run was admitted against"
        )

    # The live membership must equal the frozen plan exactly, not merely
    # contain it (#1064). ``_apply_finalize_mutations`` operates over
    # ``population.list_all()`` wholesale -- cull/breed/self-improve/migrate
    # all see every genome currently in the store, never just the ones this
    # Run's node resolver was handed. On the live path that is safe only
    # because ``_cycle_lock`` keeps ``seed_population``/a later cycle from
    # adding genomes while a cycle is in flight; recovery holds that same
    # lock (see the module-level docstring above), but a seed request that
    # landed and released the lock *before* a stranded Run was noticed can
    # still have added genomes this Run's plan never admitted. Accepting
    # that drift here would let recovered finalization cull, breed from,
    # self-improve, or migrate genomes that were never part of this Run.
    live_ids = {str(genome.id) for genome in population.list_all()}
    extra = sorted(live_ids - set(membership_ids))
    if extra:
        raise EvolveRecoveryBlocked(
            f"Evolve Run {run.run_id!r} cannot be recovered: this process's live population "
            f"has {len(extra)} genome(s) outside its {len(membership_ids)} frozen member "
            "genome(s) -- a later seed or cycle added members after this Run was admitted, "
            "and recovered finalization must never touch genomes that were not part of this "
            "Run's plan"
        )

    config = EvolutionConfig(self_improve=True, self_improve_top_n=3)
    harness = EvalHarness(benchmark_fidelity="proxy")
    cycle = EvolutionCycle(harness=harness, tournament=tournament)
    llm_call = service.build_llm_call()

    return _resolver(
        cycle=cycle,
        population=population,
        config=config,
        llm_call=llm_call,
        membership_ids=membership_ids,
        battle_slots=battle_slots,
    )


def _admitted_by_evolve(run: Run) -> bool:
    return run.provenance.get("admission_source") == _ADMISSION_SOURCE


def _current_evolution_service() -> Any | None:
    """The live ``_EvolutionService`` singleton, or ``None`` if not started.

    ``None`` is a real, expected answer here (unlike inside
    ``_recovery_resolver``, which must fail a *candidate* closed): a recovery
    tick that finds no service yet has nothing to serialize against and
    nothing to reconcile -- every candidate it touches will fail closed on
    its own via ``_recovery_resolver`` raising ``EvolveRecoveryBlocked``.
    """
    from services.evolution import EvolutionServiceNotStarted, get_evolution_service

    try:
        return get_evolution_service()
    except EvolutionServiceNotStarted:
        return None


@contextlib.asynccontextmanager
async def _serialized_against_live_cycles(service: Any | None) -> AsyncIterator[None]:
    """Hold the same lock ``seed_population``/a live cycle hold while mutating (#1064).

    Both recovery seams execute evaluate/battle/finalize graph nodes
    immediately, exactly like a live cycle, against the same
    ``PopulationStore``/``EloTournament`` that ``seed_population`` and
    ``_run_one_cycle_locked`` already serialize through
    ``_EvolutionService._cycle_lock``. Without holding that same lock here, a
    recovery tick that overlaps a live cycle or a seed request could
    interleave evaluation, battle, and finalize node execution with culling,
    breeding, and rating updates, corrupting the shared domain state despite
    the normal execution path's own serialization.

    No live service means nothing can mutate through this seam either --
    every candidate's resolver fails closed with ``EvolveRecoveryBlocked``
    before touching any domain object -- so there is nothing to serialize.
    """
    if service is None:
        yield
        return
    async with service.cycle_lock:
        yield


async def _reconcile_recovered_runs(service: Any, run_store: Any, run_ids: Sequence[str]) -> None:
    """Fold recovery's dispositions into the service state ``/evolution/status`` reads (#1064).

    ``recover_queued_graph_runs``/``resume_due_graph_runs`` mutate this
    Run's population/tournament domain state directly but return only a
    count, bypassing the ``cycle_count``/``last_run_id``/``last_run_status``
    bookkeeping ``_run_one_cycle_locked`` performs for a live cycle. Without
    this, a stranded/due Run recovered to a terminal status left
    ``/evolution/status`` reporting the prior cycle's facts, and the next
    live admission could reuse the recovered cycle's ``cycle_number``. Only a
    Run this tick actually attempted (a resolver was built for it) and that
    is now terminal is folded in; a Run left QUEUED/WAITING (isolated for a
    later tick) has nothing new to report.
    """
    for run_id in run_ids:
        run = await run_store.get_run(run_id)
        if run is None or run.status not in TERMINAL_RUN_STATUSES:
            continue
        service.record_recovered_run(run_id, run.status, error=run.error)


def _tracking_recovery_resolver_factory(sink: list[str]) -> Any:
    """Wrap ``_recovery_resolver`` to record which Runs this tick attempted.

    ``node_resolver_factory`` is the only per-candidate seam the shared
    recovery primitive exposes; recording each candidate's ``run_id`` here is
    how the tick later knows which Runs to reconcile status for, without
    changing ``recover_queued_graph_runs``/``resume_due_graph_runs`` (shared
    with the legacy DAG adapter) to return more than a count.
    """

    def factory(run: Run) -> NodeResolver:
        sink.append(run.run_id)
        return _recovery_resolver(run)

    return factory


async def recover_stranded_evolution_runs(*, limit: int = 100) -> int:
    """Recover only canonical Runs admitted by this Evolve adapter (#1064).

    Mirrors ``services.canonical_dag_runner.recover_stranded_dag_runs``: bring
    a Run stranded around checkpoint 1 (admitted QUEUED, never reached
    RUNNING) back onto the executor. A Run this process cannot honestly
    resume terminalizes FAILED via ``_recovery_resolver`` rather than staying
    stuck (see its docstring).
    """
    try:
        owner = canonical_execution_owner()
    except CanonicalExecutionUnavailable:
        return 0
    service = _current_evolution_service()
    attempted: list[str] = []
    async with _serialized_against_live_cycles(service):
        recovered = await recover_queued_graph_runs(
            store=owner.graph_run_store,
            run_store=owner.run_store,
            node_resolver_factory=_tracking_recovery_resolver_factory(attempted),
            eligible=_admitted_by_evolve,
            admission_source=_ADMISSION_SOURCE,
            limit=limit,
            events=owner.event_bus,
            # Held across ticks, mirroring the legacy-DAG wrapper (#1127):
            # the scan is bounded per call, so without one, at least `limit`
            # earlier unrecoverable candidates would be reselected on every
            # tick and starve every later queued Run.
            scan=scan_continuation("recover_queued_graph_runs", owner.run_store),
        )
        if service is not None and attempted:
            await _reconcile_recovered_runs(service, owner.run_store, attempted)
    return recovered


async def wake_due_evolution_runs(*, limit: int = 100) -> int:
    """Wake elapsed Evolve continuations through the canonical resume seam (#1064).

    Mirrors ``services.canonical_dag_runner.wake_due_dag_runs``. The resolver
    is rebuilt per Run from durable facts every time -- which node
    implementation resumes a Run is never this process's memory of a prior
    call, only what the Run itself durably records.
    """
    try:
        owner = canonical_execution_owner()
    except CanonicalExecutionUnavailable:
        return 0
    service = _current_evolution_service()
    attempted: list[str] = []
    async with _serialized_against_live_cycles(service):
        resumed = await resume_due_graph_runs(
            store=owner.graph_run_store,
            run_store=owner.run_store,
            node_resolver_factory=_tracking_recovery_resolver_factory(attempted),
            eligible=_admitted_by_evolve,
            limit=limit,
            events=owner.event_bus,
            scan=scan_continuation("resume_due_graph_runs", owner.graph_run_store),
        )
        if service is not None and attempted:
            await _reconcile_recovered_runs(service, owner.run_store, attempted)
    return resumed


__all__ = [
    "recover_stranded_evolution_runs",
    "run_canonical_evolution_cycle",
    "wake_due_evolution_runs",
]
