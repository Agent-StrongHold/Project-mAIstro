"""Process-death restart replay for Evolve battle/finalize publication (#1064).

The #1064 close-only bar: fault injection at the domain-mutation →
Attempt-commit boundary, recovery of the exact Run/NodeRun on objects that
share nothing with the killed walker except durable state, and exactly-once
domain publication across that restart. Every "process" here is an
independent object graph over the same durable files — its own sqlite
canonical spine connections, its own domain store instance, its own
PopulationStore/EloTournament — mirroring the independent-pool shape the
spine crash-window suite established for restarts, with the Evolve domain's
durable ledger carrying what the in-memory store alone never could.

The killed seam is the worst one the issue names: `run_pair_durable` has
committed the durable battle row (the exactly-once evidence) but has not
applied it to the dying process's in-memory tournament and has not
terminalized the Attempt. Recovery must show exactly one battle, one outcome,
and one Elo update for that logical NodeRun — reconstructed, not remembered.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import aiosqlite
import pytest
from services.evolution_graph import (
    FinalizeReconciliationRequired,
    NodeContext,
    _admitted_by_evolve,
    _finalize_cycle,
    _recovery_resolver,
    run_canonical_evolution_cycle,
)
from services.evolve_domain_store import SqliteEvolveDomainStore

import maistro_evolve.cycle as cycle_module
from maistro.graph.durable_runs import (
    CanonicalDurableRunStore,
    resume_due_graph_runs,
)
from maistro.graph.durable_runs.continuation import SqliteGraphContinuationStore
from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore
from maistro.runs.model import RunStatus
from maistro.runs.sqlite_store import SqliteRunStore
from maistro_evolve.types import DAGTopology, EvalWeights, NodeGenome
from maistro_evolve.types import PipelineGenome as RealGenome

pytestmark = pytest.mark.contract("behavioral")

_WS = "workspace-evolve-1064"
_ACTOR = "evolve-user"
_BENCHMARK = "proxy"


class _ProcessKilled(BaseException):
    """A BaseException no executor boundary absorbs: the process died here."""


class _KillingDomainStore:
    """Delegates everything, then kills the process at one named journal seam.

    The kill lands AFTER the durable row committed but BEFORE the in-memory
    tournament applied it and before the Attempt could terminalize — the
    exact crash window the recovery contract is about. Targeted by insert
    ordinal: the second logical battle's journal commit.
    """

    def __init__(self, inner: Any, *, kill_after_inserts: int) -> None:
        self._inner = inner
        self._kill_after = kill_after_inserts
        self._inserts = 0
        self.killed_node_run_id: str | None = None

    @property
    def backend(self) -> str:
        return self._inner.backend

    def __getattr__(self, item: str) -> Any:
        return getattr(self._inner, item)

    async def record_battle_publication(self, workspace_id: str, publication: Any) -> bool:
        inserted = await self._inner.record_battle_publication(workspace_id, publication)
        if inserted:
            self._inserts += 1
            if self._inserts >= self._kill_after:
                self.killed_node_run_id = publication.node_run_id
                raise _ProcessKilled(
                    f"process died after journaling {publication.node_run_id}/{publication.benchmark}"
                )
        return inserted


def _genome(genome_id: str, score: float) -> RealGenome:
    genome = RealGenome(
        id=genome_id,
        name=genome_id,
        topology=DAGTopology(
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
        eval_weights=EvalWeights(),
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    genome.eval_scores = {_BENCHMARK: score}
    # Pre-scored AND pre-fitnessed, so the canonical graph is
    # plan-pairs → battles → finalize and the eval harness never fires: the
    # replay contract under test lives entirely downstream of evaluation.
    genome.fitness_score = score
    return genome


def _seed_population() -> Any:
    from maistro_evolve.population import PopulationStore

    population = PopulationStore()
    for genome_id, score in (("g1", 0.9), ("g2", 0.2), ("g3", 0.8), ("g4", 0.3)):
        population.add(_genome(genome_id, score))
    return population


class _ReplayCycle:
    """Deterministic cycle double over the REAL domain stores.

    All genomes arrive pre-scored, so the canonical graph is
    plan-pairs → battles → finalize and the harness/llm seams never fire.
    Finalize computes fitness, breeds one child from g1xg2, and advances the
    cycle counter — real PopulationStore mutations whose durability the
    committed snapshot must capture.
    """

    fidelity = "proxy"

    def __init__(self, harness: Any = None, tournament: Any = None, archive: Any = None) -> None:
        self.harness = harness
        self.tournament = tournament
        self.archive = archive
        self._island_pop: Any = None
        self._cycle_count = 0
        self.finalize_fault: Exception | None = None
        self.at_finalize_population: list[str] | None = None
        self.at_finalize_tournament: dict[str, Any] | None = None
        self._child_bred = False

    @staticmethod
    def _fold_score(genome: Any, benchmark: str, score: float, stub: bool, alpha: float) -> None:
        genome.eval_scores[benchmark] = score

    def _compute_all_fitness(self, population: Any) -> list[Any]:
        if self.finalize_fault is not None:
            raise self.finalize_fault
        if self.at_finalize_population is None:
            # The exact domain state finalize inherited: the comparison point
            # between an uninterrupted cycle and a resumed one.
            self.at_finalize_population = population.export_genomes_snapshot()
            self.at_finalize_tournament = self.tournament.signature()
        for genome in population.list_all():
            genome.fitness_score = sum(genome.eval_scores.values())
        return population.list_all()

    def _breed_island(
        self, island_pop: Any, island_id: int, population: Any, config: Any, cap: int
    ) -> None:
        if self._child_bred:
            return
        self._child_bred = True
        child = _genome("child-1", 0.5)
        child.parent_a_id = "g1"
        child.parent_b_id = "g2"
        population.add(child)

    async def _self_improve_top(self, population: Any, config: Any, llm_call: Any) -> None:
        return None


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        eval_batch_size=4,
        target_benchmarks=[_BENCHMARK],
        eval_ema_alpha=0.5,
        cull_pct=0.0,
        island_count=1,
        population_size=4,
        migration_interval=1000,
    )


class _Spine:
    """One process's canonical spine + Evolve domain, over shared durable files."""

    def __init__(self, tmp_path: Path, workspace: str) -> None:
        self.spine_path = tmp_path / "spine.db"
        self.domain_path = tmp_path / "evolve_domain.db"
        self.workspace = workspace
        self.conn: aiosqlite.Connection | None = None
        self.run_store: Any = None
        self.graph_run_store: Any = None
        self.project_store: Any = None
        self.domain_store: Any = None

    async def start(self) -> _Spine:
        self.spine_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = await aiosqlite.connect(self.spine_path)
        self.project_store = SqliteProjectScopeStore(self.conn)
        await self.project_store.ensure_schema()
        self.run_store = SqliteRunStore(self.conn, project_store=self.project_store)
        await self.run_store.ensure_schema()
        continuations = SqliteGraphContinuationStore(self.conn)
        await continuations.ensure_schema()
        self.graph_run_store = CanonicalDurableRunStore(self.run_store, continuations)
        self.domain_store = SqliteEvolveDomainStore(str(self.domain_path))
        await self.domain_store.ensure_schema()
        return self

    async def close(self) -> None:
        if self.conn is not None:
            await self.conn.close()
            self.conn = None

    def container(self) -> SimpleNamespace:
        return SimpleNamespace(
            config=SimpleNamespace(workspace_id=self.workspace),
            project_scope_store=self.project_store,
            run_store=self.run_store,
            graph_run_store=self.graph_run_store,
        )

    async def node_run_ids(self, run_id: str) -> dict[str, str]:
        node_runs = await self.run_store.list_node_runs(run_id)
        return {item.node_id: item.node_run_id for item in node_runs}


async def _restore_process(spine: _Spine, monkeypatch: pytest.MonkeyPatch) -> Any:
    """A genuinely fresh process: new service object, restored domain only."""
    import services.evolution as evolution_module

    service = evolution_module._EvolutionService.__new__(evolution_module._EvolutionService)
    service._running = True
    service._population = None
    service._tournament = None
    service._cycle_count = 0
    service._last_cycle_error = None
    service._last_run_id = None
    service._last_run_status = None
    service._archive = None
    service._domain_store = spine.domain_store
    service._domain_restore = None
    service._cycle_lock = asyncio.Lock()
    service._execution_available = True
    service._availability = "executable"
    service._availability_reason = None
    monkeypatch.setattr(evolution_module, "get_evolution_service", lambda: service)
    monkeypatch.setattr(evolution_module._EvolutionService, "build_llm_call", lambda self: None)
    monkeypatch.setattr(
        evolution_module._EvolutionService,
        "workspace_id",
        property(lambda self: spine.workspace),
    )

    restored = await service.restore_or_initialize_domain_state()
    assert restored is True
    return service


def _domain_signature(tournament: Any) -> dict[str, Any]:
    """Semantic battle/Elo outcome, excluding legitimately per-run identity.

    Independent logical Runs mint different node_run/attempt ids, so byte
    equality across them would be false economy. Everything the issue asks
    to be identical — battle count, every benchmark outcome (pair, winner,
    scores) and every Elo/win/loss/draw rating — is compared exactly.
    """
    signature = tournament.signature()
    return {
        "battles": [
            {
                key: battle[key]
                for key in (
                    "benchmark",
                    "genome_a_id",
                    "genome_b_id",
                    "winner_id",
                    "score_a",
                    "score_b",
                )
            }
            for battle in signature["battles"]
        ],
        "ratings": signature["ratings"],
    }


@pytest.fixture
def compressed_leases(monkeypatch: pytest.MonkeyPatch) -> None:
    """Compress the execution-lease clock instead of sleeping out the TTL.

    The attempt lease check deliberately reads the real wall clock (a live
    lease is live regardless of a simulated tick), so the test compresses
    ``GRAPH_ATTEMPT_LEASE_TTL`` to zero: the killed walker's Attempt lease is
    born expired, which is exactly the state a real restart meets after the
    30-second TTL has elapsed.
    """
    from maistro.graph.durable_runs import attempt_executor

    monkeypatch.setattr(attempt_executor, "GRAPH_ATTEMPT_LEASE_TTL", timedelta(milliseconds=1))


@pytest.fixture
def cycle_double(monkeypatch: pytest.MonkeyPatch) -> _ReplayCycle:
    double = _ReplayCycle()

    def _factory(**kwargs: Any) -> _ReplayCycle:
        # Every construction (reference run, crashed run, and the recovery
        # resolver's rebuild) binds the caller's collaborators onto one shared
        # deterministic double, so finalize behavior is identical everywhere.
        double.harness = kwargs.get("harness")
        double.tournament = kwargs.get("tournament")
        double.archive = kwargs.get("archive")
        # Each construction models a genuinely new process's cycle object, so
        # the per-process volatile state resets here (#1064): a restarted
        # process has no memory that a previous process already bred a child
        # or advanced a counter. The deterministic BREED BEHAVIOR stays
        # identical everywhere — only the one-shot latch is volatile.
        # ``finalize_fault`` is deliberately not reset: it is the test's
        # injected fault, not process state.
        double._child_bred = False
        double._cycle_count = 0
        double.at_finalize_population = None
        double.at_finalize_tournament = None
        return double

    monkeypatch.setattr(cycle_module, "EvolutionCycle", _factory)
    return double


async def _run_uninterrupted_reference(tmp_path: Path) -> tuple[_Spine, Any, str]:
    """A full healthy cycle on independent durable files: the parity reference."""
    spine = await _Spine(tmp_path / "reference", _WS).start()
    await spine.project_store.create_root(_WS)
    population = _seed_population()
    from maistro_evolve.tournament import EloTournament

    tournament = EloTournament()
    record = await run_canonical_evolution_cycle(
        population=population,
        tournament=tournament,
        config=_config(),
        harness=SimpleNamespace(fidelity="proxy"),
        llm_call=None,
        actor_principal_id=_ACTOR,
        cycle_number=1,
        container=spine.container(),
        domain_store=spine.domain_store,
    )
    assert record.run.status is RunStatus.COMPLETED
    return spine, {"population": population, "tournament": tournament}, record.run_id


@pytest.mark.asyncio
async def test_process_death_between_journal_and_attempt_resumes_exactly_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cycle_double: _ReplayCycle,
    compressed_leases: None,
) -> None:
    """Kill mid-battle after the durable row committed; recover on a fresh process."""
    reference_spine, reference, _ = await _run_uninterrupted_reference(tmp_path / "ref")

    spine = await _Spine(tmp_path / "crash", _WS).start()
    await spine.project_store.create_root(_WS)
    population = _seed_population()
    from maistro_evolve.tournament import EloTournament

    tournament = EloTournament()
    killing_store = _KillingDomainStore(spine.domain_store, kill_after_inserts=2)

    with pytest.raises(_ProcessKilled):
        await run_canonical_evolution_cycle(
            population=population,
            tournament=tournament,
            config=_config(),
            harness=SimpleNamespace(fidelity="proxy"),
            llm_call=None,
            actor_principal_id=_ACTOR,
            cycle_number=1,
            container=spine.container(),
            domain_store=killing_store,
        )
    await spine.close()

    # The killed walker durably committed BOTH battle rows before dying:
    # battle-1 published fully, battle-2 committed its row and lost the
    # process before its in-memory apply and Attempt terminal.
    journaled = await spine.domain_store.list_battle_publications(_WS)
    assert len(journaled) == 2
    killed_node_run_id = killing_store.killed_node_run_id
    assert killed_node_run_id is not None
    assert {p.node_run_id for p in journaled} == {
        journaled[0].node_run_id,
        killed_node_run_id,
    }

    # --- the restarted process: nothing shared but the durable files -------
    recovered_spine = await _Spine(tmp_path / "crash", _WS).start()
    service = await _restore_process(recovered_spine, monkeypatch)
    # The restore rebuilt the tournament by replaying the journal — including
    # the row the dying process never applied in memory.
    restored_tournament = service.tournament
    assert restored_tournament.get_stats()["total_battles"] == 2
    restored_population = service.population
    assert sorted(g.id for g in restored_population.list_all()) == ["g1", "g2", "g3", "g4"]

    run_id = journaled[0].run_id
    # The shipped due tick, with the tick's own clock past every elapsed
    # wait: the RUNNING sweep re-queues the walker's lost frontier, then the
    # due scan resumes the Run through canonical Attempt recovery (the dead
    # battle-2 Attempt's lease, compressed to zero by the fixture, is the
    # reclaim path — the same mechanics a restarted process meets).
    resumed = await resume_due_graph_runs(
        store=recovered_spine.graph_run_store,
        run_store=recovered_spine.run_store,
        node_resolver_factory=_recovery_resolver,
        eligible=_admitted_by_evolve,
        limit=5,
        now=datetime.now(UTC) + timedelta(hours=2),
    )
    assert resumed == 1

    run = await recovered_spine.run_store.get_run(run_id)
    assert run is not None
    assert run.status is RunStatus.COMPLETED

    # Exactly-once: the journal still holds exactly two logical battles, and
    # the recovered tournament applied each of them exactly once.
    journal_after = await recovered_spine.domain_store.list_battle_publications(_WS)
    assert len(journal_after) == 2
    assert {p.node_run_id for p in journal_after} == {p.node_run_id for p in journaled}
    assert restored_tournament.get_stats()["total_battles"] == 2
    assert _domain_signature(restored_tournament) == _domain_signature(reference["tournament"])
    # The committed finalize produced the same post-cycle population the
    # uninterrupted reference produced.
    recovered_ids = sorted(g.id for g in restored_population.list_all())
    reference_ids = sorted(g.id for g in reference["population"].list_all())
    assert recovered_ids == reference_ids
    recovered_fitness = {g.id: g.fitness_score for g in restored_population.list_all()}
    reference_fitness = {g.id: g.fitness_score for g in reference["population"].list_all()}
    assert recovered_fitness == reference_fitness

    # A fresh logical cycle is never suppressed by recovered keys: a new
    # NodeRun pairing the same genomes publishes a NEW battle.
    from services.evolution_graph import _BattleInput, _TournamentWork

    work = _TournamentWork(
        cycle=service._population and _ReplayCycle(tournament=restored_tournament),
        population=restored_population,
        membership_ids=tuple(sorted(g.id for g in restored_population.list_all())),
        battle_slots=1,
        domain_store=recovered_spine.domain_store,
        workspace_id=_WS,
    )
    fresh_ctx = NodeContext(
        run_id="run-fresh",
        dag_id="dag-fresh",
        node_id="evolve-battle-1",
        node_run_id="evolve-battle-fresh",
        attempt_id="at-fresh",
        workspace_id=_WS,
    )
    pair = next((a, b) for a, b in (("g1", "g3"),))
    output = await work.run_pair_durable(_BattleInput(pairs=[pair], pair_index=0), fresh_ctx)
    assert output.benchmarks == [_BENCHMARK]
    journal_fresh = await recovered_spine.domain_store.list_battle_publications(_WS)
    assert len(journal_fresh) == 3
    assert restored_tournament.get_stats()["total_battles"] == 3
    await recovered_spine.close()
    await reference_spine.close()


@pytest.mark.asyncio
async def test_committed_finalize_is_idempotent_across_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cycle_double: _ReplayCycle
) -> None:
    """A committed finalize survives restart as committed evidence, not new work."""
    spine = await _Spine(tmp_path, _WS).start()
    await spine.project_store.create_root(_WS)
    population = _seed_population()
    from maistro_evolve.tournament import EloTournament

    tournament = EloTournament()
    record = await run_canonical_evolution_cycle(
        population=population,
        tournament=tournament,
        config=_config(),
        harness=SimpleNamespace(fidelity="proxy"),
        llm_call=None,
        actor_principal_id=_ACTOR,
        cycle_number=1,
        container=spine.container(),
        domain_store=spine.domain_store,
    )
    assert record.run.status is RunStatus.COMPLETED
    finalize_node_run_id = (await spine.node_run_ids(record.run_id))["evolve-finalize"]
    final_tournament = tournament.signature()
    final_population = population.export_genomes_snapshot()
    final_marker = await spine.domain_store.get_finalize_marker(_WS, finalize_node_run_id)
    assert final_marker is not None
    assert final_marker.payload["status"] == "committed"

    # Restart: the committed snapshot restores the post-cycle domain.
    restarted = await _Spine(tmp_path, _WS).start()
    service = await _restore_process(restarted, monkeypatch)
    assert service._domain_restore is not None
    assert service._domain_restore["kind"] == "committed"
    assert sorted(g.id for g in service.population.list_all()) == sorted(
        g.id for g in population.list_all()
    )

    ctx = NodeContext(
        run_id=record.run_id,
        dag_id="dag",
        node_id="evolve-finalize",
        node_run_id=finalize_node_run_id,
        attempt_id="at-recovered-finalize",
        workspace_id=_WS,
    )
    before_population = service.population.export_genomes_snapshot()
    before_tournament = service.tournament.signature()
    # Byte-identical restore (#1064): the restarted process rebuilt the exact
    # post-cycle population the committing process held, from the durable
    # snapshot — not an approximation of it.
    assert before_population == final_population
    output = await _finalize_cycle(
        _ReplayCycle(tournament=service.tournament),
        service.population,
        _config(),
        None,
        ctx,
        domain_store=restarted.domain_store,
        workspace_id=_WS,
    )
    # The same committed output returns, and nothing re-mutates: no second
    # cull, no second child, no second cycle advance.
    assert output.population_size == len(before_population)
    assert service.population.export_genomes_snapshot() == before_population
    assert service.tournament.signature() == before_tournament
    assert service.tournament.signature() == final_tournament
    assert (
        await restarted.domain_store.get_finalize_marker(_WS, finalize_node_run_id) == final_marker
        or (await restarted.domain_store.get_finalize_marker(_WS, finalize_node_run_id)).payload
        == final_marker.payload
    )
    await spine.close()
    await restarted.close()


@pytest.mark.asyncio
async def test_faulted_finalize_fails_closed_across_restart_with_compensated_domain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cycle_double: _ReplayCycle
) -> None:
    """A finalize that died mid-mutation is refused on recovery, never re-applied."""
    spine = await _Spine(tmp_path, _WS).start()
    await spine.project_store.create_root(_WS)
    population = _seed_population()
    admission_population = population.export_genomes_snapshot()
    from maistro_evolve.tournament import EloTournament

    tournament = EloTournament()
    cycle_double.finalize_fault = RuntimeError("synthetic finalize death")
    record = await run_canonical_evolution_cycle(
        population=population,
        tournament=tournament,
        config=_config(),
        harness=SimpleNamespace(fidelity="proxy"),
        llm_call=None,
        actor_principal_id=_ACTOR,
        cycle_number=1,
        container=spine.container(),
        domain_store=spine.domain_store,
    )
    assert record.run.status is RunStatus.FAILED
    finalize_node_run_id = (await spine.node_run_ids(record.run_id))["evolve-finalize"]
    faulted = await spine.domain_store.get_finalize_marker(_WS, finalize_node_run_id)
    assert faulted is not None
    assert faulted.payload["status"] == "faulted"
    # No committed snapshot exists: the latest durable snapshot is admission.
    latest = await spine.domain_store.latest_snapshot(_WS)
    assert latest is not None
    assert latest.kind == "admission"
    await spine.close()

    restarted = await _Spine(tmp_path, _WS).start()
    service = await _restore_process(restarted, monkeypatch)
    # The restored domain is the compensated pre-cycle state: the admission
    # snapshot — no partial cull/breed/mutation silently carried forward.
    assert sorted(g.id for g in service.population.list_all()) == [
        "g1",
        "g2",
        "g3",
        "g4",
    ]
    assert service.population.export_genomes_snapshot() == admission_population
    # Battles that durably committed before the fault are still exactly there.
    assert service.tournament.get_stats()["total_battles"] == 2
    # The faulted marker survived the restart, so recovery refuses the same
    # logical finalize instead of silently re-mutating.
    ctx = NodeContext(
        run_id=record.run_id,
        dag_id="dag",
        node_id="evolve-finalize",
        node_run_id=finalize_node_run_id,
        attempt_id="at-recovery",
        workspace_id=_WS,
    )
    with pytest.raises(FinalizeReconciliationRequired, match="faulted"):
        await _finalize_cycle(
            _ReplayCycle(tournament=service.tournament),
            service.population,
            _config(),
            None,
            ctx,
            domain_store=restarted.domain_store,
            workspace_id=_WS,
        )
    # The refusal mutated nothing.
    assert service.population.export_genomes_snapshot() == admission_population
    await spine.close()
    await restarted.close()


@pytest.fixture(params=["memory", "sqlite", "postgres"])
async def battle_receipt_store(request: pytest.FixtureRequest, tmp_path: Path):
    """Real stores, with a private Workspace for each losing-replica scenario."""
    from services.evolve_domain_store import InMemoryEvolveDomainStore, PgEvolveDomainStore

    workspace = f"evolve-battle-receipt-{uuid.uuid4().hex}"
    pool = None
    if request.param == "memory":
        store = InMemoryEvolveDomainStore()
    elif request.param == "sqlite":
        store = SqliteEvolveDomainStore(str(tmp_path / "receipts.db"))
    else:
        dsn = os.environ.get("MAISTRO_TEST_PG_DSN", "").strip()
        if not dsn:
            pytest.skip("MAISTRO_TEST_PG_DSN is not set")
        import asyncpg

        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
        store = PgEvolveDomainStore(pool)
    try:
        await store.ensure_schema()
        yield store, workspace
    finally:
        if pool is not None:
            await pool.execute(
                "DELETE FROM evolve_domain_publications WHERE workspace_id = $1", workspace
            )
            await pool.close()


def _battle_receipt_work(store: Any, workspace: str) -> Any:
    from services.evolution_graph import _TournamentWork

    from maistro_evolve.tournament import EloTournament

    return _TournamentWork(
        cycle=_ReplayCycle(tournament=EloTournament()),
        population=_seed_population(),
        domain_store=store,
        workspace_id=workspace,
    )


def _battle_receipt_context(workspace: str) -> NodeContext:
    return NodeContext(
        run_id="run-receipt",
        dag_id="dag-receipt",
        node_id="battle",
        node_run_id="nr-receipt",
        attempt_id="at-winner",
        workspace_id=workspace,
    )


@pytest.mark.asyncio
async def test_losing_battle_replica_uses_committed_scores_and_attempt(
    battle_receipt_store,
) -> None:
    """The durable winner, not a stale worker's inputs, determines Elo and provenance."""
    from services.evolution_graph import _BattleInput

    store, workspace = battle_receipt_store
    winner = _battle_receipt_work(store, workspace)
    ctx = _battle_receipt_context(workspace)
    inputs = _BattleInput(pairs=[("g1", "g2")])
    await winner.run_pair_durable(inputs, ctx)
    receipt = await store.find_battle_publication(workspace, ctx.node_run_id, _BENCHMARK)

    loser = _battle_receipt_work(store, workspace)
    # Same frozen membership, different volatile scores: exactly the case
    # the membership-only recovery guard cannot detect.
    loser._population.get("g1").eval_scores[_BENCHMARK] = 0.1
    loser._population.get("g2").eval_scores[_BENCHMARK] = 0.99
    retry_ctx = ctx.model_copy(update={"attempt_id": "at-loser"})
    for _ in range(2):
        await loser.run_pair_durable(inputs, retry_ctx)
        assert loser._cycle.tournament.signature() == winner._cycle.tournament.signature()
        battle = loser._cycle.tournament.find_published_battle(ctx.node_run_id, _BENCHMARK)
        assert battle.attempt_id == "at-winner"
    assert await store.find_battle_publication(workspace, ctx.node_run_id, _BENCHMARK) == receipt
    assert len(await store.list_battle_publications(workspace)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["run", "pair"])
@pytest.mark.parametrize("already_mirrored", [False, True])
async def test_incompatible_battle_receipt_refuses_before_local_mutation(
    battle_receipt_store, mismatch: str, already_mirrored: bool
) -> None:
    """A reused NodeRun must never silently authorize a different Run or pair."""
    from services.evolution_graph import EvolveRecoveryBlocked, _BattleInput

    store, workspace = battle_receipt_store
    winner = _battle_receipt_work(store, workspace)
    ctx = _battle_receipt_context(workspace)
    inputs = _BattleInput(pairs=[("g1", "g2")])
    await winner.run_pair_durable(inputs, ctx)
    loser = _battle_receipt_work(store, workspace)
    if already_mirrored:
        await loser.run_pair_durable(inputs, ctx)
    before = loser._cycle.tournament.signature()
    receipt = await store.find_battle_publication(workspace, ctx.node_run_id, _BENCHMARK)
    retry_ctx = ctx.model_copy(update={"attempt_id": "at-loser"})
    if mismatch == "run":
        retry_ctx = retry_ctx.model_copy(update={"run_id": "run-incompatible"})
    else:
        inputs = _BattleInput(pairs=[("g1", "g3")])
    with pytest.raises(EvolveRecoveryBlocked, match=r"battle publication.*incompatible"):
        await loser.run_pair_durable(inputs, retry_ctx)
    assert loser._cycle.tournament.signature() == before
    assert await store.find_battle_publication(workspace, ctx.node_run_id, _BENCHMARK) == receipt
    assert len(await store.list_battle_publications(workspace)) == 1
