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


class _KillBeforeEvaluationJournal:
    """Kills the process before the Nth evaluation receipt can journal (#1064).

    The evaluation-boundary crash window: every evaluation Attempt before the
    kill is durably terminal (its receipt row committed, its NodeRun
    completed), the killed Attempt's harness work is lost with the process.
    Recovery must reconstruct the scored population from the receipts the
    dead process committed — never resume against the unscored admission
    snapshot.
    """

    def __init__(self, inner: Any, *, kill_before_insert: int) -> None:
        self._inner = inner
        self._kill_before = kill_before_insert
        self._seen = 0
        self.killed_node_run_id: str | None = None

    @property
    def backend(self) -> str:
        return self._inner.backend

    def __getattr__(self, item: str) -> Any:
        return getattr(self._inner, item)

    async def record_evaluation_publication(self, workspace_id: str, publication: Any) -> bool:
        self._seen += 1
        if self._seen >= self._kill_before:
            self.killed_node_run_id = publication.node_run_id
            raise _ProcessKilled(
                f"process died before journaling evaluation {publication.node_run_id}"
            )
        return await self._inner.record_evaluation_publication(workspace_id, publication)


class _KillAfterCommittedFinalizeMarker:
    """Kills the process after the committed finalize marker is durable (#1064).

    The worst finalize crash window: ``_publish_finalize_committed`` wrote the
    committed snapshot AND the committed marker, then the process died before
    the finalize Attempt could terminalize. Every canonical row says the
    finalize is unfinished while the durable domain evidence says it is
    committed — recovery must land on the committed marker and complete the
    Run, not refuse the restored (culled/bred) population as foreign drift.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.killed_node_run_id: str | None = None

    @property
    def backend(self) -> str:
        return self._inner.backend

    def __getattr__(self, item: str) -> Any:
        return getattr(self._inner, item)

    async def upsert_finalize_marker(
        self, workspace_id: str, node_run_id: str, payload: dict[str, Any], *, run_id: str
    ) -> None:
        await self._inner.upsert_finalize_marker(workspace_id, node_run_id, payload, run_id=run_id)
        if str(payload.get("status")) == "committed" and self.killed_node_run_id is None:
            self.killed_node_run_id = node_run_id
            raise _ProcessKilled(f"process died after committing finalize {node_run_id}")


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


_EVAL_SCORES = {"g1": 0.9, "g2": 0.2, "g3": 0.8, "g4": 0.3}


class _DeterministicHarness:
    """Proxy harness double: one fixed score per genome, no LLM, no latency wall.

    An uninterrupted run and a kill+resume of the same logical cycle must
    evaluate to the same scores for the parity comparison to mean anything;
    a wall-clock or LLM-derived score would make the equality vacuous.
    """

    fidelity = "proxy"

    async def evaluate_genome(self, genome: Any, benchmarks: Any, llm_call: Any) -> list[Any]:
        return [
            SimpleNamespace(
                benchmark=benchmark,
                score=_EVAL_SCORES[genome.id],
                metadata={"stub": True},
                cost_usd=0.0,
                duration_seconds=0.01,
            )
            for benchmark in benchmarks
        ]


def _seed_unscored_population() -> Any:
    """The admission state a real cycle starts from: members, no scores (#1064)."""
    from maistro_evolve.population import PopulationStore

    population = PopulationStore()
    for genome_id in ("g1", "g2", "g3", "g4"):
        genome = _genome(genome_id, 0.0)
        genome.eval_scores = {}
        genome.fitness_score = None
        population.add(genome)
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
        # Hard process death (BaseException) inside the finalize mutation
        # sequence (#1064): no except-handler runs, so no faulted marker is
        # written — the durable marker stays in_progress, exactly the state a
        # power loss mid-finalize leaves. One-shot: the restarted process's
        # compensated re-run must be able to finish.
        self.finalize_hard_kill = False
        self._hard_kill_fired = False
        self.at_finalize_population: list[str] | None = None
        self.at_finalize_tournament: dict[str, Any] | None = None
        self._child_bred = False

    @staticmethod
    def _fold_score(genome: Any, benchmark: str, score: float, stub: bool, alpha: float) -> None:
        genome.eval_scores[benchmark] = score

    def _compute_all_fitness(self, population: Any) -> list[Any]:
        if self.finalize_hard_kill and not self._hard_kill_fired:
            self._hard_kill_fired = True
            raise _ProcessKilled("process died mid-finalize, before any fault handler")
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

    async def purge_domain(self) -> None:
        """Delete this leg's durable Evolve rows (the PG twin needs the same)."""
        import sqlite3

        conn = sqlite3.connect(self.domain_path)
        try:
            conn.execute("DELETE FROM evolve_domain_publications")
            conn.execute("DELETE FROM evolve_domain_snapshots")
            conn.commit()
        finally:
            conn.close()

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
    service._committed_finalize_runs = set()
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


def _bind_deterministic_harness(monkeypatch: pytest.MonkeyPatch) -> _DeterministicHarness:
    """Make every EvalHarness construction — including the recovery resolver's
    rebuild — produce the deterministic double (#1064).

    ``_recovery_resolver`` imports ``EvalHarness`` from its module at call
    time; patching there covers the resumed evaluations 3-4 that the
    evaluation-boundary test's recovery actually executes.
    """
    import maistro_evolve.harness as harness_module

    harness = _DeterministicHarness()
    monkeypatch.setattr(harness_module, "EvalHarness", lambda **_kwargs: harness)
    return harness


class _PgRestartSpine:
    """One fresh-pool process's canonical spine + Evolve domain over PG (#1064).

    The PostgreSQL twin of ``_Spine``: every ``start()`` opens a brand-new
    asyncpg pool, so restart legs share nothing but the server's durable
    rows — which is what a process restart means.
    """

    def __init__(self, dsn: str, workspace: str) -> None:
        self.dsn = dsn
        self.workspace = workspace
        self.pool: Any = None
        self.project_store: Any = None
        self.run_store: Any = None
        self.graph_run_store: Any = None
        self.domain_store: Any = None

    async def start(self) -> _PgRestartSpine:
        import asyncpg
        from services.evolve_domain_store import PgEvolveDomainStore

        from maistro.graph.durable_runs.pg_continuation import PgGraphContinuationStore
        from maistro.projects.pg_scope_store import PgProjectScopeStore
        from maistro.projects.scope import ProjectNotFound
        from maistro.runs.pg_store import PgRunStore

        self.pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=4)
        self.project_store = PgProjectScopeStore(self.pool)
        self.run_store = PgRunStore(self.pool, project_store=self.project_store)
        continuations = PgGraphContinuationStore(self.pool)
        self.graph_run_store = CanonicalDurableRunStore(self.run_store, continuations)
        self.domain_store = PgEvolveDomainStore(self.pool)
        await self.domain_store.ensure_schema()
        try:
            await self.project_store.root_for_workspace(self.workspace)
        except ProjectNotFound:
            await self.project_store.create_root(self.workspace)
        return self

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    async def purge_domain(self) -> None:
        """Remove exactly this workspace's durable Evolve rows from PG."""
        if self.pool is None:
            return
        await self.pool.execute(
            "DELETE FROM evolve_domain_publications WHERE workspace_id = $1", self.workspace
        )
        await self.pool.execute(
            "DELETE FROM evolve_domain_snapshots WHERE workspace_id = $1", self.workspace
        )

    def container(self) -> SimpleNamespace:
        return SimpleNamespace(
            config=SimpleNamespace(workspace_id=self.workspace),
            project_scope_store=self.project_store,
            run_store=self.run_store,
            graph_run_store=self.graph_run_store,
        )


@pytest.fixture(params=["sqlite", "postgres"])
async def restart_spine_factory(request: pytest.FixtureRequest, tmp_path: Path):
    """Fresh-process spines over one durable domain, sqlite or PostgreSQL (#1064).

    The restart tests' legs must share nothing but the durable store, which
    is what a process restart means: sqlite legs keep that state in tmp_path
    files, PostgreSQL legs in one real server — every leg opens its own
    pool/connection and the dying process's is closed before recovery
    begins. The PG legs skip without ``MAISTRO_TEST_PG_DSN``, like every
    other PG-leg suite, and purge this leg's domain rows on the way out.
    """
    created: list[str] = []

    if request.param == "sqlite":

        async def make(name: str, workspace: str = _WS) -> Any:
            spine = await _Spine(tmp_path / name, workspace).start()
            await spine.project_store.create_root(workspace)
            return spine

    else:
        dsn = os.environ.get("MAISTRO_TEST_PG_DSN", "").strip()
        if not dsn:
            pytest.skip(
                "MAISTRO_TEST_PG_DSN is not set; the PostgreSQL restart leg needs a real server"
            )

        async def make(name: str, workspace: str = _WS) -> Any:
            spine = await _PgRestartSpine(dsn, workspace).start()
            created.append(workspace)
            return spine

    yield make

    if created:
        import asyncpg

        pool = await asyncpg.create_pool(dsn, min_size=1)
        try:
            await pool.execute(
                "DELETE FROM evolve_domain_publications WHERE workspace_id = $1", _WS
            )
            await pool.execute("DELETE FROM evolve_domain_snapshots WHERE workspace_id = $1", _WS)
        finally:
            await pool.close()


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
        # ``finalize_fault`` and ``finalize_hard_kill`` are deliberately not
        # reset: they are the test's injected faults, not process state (the
        # hard kill is latched, so the restarted finalize can finish).
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


@pytest.mark.asyncio
async def test_process_death_after_evaluations_recovers_scored_population(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cycle_double: _ReplayCycle,
    compressed_leases: None,
    restart_spine_factory: Any,
) -> None:
    """A crash between evaluation and battle legs resumes with scored genomes (#1064).

    The evaluation receipts a killed process committed are the durable form of
    its folded scores. A restarted process that restores only the admission
    snapshot holds UNSCORED genomes; without the evaluation journal, recovery
    resumed against them, found no common benchmarks, and "completed" the Run
    with zero battles. This test pins the repaired contract: the restore
    replays the receipts, the resumed Run fights its battles, and the result
    is semantically identical to the uninterrupted reference.

    Every leg admits with the production default ``EvolutionConfig`` — the
    exact config ``_recovery_resolver`` replays a recovered cycle with — so
    the resumed evaluations 3-4 run under the same benchmarks the reference
    did and the parity comparison is apples to apples.
    """
    from maistro_evolve.cycle import EvolutionConfig

    harness = _bind_deterministic_harness(monkeypatch)
    config = EvolutionConfig(self_improve=True, self_improve_top_n=3)
    reference_spine = await restart_spine_factory("reference")
    reference_population = _seed_unscored_population()
    from maistro_evolve.tournament import EloTournament

    reference_tournament = EloTournament()
    reference = await run_canonical_evolution_cycle(
        population=reference_population,
        tournament=reference_tournament,
        config=config,
        harness=harness,
        llm_call=None,
        actor_principal_id=_ACTOR,
        cycle_number=1,
        container=reference_spine.container(),
        domain_store=reference_spine.domain_store,
    )
    assert reference.run.status is RunStatus.COMPLETED
    reference_ids = sorted(g.id for g in reference_population.list_all())
    reference_fitness = {g.id: g.fitness_score for g in reference_population.list_all()}
    reference_eval_pubs = await reference_spine.domain_store.list_evaluation_publications(_WS)
    assert len(reference_eval_pubs) == 4
    reference_signature = _domain_signature(reference_tournament)
    # Legs share one durable domain on PG: the reference's rows are purged
    # before the crash leg is admitted, so the restarted process's journal
    # is exactly the crash run's own history.
    await reference_spine.purge_domain()
    await reference_spine.close()

    # Crash leg: the process dies before evaluation 2's receipt can journal —
    # evaluation 1 is durably terminal, evaluations 3-4 never ran.
    crash_spine = await restart_spine_factory("crash")
    population = _seed_unscored_population()
    tournament = EloTournament()
    killing_store = _KillBeforeEvaluationJournal(crash_spine.domain_store, kill_before_insert=2)
    with pytest.raises(_ProcessKilled):
        await run_canonical_evolution_cycle(
            population=population,
            tournament=tournament,
            config=config,
            harness=_DeterministicHarness(),
            llm_call=None,
            actor_principal_id=_ACTOR,
            cycle_number=1,
            container=crash_spine.container(),
            domain_store=killing_store,
        )
    assert killing_store.killed_node_run_id is not None
    journaled_evals = await crash_spine.domain_store.list_evaluation_publications(_WS)
    assert len(journaled_evals) == 1
    assert journaled_evals[0].node_run_id != killing_store.killed_node_run_id
    assert await crash_spine.domain_store.list_battle_publications(_WS) == []
    await crash_spine.close()

    # Restarted process: the restore replays evaluation 1's receipt, so the
    # population is NOT the unscored admission snapshot.
    recovered_spine = await restart_spine_factory("crash")
    service = await _restore_process(recovered_spine, monkeypatch)
    assert service._domain_restore["replayed_evaluations"] == 1
    restored_g1 = service.population.get("g1")
    assert restored_g1.eval_scores == dict.fromkeys(config.target_benchmarks, _EVAL_SCORES["g1"])
    assert service.population.get("g2").eval_scores == {}
    assert service.tournament.get_stats()["total_battles"] == 0

    resumed = await resume_due_graph_runs(
        store=recovered_spine.graph_run_store,
        run_store=recovered_spine.run_store,
        node_resolver_factory=_recovery_resolver,
        eligible=_admitted_by_evolve,
        limit=5,
        now=datetime.now(UTC) + timedelta(hours=2),
    )
    assert resumed == 1
    run_id = journaled_evals[0].run_id
    run = await recovered_spine.run_store.get_run(run_id)
    assert run is not None and run.status is RunStatus.COMPLETED

    # Exactly-once: four logical evaluations and two logical battles, no
    # matter how the process boundaries split the work.
    eval_pubs = await recovered_spine.domain_store.list_evaluation_publications(_WS)
    assert len(eval_pubs) == 4
    assert len({p.node_run_id for p in eval_pubs}) == 4
    battle_pubs = await recovered_spine.domain_store.list_battle_publications(_WS)
    # One row per (NodeRun, benchmark): the default config fights several
    # benchmarks per pair, so assert on the logical battles, not row count.
    assert len({p.node_run_id for p in battle_pubs}) == 2
    # Byte/semantic equality with the uninterrupted reference: same members,
    # same fitness, same battle outcomes and Elo ratings.
    recovered_ids = sorted(g.id for g in service.population.list_all())
    assert recovered_ids == reference_ids
    recovered_fitness = {g.id: g.fitness_score for g in service.population.list_all()}
    assert recovered_fitness == reference_fitness
    assert _domain_signature(service.tournament) == reference_signature
    await recovered_spine.close()


@pytest.mark.asyncio
async def test_committed_finalize_before_attempt_terminal_completes_across_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cycle_double: _ReplayCycle,
    compressed_leases: None,
    restart_spine_factory: Any,
) -> None:
    """Committed finalize evidence completes the Run; it never refuses (#1064).

    ``_publish_finalize_committed`` writes the committed snapshot and marker
    BEFORE the finalize Attempt can terminalize, so the worst crash window
    leaves committed domain evidence under an unfinished Attempt. The restored
    population IS that Run's committed post-finalize domain — culled members
    missing, bred members extra — and the shipped recovery seam must land on
    the committed marker and complete the Run rather than reject the changed
    membership as foreign drift.
    """
    reference_spine = await restart_spine_factory("reference")
    reference_population = _seed_population()
    from maistro_evolve.tournament import EloTournament

    reference_tournament = EloTournament()
    reference = await run_canonical_evolution_cycle(
        population=reference_population,
        tournament=reference_tournament,
        config=_config(),
        harness=SimpleNamespace(fidelity="proxy"),
        llm_call=None,
        actor_principal_id=_ACTOR,
        cycle_number=1,
        container=reference_spine.container(),
        domain_store=reference_spine.domain_store,
    )
    assert reference.run.status is RunStatus.COMPLETED
    reference_ids = sorted(g.id for g in reference_population.list_all())
    reference_population_export = reference_population.export_genomes_snapshot()
    reference_signature = _domain_signature(reference_tournament)
    # Legs share one durable domain on PG: the reference's rows are purged
    # before the crash leg is admitted, so the restarted process's journal
    # is exactly the crash run's own history.
    await reference_spine.purge_domain()
    await reference_spine.close()

    crash_spine = await restart_spine_factory("crash")
    population = _seed_population()
    tournament = EloTournament()
    killing_store = _KillAfterCommittedFinalizeMarker(crash_spine.domain_store)
    with pytest.raises(_ProcessKilled):
        await run_canonical_evolution_cycle(
            population=population,
            tournament=tournament,
            config=_config(),
            harness=SimpleNamespace(fidelity="proxy"),
            llm_call=None,
            actor_principal_id=_ACTOR,
            cycle_number=1,
            container=crash_spine.container(),
            domain_store=killing_store,
        )
    killed_node_run_id = killing_store.killed_node_run_id
    assert killed_node_run_id is not None
    # The committed evidence is durable...
    marker = await crash_spine.domain_store.get_finalize_marker(_WS, killed_node_run_id)
    assert marker is not None
    assert marker.payload["status"] == "committed"
    committed_snapshot = await crash_spine.domain_store.latest_snapshot(_WS, kind="committed")
    assert committed_snapshot is not None
    journaled = await crash_spine.domain_store.list_battle_publications(_WS)
    assert len(journaled) == 2
    run_id = journaled[0].run_id
    # ...while the finalize Attempt never terminalized: the NodeRun is still
    # non-terminal on the spine, which is why recovery is needed at all.
    node_runs = await crash_spine.run_store.list_node_runs(run_id)
    finalize_status = {
        item.node_id: item.status for item in node_runs if item.node_id == "evolve-finalize"
    }
    assert finalize_status["evolve-finalize"] is not RunStatus.COMPLETED
    await crash_spine.close()

    # Restarted process: restore rebuilds the committed post-finalize
    # population — membership diverged from the frozen plan, legitimately.
    recovered_spine = await restart_spine_factory("crash")
    service = await _restore_process(recovered_spine, monkeypatch)
    assert service._domain_restore is not None
    assert service._domain_restore["kind"] == "committed"
    restored_ids = sorted(g.id for g in service.population.list_all())
    assert restored_ids == reference_ids
    assert run_id in service.committed_finalize_run_ids

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
    assert run is not None and run.status is RunStatus.COMPLETED

    # Idempotent completion: nothing re-mutated, no second cull/breed/battle.
    assert sorted(g.id for g in service.population.list_all()) == reference_ids
    assert service.population.export_genomes_snapshot() == reference_population_export
    assert _domain_signature(service.tournament) == reference_signature
    assert len(await recovered_spine.domain_store.list_battle_publications(_WS)) == 2
    reread = await recovered_spine.domain_store.get_finalize_marker(_WS, killed_node_run_id)
    assert reread is not None
    assert reread.payload == marker.payload
    await recovered_spine.close()


@pytest.mark.asyncio
async def test_hard_kill_mid_finalize_retries_transparently_after_compensated_restore(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cycle_double: _ReplayCycle,
    compressed_leases: None,
    restart_spine_factory: Any,
) -> None:
    """A BaseException mid-finalize resumes transparently after a restore (#1064).

    Process death inside the mutation sequence leaves the durable marker
    in_progress with no fault handler run. The restarted process restores the
    exact pre-finalize domain — the partial mutations died with the old
    process — so the recovered finalize re-applies the sequence over that
    compensated base and lands exactly where the uninterrupted reference
    landed. The same in_progress marker still refuses a caller holding
    partially-mutated live memory: only the restored process retries.
    """
    reference_spine = await restart_spine_factory("reference")
    reference_population = _seed_population()
    from maistro_evolve.tournament import EloTournament

    reference_tournament = EloTournament()
    reference = await run_canonical_evolution_cycle(
        population=reference_population,
        tournament=reference_tournament,
        config=_config(),
        harness=SimpleNamespace(fidelity="proxy"),
        llm_call=None,
        actor_principal_id=_ACTOR,
        cycle_number=1,
        container=reference_spine.container(),
        domain_store=reference_spine.domain_store,
    )
    assert reference.run.status is RunStatus.COMPLETED
    reference_ids = sorted(g.id for g in reference_population.list_all())
    reference_population_export = reference_population.export_genomes_snapshot()
    reference_signature = _domain_signature(reference_tournament)
    # Legs share one durable domain on PG: the reference's rows are purged
    # before the crash leg is admitted, so the restarted process's journal
    # is exactly the crash run's own history.
    await reference_spine.purge_domain()
    await reference_spine.close()

    crash_spine = await restart_spine_factory("crash")
    population = _seed_population()
    tournament = EloTournament()
    cycle_double.finalize_hard_kill = True
    with pytest.raises(_ProcessKilled):
        await run_canonical_evolution_cycle(
            population=population,
            tournament=tournament,
            config=_config(),
            harness=SimpleNamespace(fidelity="proxy"),
            llm_call=None,
            actor_principal_id=_ACTOR,
            cycle_number=1,
            container=crash_spine.container(),
            domain_store=crash_spine.domain_store,
        )
    journaled = await crash_spine.domain_store.list_battle_publications(_WS)
    assert len(journaled) == 2
    run_id = journaled[0].run_id
    node_runs = await crash_spine.run_store.list_node_runs(run_id)
    finalize_node_run_id = next(
        item.node_run_id for item in node_runs if item.node_id == "evolve-finalize"
    )
    # No fault handler ran: the durable marker is in_progress, not faulted.
    marker = await crash_spine.domain_store.get_finalize_marker(_WS, finalize_node_run_id)
    assert marker is not None
    assert marker.payload["status"] == "in_progress"
    # No committed snapshot: the latest durable snapshot is the admission one.
    latest = await crash_spine.domain_store.latest_snapshot(_WS)
    assert latest is not None
    assert latest.kind == "admission"
    await crash_spine.close()

    # Restarted process: the restore is the compensation — the pre-finalize
    # domain, battles replayed, child not yet bred.
    recovered_spine = await restart_spine_factory("crash")
    service = await _restore_process(recovered_spine, monkeypatch)
    assert sorted(g.id for g in service.population.list_all()) == ["g1", "g2", "g3", "g4"]
    assert service.tournament.get_stats()["total_battles"] == 2
    assert service.domain_restore is not None

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
    assert run is not None and run.status is RunStatus.COMPLETED

    # The retried finalize produced exactly the reference outcome: one child,
    # one cycle advance, no doubled mutation.
    assert sorted(g.id for g in service.population.list_all()) == reference_ids
    assert service.population.export_genomes_snapshot() == reference_population_export
    assert _domain_signature(service.tournament) == reference_signature
    committed = await recovered_spine.domain_store.get_finalize_marker(_WS, finalize_node_run_id)
    assert committed is not None
    assert committed.payload["status"] == "committed"
    assert len(await recovered_spine.domain_store.list_battle_publications(_WS)) == 2
    await recovered_spine.close()
