"""Restart/recovery proof for canonical Evolve Runs (#1064).

Before this module's production code existed, a process lost after admitting
an Evolve Run (``run_canonical_evolution_cycle``) left it QUEUED or RUNNING
forever -- nothing in this app ever looked at it again. These tests prove:

1. ``_recovery_resolver`` reconstructs a working node resolver purely from
   durable Run facts when this process still holds the exact population the
   Run was admitted against.
2. It fails closed with ``EvolveRecoveryBlocked`` -- never a silent resume
   against fabricated domain state, never an indefinite hang -- whenever the
   domain prerequisites are not available in this process.
3. ``recover_stranded_evolution_runs``/``wake_due_evolution_runs`` wire that
   resolver through the shared canonical recovery seam end to end: a
   recoverable Run reaches COMPLETED. A QUEUED Run this process cannot
   honestly resume is isolated as a candidate-local failure and left QUEUED
   for a later tick (the same documented contract the legacy DAG adapter's
   own resolver failures get) rather than being resumed against the wrong
   population or falsely reported complete -- never silently, always logged.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from maistro.graph.durable_runs import CanonicalDurableRunStore, InMemoryGraphContinuationStore
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import RunStatus
from maistro.runs.store import InMemoryRunStore

pytestmark = pytest.mark.contract("behavioral")


def _real_genome(genome_id: str, score: float) -> Any:
    """A minimal but real ``PipelineGenome`` -- valid enough for the real
    ``EvolutionCycle``/``EvolutionConfig`` the recovery resolver reconstructs
    to cull/breed/migrate it for real, unlike the lightweight ``_Genome``
    double below (which only stands in where a node is constructed but never
    executed)."""
    from datetime import UTC, datetime

    from maistro_evolve.types import DAGTopology, EvalWeights, NodeGenome, PipelineGenome

    return PipelineGenome(
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
        fitness_score=score,
        eval_scores={"proxy": score},
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )


def _real_population(scores: dict[str, float]) -> Any:
    from maistro_evolve.population import PopulationStore

    store = PopulationStore()
    for genome_id, score in scores.items():
        store.add(_real_genome(genome_id, score))
    return store


def _bare_service(population: Any, tournament: Any) -> Any:
    """A resolver-level ``_EvolutionService`` double with only ``population``/
    ``tournament`` under test control, bypassing the real ``__init__`` (which
    would need the engine Container mocked before construction). Still needs
    the lock/bookkeeping attributes real recovery now touches (#1064): the
    recovery seam holds ``cycle_lock`` for its whole execution and folds a
    terminal disposition into ``last_run_id``/``last_run_status``/
    ``cycle_count`` via ``record_recovered_run``.
    """
    import asyncio as _asyncio

    import services.evolution as evolution_module

    service = evolution_module._EvolutionService.__new__(evolution_module._EvolutionService)
    service._population = population
    service._tournament = tournament
    service._cycle_lock = _asyncio.Lock()
    service._cycle_count = 0
    service._last_run_id = None
    service._last_run_status = None
    service._last_cycle_error = None
    service._running = True
    service._execution_available = True
    service._availability = "executable"
    service._availability_reason = None
    return service


class _Genome:
    def __init__(self, genome_id: str, score: float = 0.5) -> None:
        self.id = genome_id
        self.eval_scores: dict[str, float] = {"proxy": score}
        self.fitness_score: float | None = score
        self.harness_params: dict[str, Any] = {}
        self.parent_a_id: str | None = None
        self.parent_b_id: str | None = None
        self.updated_at = ""


class _Population:
    def __init__(self, genomes: list[_Genome]) -> None:
        self._items = {genome.id: genome for genome in genomes}
        self._cycle_markers: dict[str, dict[str, Any]] = {}

    def add(self, genome: _Genome) -> None:
        self._items[genome.id] = genome

    def get(self, genome_id: str) -> _Genome | None:
        return self._items.get(genome_id)

    def list_all(self) -> list[_Genome]:
        return list(self._items.values())

    def cull_bottom(self, pct: float) -> int:
        return 0

    def record_cycle_marker(self, marker_id: str, payload: dict[str, Any]) -> None:
        self._cycle_markers[marker_id] = payload

    def get_cycle_marker(self, marker_id: str) -> dict[str, Any] | None:
        return self._cycle_markers.get(marker_id)


async def _container() -> Any:
    project_store = InMemoryProjectScopeStore()
    await project_store.create_root("workspace-evolve")
    run_store = InMemoryRunStore(project_store=project_store)
    continuation = InMemoryGraphContinuationStore()
    return SimpleNamespace(
        config=SimpleNamespace(workspace_id="workspace-evolve"),
        project_scope_store=project_store,
        run_store=run_store,
        graph_run_store=CanonicalDurableRunStore(run_store, continuation),
        # A real Container's `event_bus` is never actually None in
        # production (see `container.py`); recovery dispositions must reach
        # it (#1064). `None` here is a valid `RecoveryEventSink | None` and
        # keeps these tests focused on recovery/finalize behavior rather than
        # event-bus plumbing -- ``test_recovery_forwards_dispositions_to_the_
        # canonical_event_bus`` below exercises a real sink.
        event_bus=None,
    )


async def _admit_stranded_run(
    owner: Any, *, population: Any, membership_ids: list[str], workspace_id: str
):
    """Build a Graph the same way ``run_canonical_evolution_cycle`` does and
    admit it QUEUED, WITHOUT calling ``run_durable_graph`` -- modeling a
    process that died between admission and checkpoint 1."""
    from services.evolution_graph import _ADMISSION_SOURCE, _build_graph, _membership_hash

    config = SimpleNamespace(eval_batch_size=len(membership_ids))
    project = await owner.project_scope_store.root_for_workspace(workspace_id)
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
        "cycle_number": 1,
        "evolve_membership_ids": list(membership_ids),
        "evolve_membership_count": len(membership_ids),
        "evolve_membership_hash": _membership_hash(membership_ids),
        "evolve_battle_capacity": battle_slots,
    }
    return await owner.run_store.create_run(
        graph,
        provenance=provenance,
        initial_status=RunStatus.QUEUED,
    )


# --- _recovery_resolver -----------------------------------------------------


def test_recovery_resolver_blocked_when_evolution_service_not_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.evolution as evolution_module
    from services.evolution_graph import EvolveRecoveryBlocked, _recovery_resolver

    monkeypatch.setattr(evolution_module, "_service", None)
    run = SimpleNamespace(
        run_id="run-1",
        graph=SimpleNamespace(materialize=lambda: SimpleNamespace(metadata={})),
        provenance={"evolve_membership_ids": ["g1", "g2"], "evolve_battle_capacity": 1},
    )

    with pytest.raises(EvolveRecoveryBlocked, match="has not started"):
        _recovery_resolver(run)  # type: ignore[arg-type]


def test_recovery_resolver_blocked_when_domain_state_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.evolution as evolution_module
    from services.evolution_graph import EvolveRecoveryBlocked, _recovery_resolver

    service = evolution_module._EvolutionService.__new__(evolution_module._EvolutionService)
    service._population = None
    service._tournament = None
    monkeypatch.setattr(evolution_module, "get_evolution_service", lambda: service)

    run = SimpleNamespace(
        run_id="run-1",
        graph=SimpleNamespace(materialize=lambda: SimpleNamespace(metadata={})),
        provenance={"evolve_membership_ids": ["g1", "g2"], "evolve_battle_capacity": 1},
    )
    with pytest.raises(EvolveRecoveryBlocked, match="no live population"):
        _recovery_resolver(run)  # type: ignore[arg-type]


def test_recovery_resolver_blocked_when_live_population_does_not_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The current process holds A population, but not the one this Run was
    admitted against -- e.g. a genuinely different replica, or this process
    restarted with fresh (empty) domain state. Never resume against it."""
    import services.evolution as evolution_module
    from services.evolution_graph import EvolveRecoveryBlocked, _recovery_resolver

    import maistro_evolve.tournament as tournament_module

    service = evolution_module._EvolutionService.__new__(evolution_module._EvolutionService)
    service._population = _Population([_Genome("other-1"), _Genome("other-2")])
    service._tournament = tournament_module.EloTournament()
    monkeypatch.setattr(evolution_module, "get_evolution_service", lambda: service)

    run = SimpleNamespace(
        run_id="run-1",
        graph=SimpleNamespace(materialize=lambda: SimpleNamespace(metadata={})),
        provenance={"evolve_membership_ids": ["g1", "g2"], "evolve_battle_capacity": 1},
    )
    with pytest.raises(EvolveRecoveryBlocked, match="not the population this Run"):
        _recovery_resolver(run)  # type: ignore[arg-type]


def test_recovery_resolver_succeeds_when_population_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.evolution as evolution_module
    from services.evolution_graph import _build_graph, _recovery_resolver

    import maistro_evolve.tournament as tournament_module

    population = _Population([_Genome("g1"), _Genome("g2")])
    service = evolution_module._EvolutionService.__new__(evolution_module._EvolutionService)
    service._population = population
    service._tournament = tournament_module.EloTournament()
    monkeypatch.setattr(evolution_module, "get_evolution_service", lambda: service)
    monkeypatch.setattr(evolution_module._EvolutionService, "build_llm_call", lambda self: None)

    graph = _build_graph(
        workspace_id="ws-1",
        project_id="project-1",
        population=population,
        config=SimpleNamespace(eval_batch_size=2),
        membership_ids=["g1", "g2"],
    )
    run = SimpleNamespace(
        run_id="run-1",
        graph=SimpleNamespace(materialize=lambda: graph),
        provenance={"evolve_membership_ids": ["g1", "g2"], "evolve_battle_capacity": 1},
    )

    resolver = _recovery_resolver(run)  # type: ignore[arg-type]
    # These genomes are already scored (see ``_Genome.__init__``), so the
    # frozen graph has no evaluate nodes -- pair-planning is the entry node.
    node = resolver("evolve-plan-pairs", graph)
    assert node.kind == "evolve.plan_tournament_pairs"


def test_recovery_resolver_falls_back_to_graph_metadata_when_provenance_omits_the_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#1065: a Run whose provenance dict never recorded the frozen
    membership/battle-capacity fields (an older Run predating provenance
    freezing, or a rehydrated Run whose provenance lost them) falls back to
    the Graph's own frozen metadata -- set once by ``_build_graph`` at
    admission -- rather than treating the plan as empty."""
    import services.evolution as evolution_module
    import services.evolution_graph as evolution_graph_module
    from services.evolution_graph import _build_graph

    import maistro_evolve.tournament as tournament_module

    population = _Population([_Genome("g1"), _Genome("g2")])
    service = evolution_module._EvolutionService.__new__(evolution_module._EvolutionService)
    service._population = population
    service._tournament = tournament_module.EloTournament()
    monkeypatch.setattr(evolution_module, "get_evolution_service", lambda: service)
    monkeypatch.setattr(evolution_module._EvolutionService, "build_llm_call", lambda self: None)

    graph = _build_graph(
        workspace_id="ws-1",
        project_id="project-1",
        population=population,
        config=SimpleNamespace(eval_batch_size=2),
        membership_ids=["g1", "g2"],
    )
    assert graph.metadata["evolve_membership_ids"] == ["g1", "g2"]
    assert graph.metadata["evolve_battle_capacity"] == 1

    captured: dict[str, Any] = {}

    def _fake_resolver(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return lambda node_id, graph: None

    monkeypatch.setattr(evolution_graph_module, "_resolver", _fake_resolver)

    run = SimpleNamespace(
        run_id="run-1",
        graph=SimpleNamespace(materialize=lambda: graph),
        provenance={},  # neither frozen-plan field was recorded
    )

    evolution_graph_module._recovery_resolver(run)  # type: ignore[arg-type]

    assert captured["membership_ids"] == ["g1", "g2"]
    assert captured["battle_slots"] == 1


def test_recovery_resolver_computes_battle_capacity_when_wholly_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#1065: when neither provenance nor the Graph's own metadata records a
    battle capacity, the resolver falls back to deriving it the same way
    ``_build_graph`` originally did: half the frozen membership."""
    import services.evolution as evolution_module
    import services.evolution_graph as evolution_graph_module

    import maistro_evolve.tournament as tournament_module

    population = _Population([_Genome("g1"), _Genome("g2"), _Genome("g3")])
    service = evolution_module._EvolutionService.__new__(evolution_module._EvolutionService)
    service._population = population
    service._tournament = tournament_module.EloTournament()
    monkeypatch.setattr(evolution_module, "get_evolution_service", lambda: service)
    monkeypatch.setattr(evolution_module._EvolutionService, "build_llm_call", lambda self: None)

    captured: dict[str, Any] = {}

    def _fake_resolver(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return lambda node_id, graph: None

    monkeypatch.setattr(evolution_graph_module, "_resolver", _fake_resolver)

    run = SimpleNamespace(
        run_id="run-1",
        # Membership is present (from provenance), but battle capacity is
        # missing from BOTH provenance and the Graph's own metadata.
        graph=SimpleNamespace(materialize=lambda: SimpleNamespace(metadata={})),
        provenance={"evolve_membership_ids": ["g1", "g2", "g3"]},
    )

    evolution_graph_module._recovery_resolver(run)  # type: ignore[arg-type]

    assert captured["membership_ids"] == ["g1", "g2", "g3"]
    assert captured["battle_slots"] == 1  # len(membership_ids) // 2


# --- end-to-end recovery seam ------------------------------------------------


@pytest.mark.asyncio
async def test_stranded_evolution_run_recovers_to_completion_when_population_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.engine as engine_module
    import services.evolution as evolution_module
    from services.evolution_graph import recover_stranded_evolution_runs

    import maistro_evolve.tournament as tournament_module

    owner = await _container()
    monkeypatch.setattr(
        engine_module,
        "get_engine",
        lambda: SimpleNamespace(agent_port=SimpleNamespace(container=owner)),
    )

    population = _real_population({"g1": 0.5, "g2": 0.7})
    service = _bare_service(population, tournament_module.EloTournament())
    monkeypatch.setattr(evolution_module, "get_evolution_service", lambda: service)
    monkeypatch.setattr(evolution_module._EvolutionService, "build_llm_call", lambda self: None)

    admitted = await _admit_stranded_run(
        owner, population=population, membership_ids=["g1", "g2"], workspace_id="workspace-evolve"
    )
    assert admitted.status is RunStatus.QUEUED

    recovered = await recover_stranded_evolution_runs()
    assert recovered == 1

    stored = await owner.run_store.get_run(admitted.run_id)
    assert stored is not None
    assert stored.status is RunStatus.COMPLETED
    node_runs = await owner.run_store.list_node_runs(admitted.run_id)
    # Both genomes are already scored, so there is nothing to evaluate: the
    # recovered Run goes straight from pair-planning through one battle to
    # finalization, entirely reconstructed from durable Run facts.
    assert [item.node_id for item in node_runs] == [
        "evolve-plan-pairs",
        "evolve-battle-1",
        "evolve-finalize",
    ]
    assert all(item.status is RunStatus.COMPLETED for item in node_runs)
    assert service.tournament.get_stats()["total_battles"] == 1

    # #1064 finding 4: recovery must fold its disposition into the same
    # service-level status a live cycle updates, not just mutate domain
    # state and leave `/evolution/status` stale.
    assert service.cycle_count == 1
    assert service.last_run_id == admitted.run_id
    status = service.status()
    assert status["cycle_count"] == 1
    assert status["last_run_id"] == admitted.run_id
    assert status["last_run_status"] == RunStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_stranded_evolution_run_is_isolated_and_retried_when_population_does_not_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A QUEUED admission this process cannot honestly resume is isolated as
    a candidate-local failure and left QUEUED for a later tick -- the same
    documented, shared contract ``recover_queued_graph_runs`` gives the
    legacy DAG adapter for a resolver failure raised before checkpoint 1
    (``services.canonical_dag_runner._recovery_resolver`` has the identical
    shape). It is critical that this is neither silently reported as
    recovered nor corrupted into a false COMPLETED -- the population
    mismatch must never be resumed against."""
    import services.engine as engine_module
    import services.evolution as evolution_module
    from services.evolution_graph import recover_stranded_evolution_runs

    import maistro_evolve.tournament as tournament_module

    owner = await _container()
    monkeypatch.setattr(
        engine_module,
        "get_engine",
        lambda: SimpleNamespace(agent_port=SimpleNamespace(container=owner)),
    )

    admission_population = _real_population({"g1": 0.5, "g2": 0.7})
    admitted = await _admit_stranded_run(
        owner,
        population=admission_population,
        membership_ids=["g1", "g2"],
        workspace_id="workspace-evolve",
    )
    assert admitted.status is RunStatus.QUEUED

    # This process's live domain state does not hold the genomes the Run was
    # frozen against -- e.g. this process restarted with fresh state.
    service = _bare_service(_real_population({"unrelated": 0.1}), tournament_module.EloTournament())
    monkeypatch.setattr(evolution_module, "get_evolution_service", lambda: service)

    recovered = await recover_stranded_evolution_runs()
    assert recovered == 0

    stored = await owner.run_store.get_run(admitted.run_id)
    assert stored is not None
    # Never resumed against the wrong population, and never falsely reported
    # complete -- it stays exactly as admitted, eligible for a later tick
    # once this process (or another) actually holds a matching population.
    assert stored.status is RunStatus.QUEUED
    assert service.tournament.get_stats()["total_battles"] == 0
    # A QUEUED, un-recovered candidate has nothing new to report: bookkeeping
    # stays untouched rather than falsely advancing (#1064 finding 4).
    assert service.cycle_count == 0
    assert service.last_run_id is None


async def _assert_seam_wired(
    monkeypatch: pytest.MonkeyPatch,
    evolution_graph_module: Any,
    *,
    seam_name: str,
    recovered_fn: Any,
    graph_store: object,
    run_store: object,
    event_bus: object,
) -> None:
    captured: dict = {}

    async def _fake(**kwargs: Any) -> int:
        captured.update(kwargs)
        return 5

    monkeypatch.setattr(evolution_graph_module, seam_name, _fake)
    # No live `_EvolutionService` singleton in this process for this test, so
    # there is nothing to serialize against or reconcile -- exercised
    # separately by the lock/bookkeeping tests below.
    monkeypatch.setattr(evolution_graph_module, "_current_evolution_service", lambda: None)
    assert await recovered_fn(limit=9) == 5
    assert captured["store"] is graph_store
    assert captured["run_store"] is run_store
    assert captured["limit"] == 9
    # (#1064) crash dispositions must reach the canonical Event bus.
    assert captured["events"] is event_bus
    # (#1127) the bounded scan must persist a continuation across ticks
    # rather than restarting from the top every call.
    from maistro.graph.durable_runs import ScanContinuation

    assert isinstance(captured["scan"], ScanContinuation)

    # `node_resolver_factory` is no longer `_recovery_resolver` itself -- it
    # is wrapped so the tick can learn which Runs it attempted (#1064) -- but
    # it must still delegate to `_recovery_resolver` for every candidate.
    seen_runs: list[Any] = []

    def _spy_resolver(run: Any) -> Any:
        seen_runs.append(run)
        return "resolver-sentinel"

    monkeypatch.setattr(evolution_graph_module, "_recovery_resolver", _spy_resolver)
    probe_run = SimpleNamespace(run_id="probe-run-1")
    assert captured["node_resolver_factory"](probe_run) == "resolver-sentinel"
    assert seen_runs == [probe_run]

    owned = SimpleNamespace(provenance={"admission_source": "evolve"})
    foreign = SimpleNamespace(provenance={"admission_source": "some_other_product"})
    assert captured["eligible"](owned) is True
    assert captured["eligible"](foreign) is False


@pytest.mark.asyncio
async def test_recovery_seams_are_wired_to_evolves_own_resolver_and_admission_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wiring proof mirroring ``test_dag_recovery.test_recovery_owns_only_hive_legacy_admissions``:
    both Evolve recovery entrypoints must hand the canonical seam Evolve's
    own ``_recovery_resolver`` (never a generic/foreign one) and must scope
    to Runs this adapter itself admitted (``admission_source == "evolve"``),
    so recovery never touches another product's Run."""
    import services.evolution_graph as evolution_graph_module

    graph_store = object()
    run_store = object()
    event_bus = object()
    owner = SimpleNamespace(graph_run_store=graph_store, run_store=run_store, event_bus=event_bus)
    monkeypatch.setattr(evolution_graph_module, "canonical_execution_owner", lambda: owner)

    await _assert_seam_wired(
        monkeypatch,
        evolution_graph_module,
        seam_name="recover_queued_graph_runs",
        recovered_fn=evolution_graph_module.recover_stranded_evolution_runs,
        graph_store=graph_store,
        run_store=run_store,
        event_bus=event_bus,
    )
    await _assert_seam_wired(
        monkeypatch,
        evolution_graph_module,
        seam_name="resume_due_graph_runs",
        recovered_fn=evolution_graph_module.wake_due_evolution_runs,
        graph_store=graph_store,
        run_store=run_store,
        event_bus=event_bus,
    )


@pytest.mark.asyncio
async def test_recovery_seams_are_a_noop_when_canonical_execution_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recovery must degrade quietly (0 recovered), never raise, when the
    engine/Container is not up -- the same posture ``canonical_execution_owner``
    gives cycle admission itself."""
    import services.evolution_graph as evolution_graph_module

    def _unavailable():
        raise evolution_graph_module.CanonicalExecutionUnavailable("engine not started")

    monkeypatch.setattr(evolution_graph_module, "canonical_execution_owner", _unavailable)
    assert await evolution_graph_module.recover_stranded_evolution_runs() == 0
    assert await evolution_graph_module.wake_due_evolution_runs() == 0


# --- #1064 finding 1: recovery must be serialized with live cycles ----------


@pytest.mark.asyncio
async def test_recovery_cannot_interleave_with_a_live_cycle_holding_the_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A recovery tick must hold the same ``cycle_lock`` a live cycle/seed
    request holds, so it can never execute evaluate/battle/finalize nodes
    while a live cycle is mutating the same population/tournament (#1064)."""
    import services.engine as engine_module
    import services.evolution as evolution_module
    from services.evolution_graph import recover_stranded_evolution_runs

    import maistro_evolve.tournament as tournament_module

    owner = await _container()
    monkeypatch.setattr(
        engine_module,
        "get_engine",
        lambda: SimpleNamespace(agent_port=SimpleNamespace(container=owner)),
    )

    population = _real_population({"g1": 0.5, "g2": 0.7})
    service = _bare_service(population, tournament_module.EloTournament())
    monkeypatch.setattr(evolution_module, "get_evolution_service", lambda: service)
    monkeypatch.setattr(evolution_module._EvolutionService, "build_llm_call", lambda self: None)

    admitted = await _admit_stranded_run(
        owner, population=population, membership_ids=["g1", "g2"], workspace_id="workspace-evolve"
    )
    assert admitted.status is RunStatus.QUEUED

    order: list[str] = []
    may_release = asyncio.Event()
    acquired = asyncio.Event()

    async def _live_cycle_holds_the_lock() -> None:
        async with service.cycle_lock:
            order.append("live_cycle_acquired")
            acquired.set()
            await may_release.wait()
            order.append("live_cycle_released")

    live_task = asyncio.create_task(_live_cycle_holds_the_lock())
    await asyncio.wait_for(acquired.wait(), timeout=1.0)

    recovery_task = asyncio.create_task(recover_stranded_evolution_runs())
    # The recovery task is now contending for the same lock. It must not be
    # able to proceed -- neither finishing nor mutating tournament state --
    # while the "live cycle" above still holds it.
    await asyncio.sleep(0.05)
    assert not recovery_task.done()
    assert order == ["live_cycle_acquired"]
    assert service.tournament.get_stats()["total_battles"] == 0

    may_release.set()
    await live_task
    recovered = await recovery_task

    assert recovered == 1
    # The live holder released before recovery ever got in -- proves ordering,
    # not just eventual completion.
    assert order == ["live_cycle_acquired", "live_cycle_released"]
    assert service.tournament.get_stats()["total_battles"] == 1


# --- #1064 finding 2: recovery must reject a drifted population -------------


@pytest.mark.asyncio
async def test_recovery_is_blocked_when_live_population_gained_genomes_after_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A later seed (or another cycle) that added genomes to the live
    population after this Run's plan was frozen must block recovery instead
    of silently letting recovered finalization cull/breed/self-improve/
    migrate genomes that were never part of this Run's plan (#1064)."""
    import services.engine as engine_module
    import services.evolution as evolution_module
    from services.evolution_graph import EvolveRecoveryBlocked, _recovery_resolver

    import maistro_evolve.tournament as tournament_module

    owner = await _container()
    monkeypatch.setattr(
        engine_module,
        "get_engine",
        lambda: SimpleNamespace(agent_port=SimpleNamespace(container=owner)),
    )

    population = _real_population({"g1": 0.5, "g2": 0.7})
    admitted = await _admit_stranded_run(
        owner, population=population, membership_ids=["g1", "g2"], workspace_id="workspace-evolve"
    )

    # A seed request lands after this Run's plan was frozen but before
    # recovery notices the stranded Run -- exactly the drift the exact-
    # equality check must catch.
    population.add(_real_genome("g3-seeded-after-admission", 0.9))

    service = _bare_service(population, tournament_module.EloTournament())
    monkeypatch.setattr(evolution_module, "get_evolution_service", lambda: service)

    run = await owner.run_store.get_run(admitted.run_id)
    assert run is not None
    with pytest.raises(EvolveRecoveryBlocked, match="outside its"):
        _recovery_resolver(run)


@pytest.mark.asyncio
async def test_recovery_seam_is_a_noop_when_population_gained_genomes_after_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: the seam isolates the drifted candidate rather than
    resuming it -- the Run stays QUEUED, and no domain mutation happens to
    the genome the seed request added."""
    import services.engine as engine_module
    import services.evolution as evolution_module
    from services.evolution_graph import recover_stranded_evolution_runs

    import maistro_evolve.tournament as tournament_module

    owner = await _container()
    monkeypatch.setattr(
        engine_module,
        "get_engine",
        lambda: SimpleNamespace(agent_port=SimpleNamespace(container=owner)),
    )

    population = _real_population({"g1": 0.5, "g2": 0.7})
    admitted = await _admit_stranded_run(
        owner, population=population, membership_ids=["g1", "g2"], workspace_id="workspace-evolve"
    )
    population.add(_real_genome("g3-seeded-after-admission", 0.9))

    service = _bare_service(population, tournament_module.EloTournament())
    monkeypatch.setattr(evolution_module, "get_evolution_service", lambda: service)

    recovered = await recover_stranded_evolution_runs()
    assert recovered == 0

    stored = await owner.run_store.get_run(admitted.run_id)
    assert stored is not None
    assert stored.status is RunStatus.QUEUED
    # The seeded genome was never touched: still exactly as it was seeded,
    # never culled/bred/rated by a recovered finalize it was never part of.
    seeded = population.get("g3-seeded-after-admission")
    assert seeded is not None
    assert seeded.eval_scores == {"proxy": 0.9}


# --- #1064 finding 3: the recovery scan must not restart every tick ---------


@pytest.mark.asyncio
async def test_a_second_recovery_tick_advances_past_previously_unrecoverable_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With a per-store ``ScanContinuation`` held across ticks (mirroring the
    legacy-DAG wrapper, #1127), a tick that cannot recover the earliest
    candidates must not keep reselecting them forever -- it advances past
    them so later, genuinely recoverable Runs are eventually reached, even
    though each call's own scan is bounded."""
    import services.engine as engine_module
    import services.evolution as evolution_module
    from services.evolution_graph import recover_stranded_evolution_runs

    import maistro_evolve.tournament as tournament_module

    owner = await _container()
    monkeypatch.setattr(
        engine_module,
        "get_engine",
        lambda: SimpleNamespace(agent_port=SimpleNamespace(container=owner)),
    )

    # This process's live population never matches the two earlier Runs'
    # frozen plans -- e.g. it restarted with fresh state and only later
    # genomes were re-seeded. Every tick that rescans from the top would keep
    # reselecting these first, starving the later, recoverable Run below.
    unrelated_population = _real_population({"unrelated": 0.1})
    stale_1 = await _admit_stranded_run(
        owner,
        population=_real_population({"a1": 0.5, "a2": 0.6}),
        membership_ids=["a1", "a2"],
        workspace_id="workspace-evolve",
    )
    stale_2 = await _admit_stranded_run(
        owner,
        population=_real_population({"b1": 0.5, "b2": 0.6}),
        membership_ids=["b1", "b2"],
        workspace_id="workspace-evolve",
    )
    recoverable_population = _real_population({"g1": 0.5, "g2": 0.7})
    recoverable = await _admit_stranded_run(
        owner,
        population=recoverable_population,
        membership_ids=["g1", "g2"],
        workspace_id="workspace-evolve",
    )

    service = _bare_service(unrelated_population, tournament_module.EloTournament())
    monkeypatch.setattr(evolution_module, "get_evolution_service", lambda: service)
    monkeypatch.setattr(evolution_module._EvolutionService, "build_llm_call", lambda self: None)

    # Bound each tick's scan to exactly one candidate: without a persisted
    # continuation, every tick would look at `stale_1` again and never reach
    # `recoverable` below.
    first = await recover_stranded_evolution_runs(limit=1)
    assert first == 0
    stored_stale_1 = await owner.run_store.get_run(stale_1.run_id)
    assert stored_stale_1 is not None and stored_stale_1.status is RunStatus.QUEUED

    second = await recover_stranded_evolution_runs(limit=1)
    assert second == 0
    stored_stale_2 = await owner.run_store.get_run(stale_2.run_id)
    assert stored_stale_2 is not None and stored_stale_2.status is RunStatus.QUEUED

    # This process's live population now matches the third Run's plan (a
    # later re-seed) -- the third tick must reach it rather than looping back
    # to `stale_1`/`stale_2`.
    service._population = recoverable_population
    third = await recover_stranded_evolution_runs(limit=1)
    assert third == 1
    stored_recoverable = await owner.run_store.get_run(recoverable.run_id)
    assert stored_recoverable is not None and stored_recoverable.status is RunStatus.COMPLETED
