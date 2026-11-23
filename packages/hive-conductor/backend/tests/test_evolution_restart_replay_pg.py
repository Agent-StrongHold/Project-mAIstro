"""Run-level recovery comparison on PostgreSQL (#1064).

The sqlite restart-replay suite exercises recovery over durable sqlite files.
This suite compares the Run-level choreography over the production spine — a
migrated PostgreSQL database through ``PgProjectScopeStore``/``PgRunStore``/
``PgGraphContinuationStore`` plus the ``PgEvolveDomainStore`` publication
ledger. Each recovery leg closes the interrupted leg's pool and creates a new
one, but remains in the same OS process; this is not evidence for the issue's
close-only distinct-process launch requirement. Skipped unless
``MAISTRO_TEST_PG_DSN`` names a reachable, migrated server, like every other
PG-leg suite in this repo.
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

#: The choreography helpers (seed population, kill seam, restore, signatures)
#: live once, in the sqlite restart-replay suite; this module is their
#: PostgreSQL twin and imports them instead of copying them.
_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

from test_evolution_restart_replay import (  # noqa: E402
    _ACTOR,
    _config,
    _domain_signature,
    _KillingDomainStore,
    _ProcessKilled,
    _ReplayCycle,
    _restore_process,
    _seed_population,
)

pytestmark = pytest.mark.contract("behavioral")

_WS_BASE = "workspace-evolve-1064-pg"


def _pg_dsn() -> str:
    return os.environ.get("MAISTRO_TEST_PG_DSN", "").strip()


class _PgSpine:
    """One process's canonical spine + Evolve domain over the shared PG server.

    Every ``start()`` opens a brand-new asyncpg pool: a restarted process
    shares nothing with its predecessor but PostgreSQL itself.
    """

    def __init__(self, dsn: str, workspace: str) -> None:
        self.dsn = dsn
        self.workspace = workspace
        self.pool: Any = None
        self.run_store: Any = None
        self.graph_run_store: Any = None
        self.project_store: Any = None
        self.domain_store: Any = None

    async def start(self) -> _PgSpine:
        asyncpg = pytest.importorskip("asyncpg")

        from services.evolve_domain_store import PgEvolveDomainStore

        from maistro.graph.durable_runs import CanonicalDurableRunStore
        from maistro.graph.durable_runs.pg_continuation import PgGraphContinuationStore
        from maistro.projects.pg_scope_store import PgProjectScopeStore
        from maistro.runs.pg_store import PgRunStore

        self.pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=4)
        self.project_store = PgProjectScopeStore(self.pool)
        self.run_store = PgRunStore(self.pool, project_store=self.project_store)
        continuations = PgGraphContinuationStore(self.pool)
        self.graph_run_store = CanonicalDurableRunStore(self.run_store, continuations)
        self.domain_store = PgEvolveDomainStore(self.pool)
        await self.domain_store.ensure_schema()
        return self

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    async def purge_domain(self) -> None:
        """Remove exactly this leg's durable domain rows; canonical rows keyed
        by the unique workspace id are inert to every other suite."""
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

    async def node_run_ids(self, run_id: str) -> dict[str, str]:
        node_runs = await self.run_store.list_node_runs(run_id)
        return {item.node_id: item.node_run_id for item in node_runs}


@pytest.fixture
def compressed_leases(monkeypatch: pytest.MonkeyPatch) -> None:
    """The killed walker's Attempt lease is born expired, as a real restart meets."""
    from maistro.graph.durable_runs import attempt_executor

    monkeypatch.setattr(attempt_executor, "GRAPH_ATTEMPT_LEASE_TTL", timedelta(milliseconds=1))


@pytest.fixture
def cycle_double(monkeypatch: pytest.MonkeyPatch) -> _ReplayCycle:
    """The deterministic finalize double, shared by every leg of one test."""
    import maistro_evolve.cycle as cycle_module

    double = _ReplayCycle()

    def _factory(**kwargs: Any) -> _ReplayCycle:
        double.harness = kwargs.get("harness")
        double.tournament = kwargs.get("tournament")
        double.archive = kwargs.get("archive")
        double._child_bred = False
        double._improved = False
        double._cycle_count = 0
        double.at_finalize_population = None
        double.at_finalize_tournament = None
        return double

    monkeypatch.setattr(cycle_module, "EvolutionCycle", _factory)
    return double


async def _start_leg(dsn: str, workspace: str) -> _PgSpine:
    """One fresh-pool process; the workspace root is idempotent across legs."""
    from maistro.projects.scope import ProjectNotFound

    spine = await _PgSpine(dsn, workspace).start()
    try:
        await spine.project_store.root_for_workspace(workspace)
    except ProjectNotFound:
        await spine.project_store.create_root(workspace)
    return spine


@pytest.mark.asyncio
async def test_pg_process_death_between_journal_and_attempt_resumes_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
    cycle_double: _ReplayCycle,
    compressed_leases: None,
) -> None:
    """The sqlite restart-replay headline, replayed over real PostgreSQL.

    The killed process durably committed both battle rows and died before the
    second Attempt terminalized. A restarted process — a fresh asyncpg pool,
    zero shared Python state — restores the domain from the ledger, resumes
    the exact Run through the shipped recovery seam, and lands on the same
    battle/Elo/lineage outcome the uninterrupted reference produced on its
    own fresh pool, with the journal holding exactly one row per logical
    battle.
    """
    dsn = _pg_dsn()
    if not dsn:
        pytest.skip(
            "MAISTRO_TEST_PG_DSN is not set; the Run-level PostgreSQL leg needs a real server"
        )
    # One workspace for every leg: the pair plan is seeded from the logical
    # cycle identity (workspace, cycle number, frozen membership), so the
    # uninterrupted reference and the killed run must share it to be
    # comparable. The legs are strictly sequential, and the reference leg's
    # durable domain rows are purged before the crash leg is admitted, so the
    # restarted process's journal is exactly the crash run's own history.
    workspace = f"{_WS_BASE}-{uuid.uuid4().hex[:10]}"

    from services.evolution_graph import (
        _admitted_by_evolve,
        _recovery_resolver,
        run_canonical_evolution_cycle,
    )

    from maistro.graph.durable_runs import resume_due_graph_runs
    from maistro.runs.model import RunStatus
    from maistro_evolve.tournament import EloTournament

    # -- Leg 1: the uninterrupted reference; one fresh pool, fully closed. ---
    reference_spine = await _start_leg(dsn, workspace)
    try:
        population = _seed_population()
        tournament = EloTournament()
        record = await run_canonical_evolution_cycle(
            population=population,
            tournament=tournament,
            config=_config(),
            harness=SimpleNamespace(fidelity="proxy"),
            llm_call=None,
            actor_principal_id=_ACTOR,
            cycle_number=1,
            container=reference_spine.container(),
            domain_store=reference_spine.domain_store,
        )
        assert record.run.status is RunStatus.COMPLETED
        reference_signature = _domain_signature(tournament)
        reference_ids = sorted(g.id for g in population.list_all())
        reference_fitness = {g.id: g.fitness_score for g in population.list_all()}
        reference_journal = await reference_spine.domain_store.list_battle_publications(
            reference_spine.workspace
        )
    finally:
        await reference_spine.purge_domain()
        await reference_spine.close()

    # -- Leg 2: the killed process; its own fresh pool, lost at the kill. -----
    crash_spine = await _start_leg(dsn, workspace)
    killed_node_run_id: str | None = None
    try:
        population = _seed_population()
        tournament = EloTournament()
        killing_store = _KillingDomainStore(crash_spine.domain_store, kill_after_inserts=2)
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
    finally:
        # The dying process loses every connection before recovery starts.
        await crash_spine.close()

    # -- Leg 3: the restarted process; nothing shared but the server. --------
    recovered_spine = await _start_leg(dsn, workspace)
    try:
        service = await _restore_process(recovered_spine, monkeypatch)
        restored_tournament = service.tournament
        # The restore replayed the journal, including the row the dying
        # process committed but never applied in memory.
        assert restored_tournament.get_stats()["total_battles"] == 2
        journaled = await recovered_spine.domain_store.list_battle_publications(workspace)
        assert len(journaled) == 2
        assert killed_node_run_id in {p.node_run_id for p in journaled}
        run_id = journaled[0].run_id

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

        # Exactly-once across the restart...
        journal_after = await recovered_spine.domain_store.list_battle_publications(workspace)
        assert len(journal_after) == 2
        assert {p.node_run_id for p in journal_after} == {p.node_run_id for p in journaled}
        assert restored_tournament.get_stats()["total_battles"] == 2
        # ...and byte/semantic equality with the uninterrupted reference:
        # every battle outcome and every Elo rating, then the lineage the
        # committed finalize produced.
        assert _domain_signature(restored_tournament) == reference_signature
        assert len(journal_after) == len(reference_journal)
        recovered_ids = sorted(g.id for g in service.population.list_all())
        assert recovered_ids == reference_ids
        recovered_fitness = {g.id: g.fitness_score for g in service.population.list_all()}
        assert recovered_fitness == reference_fitness
    finally:
        await recovered_spine.purge_domain()
        await recovered_spine.close()


@pytest.mark.asyncio
async def test_pg_committed_finalize_is_idempotent_across_restart(
    monkeypatch: pytest.MonkeyPatch,
    cycle_double: _ReplayCycle,
) -> None:
    """A committed finalize marker survives a fresh-connection restart as evidence.

    The restarted process restores the byte-identical post-cycle population
    from the committed PostgreSQL snapshot, replays the same logical finalize
    marker, and re-mutates nothing: no second cull, no second child, no
    second cycle advance — the durable marker, not process memory, decides.
    """
    dsn = _pg_dsn()
    if not dsn:
        pytest.skip(
            "MAISTRO_TEST_PG_DSN is not set; the Run-level PostgreSQL leg needs a real server"
        )

    from services.evolution_graph import NodeContext, _finalize_cycle, run_canonical_evolution_cycle

    from maistro.runs.model import RunStatus
    from maistro_evolve.tournament import EloTournament

    workspace = f"{_WS_BASE}-{uuid.uuid4().hex[:10]}-fin"
    spine = await _start_leg(dsn, workspace)
    record_run_id: str | None = None
    final_tournament: dict[str, Any] | None = None
    final_population: list[Any] | None = None
    finalize_node_run_id: str | None = None
    try:
        population = _seed_population()
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
        record_run_id = record.run_id
        finalize_node_run_id = (await spine.node_run_ids(record.run_id))["evolve-finalize"]
        final_tournament = tournament.signature()
        final_population = population.export_genomes_snapshot()
        marker = await spine.domain_store.get_finalize_marker(workspace, finalize_node_run_id)
        assert marker is not None
        assert marker.payload["status"] == "committed"
    finally:
        await spine.close()
    assert record_run_id is not None
    assert finalize_node_run_id is not None
    assert final_tournament is not None and final_population is not None

    restarted = await _start_leg(dsn, workspace)
    try:
        service = await _restore_process(restarted, monkeypatch)
        assert service._domain_restore is not None
        assert service._domain_restore["kind"] == "committed"
        # Byte-identical restore: the restarted process rebuilt the exact
        # post-cycle population from the durable PostgreSQL snapshot.
        before_population = service.population.export_genomes_snapshot()
        assert before_population == final_population
        before_tournament = service.tournament.signature()
        assert before_tournament == final_tournament

        ctx = NodeContext(
            run_id=record_run_id,
            dag_id="dag",
            node_id="evolve-finalize",
            node_run_id=finalize_node_run_id,
            attempt_id="at-recovered-finalize",
            workspace_id=workspace,
        )
        output = await _finalize_cycle(
            _ReplayCycle(tournament=service.tournament),
            service.population,
            _config(),
            None,
            ctx,
            domain_store=restarted.domain_store,
            workspace_id=workspace,
        )
        # The same committed output returns; nothing re-mutates.
        assert output.population_size == len(before_population)
        assert service.population.export_genomes_snapshot() == before_population
        assert service.tournament.signature() == final_tournament
        reread = await restarted.domain_store.get_finalize_marker(workspace, finalize_node_run_id)
        assert reread is not None
        assert reread.payload["status"] == "committed"
    finally:
        await restarted.purge_domain()
        await restarted.close()


#: The driver executed by the genuinely distinct OS process (#1064). It runs
#: inside a fresh interpreter — no pytest, no shared in-memory state, only the
#: DSN and the workspace/run ids passed on argv — restores the domain from the
#: durable rows, resumes the killed Run through the shipped recovery seam, and
#: prints one JSON result line for the parent to compare against its own
#: in-process reference leg. The attempt lease TTL is compressed here exactly
#: like the parent's ``compressed_leases`` fixture does: the restarted child
#: models a restart that happens after the real 30s lease TTL, without the
#: test sleeping it out.
_CHILD_DRIVER = r"""
import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta

workspace, run_id = sys.argv[1], sys.argv[2]

import maistro.graph.durable_runs.attempt_executor as attempt_executor

attempt_executor.GRAPH_ATTEMPT_LEASE_TTL = timedelta(milliseconds=1)

import test_evolution_restart_replay_pg as pg  # noqa: E402  (inserts the tests dir)


async def main() -> int:
    import pytest

    import maistro_evolve.cycle as cycle_module
    from maistro.graph.durable_runs import resume_due_graph_runs
    from maistro.runs.model import RunStatus
    from services.evolution_graph import _admitted_by_evolve, _recovery_resolver

    # Bind the same deterministic cycle double the parent's ``cycle_double``
    # fixture binds: a child process running the REAL EvolutionCycle would
    # breed real LLM-shaped children and could never match the reference.
    double = pg._ReplayCycle()

    def _factory(**kwargs: object) -> pg._ReplayCycle:
        double.harness = kwargs.get("harness")
        double.tournament = kwargs.get("tournament")
        double.archive = kwargs.get("archive")
        double._child_bred = False
        double._improved = False
        double._cycle_count = 0
        double.at_finalize_population = None
        double.at_finalize_tournament = None
        return double

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(cycle_module, "EvolutionCycle", _factory)

    spine = await pg._start_leg(os.environ["MAISTRO_TEST_PG_DSN"], workspace)
    try:
        service = await pg._restore_process(spine, monkeypatch)
        resumed = await resume_due_graph_runs(
            store=spine.graph_run_store,
            run_store=spine.run_store,
            node_resolver_factory=_recovery_resolver,
            eligible=_admitted_by_evolve,
            limit=5,
            now=datetime.now(UTC) + timedelta(hours=2),
        )
        run = await spine.run_store.get_run(run_id)
        if run is None:
            print(json.dumps({"error": "run not found"}))
            return 3
        print(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "resumed": resumed,
                    "status": str(run.status),
                    "restore_kind": (service.domain_restore or {}).get("kind"),
                    "ids": sorted(g.id for g in service.population.list_all()),
                    "population": service.population.export_genomes_snapshot(),
                    "signature": pg._domain_signature(service.tournament),
                    "battles": len(await spine.domain_store.list_battle_publications(workspace)),
                }
            )
        )
        return 0 if run.status is RunStatus.COMPLETED else 2
    finally:
        await spine.purge_domain()
        await spine.close()


raise SystemExit(asyncio.run(main()))
"""


@pytest.mark.asyncio
async def test_pg_distinct_os_process_recovers_killed_run(
    monkeypatch: pytest.MonkeyPatch,
    cycle_double: _ReplayCycle,
    compressed_leases: None,
) -> None:
    """A genuinely distinct OS process completes the killed Run (#1064).

    Every other restart leg in this lane restarts *within* the pytest OS
    process (fresh pool, fresh stores, fresh service object). This leg is
    the issue's close-only distinct-process launch: the recovery half runs
    in a child interpreter that shares nothing with the parent but the
    PostgreSQL server itself, and must land the killed Run on exactly the
    uninterrupted reference's battle/Elo/lineage outcome.
    """
    import subprocess
    import sys

    import asyncpg

    dsn = _pg_dsn()
    if not dsn:
        pytest.skip(
            "MAISTRO_TEST_PG_DSN is not set; the distinct-process PostgreSQL leg needs a server"
        )
    workspace = f"{_WS_BASE}-subprocess-{uuid.uuid4().hex[:10]}"
    import json

    from services.evolution_graph import run_canonical_evolution_cycle

    from maistro.runs.model import RunStatus
    from maistro_evolve.tournament import EloTournament

    # -- Leg 1: the in-process reference on its own fresh pool. --------------
    reference_spine = await _start_leg(dsn, workspace)
    try:
        population = _seed_population()
        tournament = EloTournament()
        record = await run_canonical_evolution_cycle(
            population=population,
            tournament=tournament,
            config=_config(),
            harness=SimpleNamespace(fidelity="proxy"),
            llm_call=None,
            actor_principal_id=_ACTOR,
            cycle_number=1,
            container=reference_spine.container(),
            domain_store=reference_spine.domain_store,
        )
        assert record.run.status is RunStatus.COMPLETED
        reference_ids = sorted(g.id for g in population.list_all())
        reference_export = population.export_genomes_snapshot()
        reference_signature = _domain_signature(tournament)
    finally:
        await reference_spine.purge_domain()
        await reference_spine.close()

    # -- Leg 2: the killed process (this interpreter), own fresh pool. -------
    crash_spine = await _start_leg(dsn, workspace)
    run_id: str | None = None
    try:
        population = _seed_population()
        tournament = EloTournament()
        killing_store = _KillingDomainStore(crash_spine.domain_store, kill_after_inserts=2)
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
        assert killing_store.killed_node_run_id is not None
        journaled = await crash_spine.domain_store.list_battle_publications(workspace)
        assert len(journaled) == 2
        run_id = journaled[0].run_id
    finally:
        # The crash leg's durable rows MUST survive for the child process;
        # only the dead pool is closed here.
        await crash_spine.close()
    assert run_id is not None

    # -- Leg 3: the distinct OS process. -------------------------------------
    backend_dir = Path(__file__).resolve().parents[1]
    tests_dir = Path(__file__).resolve().parent
    # The workspace packages resolve through pytest's ``pythonpath`` ini, not
    # site-packages, so the child inherits THIS process's fully configured
    # ``sys.path`` (backend dir first, tests dir next, then every entry the
    # running session itself resolved).
    child_pythonpath = os.pathsep.join(
        [str(backend_dir), str(tests_dir)] + [entry for entry in sys.path if entry]
    )
    child_env = {
        **os.environ,
        "MAISTRO_TEST_PG_DSN": dsn,
        "PYTHONPATH": child_pythonpath,
    }
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD_DRIVER, workspace, run_id],
        env=child_env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert proc.returncode == 0, (
        f"child recovery process failed rc={proc.returncode}\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr[-4000:]}"
    )
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    assert result["pid"] != os.getpid(), "the recovery leg must be a distinct OS process"
    assert result["resumed"] == 1
    assert result["restore_kind"] == "admission"
    assert result["status"] == str(RunStatus.COMPLETED)
    assert result["ids"] == reference_ids
    assert result["population"] == reference_export
    assert result["signature"] == reference_signature
    assert result["battles"] == 2

    # The child purged this workspace's durable rows; nothing may outlive it.
    drain_pool = await asyncpg.create_pool(dsn, min_size=1)
    try:
        remaining = await drain_pool.fetchval(
            "SELECT count(*) FROM evolve_domain_snapshots WHERE workspace_id = $1", workspace
        )
        assert remaining == 0
    finally:
        await drain_pool.close()
