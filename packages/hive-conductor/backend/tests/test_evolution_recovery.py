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
    service = evolution_module._EvolutionService.__new__(evolution_module._EvolutionService)
    service._population = population
    service._tournament = tournament_module.EloTournament()
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
    service = evolution_module._EvolutionService.__new__(evolution_module._EvolutionService)
    service._population = _real_population({"unrelated": 0.1})
    service._tournament = tournament_module.EloTournament()
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


async def _assert_seam_wired(
    monkeypatch: pytest.MonkeyPatch,
    evolution_graph_module: Any,
    *,
    seam_name: str,
    recovered_fn: Any,
    graph_store: object,
    run_store: object,
) -> None:
    captured: dict = {}

    async def _fake(**kwargs: Any) -> int:
        captured.update(kwargs)
        return 5

    monkeypatch.setattr(evolution_graph_module, seam_name, _fake)
    assert await recovered_fn(limit=9) == 5
    assert captured["store"] is graph_store
    assert captured["run_store"] is run_store
    assert captured["node_resolver_factory"] is evolution_graph_module._recovery_resolver
    assert captured["limit"] == 9

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
    owner = SimpleNamespace(graph_run_store=graph_store, run_store=run_store)
    monkeypatch.setattr(evolution_graph_module, "canonical_execution_owner", lambda: owner)

    await _assert_seam_wired(
        monkeypatch,
        evolution_graph_module,
        seam_name="recover_queued_graph_runs",
        recovered_fn=evolution_graph_module.recover_stranded_evolution_runs,
        graph_store=graph_store,
        run_store=run_store,
    )
    await _assert_seam_wired(
        monkeypatch,
        evolution_graph_module,
        seam_name="resume_due_graph_runs",
        recovered_fn=evolution_graph_module.wake_due_evolution_runs,
        graph_store=graph_store,
        run_store=run_store,
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
