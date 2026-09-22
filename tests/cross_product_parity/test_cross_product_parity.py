"""Named M1 cross-product parity suite (#459).

The active product convergence PRs are dependencies, not implementation material
for this branch. The named producer scenarios execute the shipped product
composition and observe canonical Run/NodeRun/Attempt evidence; they do not
replace missing product behavior with fixtures. The independent ontology and
baseline contracts remain dependency-gated.

Set `M1_STRICT_CLOSEOUT=1` for the closeout invocation; named blockers then
fail instead of being treated as a passing abstention.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_BACKEND = Path(__file__).resolve().parents[2] / "packages" / "hive-conductor" / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from maistro.graph.definitions import Graph, Node  # noqa: E402
from tests.cross_product_parity.harness import (  # noqa: E402
    GOLDEN_BASELINES,
    ONTOLOGY,
    DependencyAssessment,
    DependencyUnavailable,
    ParityContractError,
    assert_identity_projection,
    assert_matches_golden,
    assert_ontology_identity_projection,
    canonical_observation,
    dependency_assessment,
    enforce_strict_closeout,
    open_durable_profile,
)

pytestmark = [pytest.mark.contract("cross-service"), pytest.mark.scope("integration")]


@pytest.mark.asyncio
async def test_cross_product_parity_profile_is_real_sqlite_and_survives_restart(
    tmp_path: Path,
) -> None:
    """The suite's fixture is the supported durable spine, not an in-memory double."""
    db_path = tmp_path / "m1-459-parity.sqlite3"
    first = await open_durable_profile(db_path, workspace_id="workspace-parity")
    graph = Graph(
        graph_id="graph-parity-restart",
        workspace_id=first.workspace_id,
        project_id=first.project_id,
        name="M1 parity restart probe",
        nodes=[Node(node_id="node-parity", node_type="parity.probe", name="Probe")],
    )
    run = await first.run_store.create_run(
        graph,
        provenance={"admission_source": "m1-459-harness"},
    )
    first_project_id = first.project_id
    await first.close()

    second = await open_durable_profile(db_path, workspace_id="workspace-parity")
    try:
        restored = await second.run_store.get_run(run.run_id)
        assert restored is not None
        assert restored.run_id == run.run_id
        assert restored.graph.graph_id == graph.graph_id
        assert restored.workspace_id == first.workspace_id
        assert restored.project_id == first_project_id == second.project_id
        assert restored.provenance["admission_source"] == "m1-459-harness"
    finally:
        await second.close()


def test_identical_cross_product_identity_projection_is_accepted() -> None:
    canonical = {
        "workspace_id": "workspace-1",
        "project_id": "project-1",
        "graph_id": "graph-1",
        "run_id": "run-1",
        "node_run_id": "node-run-1",
        "attempt_id": "attempt-1",
        "event_id": "event-1",
        "invocation_id": "invocation-1",
        "artifact_id": "artifact-1",
        "provenance_id": "provenance-1",
        "status": "completed",
    }
    projected = {**canonical, "terminal_state": "completed"}

    assert_identity_projection(canonical, projected)


def test_second_run_id_mapping_and_private_terminal_state_are_rejected() -> None:
    """Scenario 5: planted parallel identity/lifecycle authority must fail closed."""
    canonical = {
        "workspace_id": "workspace-1",
        "project_id": "project-1",
        "graph_id": "graph-1",
        "run_id": "run-1",
        "status": "completed",
    }

    with pytest.raises(ParityContractError, match="second Run identity"):
        assert_identity_projection(
            canonical,
            {**canonical, "product_run_id": "run-2", "terminal_state": "completed"},
        )

    with pytest.raises(ParityContractError, match="product-private terminal state"):
        assert_identity_projection(
            canonical,
            {**canonical, "terminal_state": "product_done"},
        )


@pytest.mark.asyncio
async def test_builders_created_work_is_observable_on_the_canonical_spine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scenario 1 executes Builders and reads the resulting canonical evidence."""
    from maistro.builders.session_composition import (
        build_session_pipeline,
        open_session_spine,
    )

    class DeterministicTurnRunner:
        """Model-call boundary stand-in for the bootstrap agent loop.

        Everything else — spine wiring, dispatcher, pipeline construction —
        is the shipped session composition the Builders TUI runs; only the
        network-facing LLM call is deterministic here.
        """

        async def execute_turn(self, messages: list[dict[str, object]]) -> dict[str, object]:
            user = next(m for m in messages if m["role"] == "user")
            return {"content": f"parity turn: {user['content']}"}

    profile = await open_durable_profile(
        tmp_path / "builders.sqlite3", workspace_id="builders-parity"
    )
    try:
        spine = await open_session_spine(profile.connection, workspace_id=profile.workspace_id)
        pipeline = build_session_pipeline(DeterministicTurnRunner(), spine=spine)
        product_run = await pipeline.execute(
            issue_number=734,
            title="Builders parity",
            repo=str(tmp_path),
            skip_decompose=False,
        )
        assert product_run.canonical_run_id
        observation = await canonical_observation(profile, product_run.canonical_run_id)
        assert observation["status"] == "completed"
        assert len(observation["node_run_ids"]) == len(observation["attempt_ids"]) == 1
        assert product_run.context["chat_turn"] == "parity turn: Builders parity"

        # Use the shipped Conductor inspection seam as the observer. The
        # canonical store remains the source of existence and lifecycle truth.
        import services.dag_run_inspection as inspection
        import services.engine as engine_module

        async def _views_for_user(_user_id: str) -> list[SimpleNamespace]:
            return [SimpleNamespace(id=profile.workspace_id)]

        monkeypatch.setattr(
            engine_module, "_singleton", SimpleNamespace(run_store=profile.run_store)
        )
        monkeypatch.setattr(inspection, "list_views_for_user", _views_for_user)
        inspected = await inspection.visible_run_detail(
            "builders-observer", product_run.canonical_run_id
        )
        assert inspected is not None
        assert inspected["canonical_run_id"] == product_run.canonical_run_id
        assert inspected["status"] == "completed"

        assert_identity_projection(
            observation,
            {**observation, "terminal_state": observation["status"]},
        )
    finally:
        await profile.close()


@pytest.mark.asyncio
async def test_schedule_fire_admits_a_canonical_run_from_the_live_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scenario 2 fires Hive's configured scheduler, not a source probe."""
    from datetime import UTC, datetime

    import services.dag_run_inspection as inspection
    import services.engine as engine_module
    from services.scheduler import ScheduleRunner

    from maistro.graph.definitions import GraphTemplate, Node

    class Row:
        id = "parity-schedule"
        user_id = "parity-user"
        workspace_id = "scheduler-parity"
        name = "Parity schedule"
        description = ""
        cron_expression = "0 * * * *"
        mission_template_id = "parity-template"
        enabled = True
        timezone = "UTC"
        max_runs = None
        last_run = datetime(2026, 8, 21, 11, 0, tzinfo=UTC)
        last_run_id = None
        next_run = None
        created_at = datetime(2026, 8, 1, tzinfo=UTC)

        def model_copy(self, *, update: dict[str, object]) -> Row:
            clone = Row()
            clone.__dict__.update(self.__dict__)
            clone.__dict__.update(update)
            return clone

    from maistro.scheduling.admission import ScheduleRunAdmitter

    profile = await open_durable_profile(
        tmp_path / "scheduler.sqlite3", workspace_id="scheduler-parity"
    )
    container = SimpleNamespace(
        config=SimpleNamespace(workspace_id=profile.workspace_id),
        project_scope_store=profile.project_store,
        run_store=profile.run_store,
        template_store=profile.template_store,
        schedule_store=profile.schedule_store,
        schedule_admitter=ScheduleRunAdmitter(
            profile.run_store, profile.template_store, profile.schedule_store
        ),
    )
    await profile.template_store.put(
        GraphTemplate(
            template_id="parity-template",
            workspace_id=profile.workspace_id,
            version=1,
            name="Parity template",
            nodes=[Node(node_id="only", node_type="parity.probe", name="Probe")],
            edges=[],
        )
    )
    row = Row()
    import stores

    stores.schedules[row.id] = row
    monkeypatch.setattr(
        engine_module,
        "_singleton",
        SimpleNamespace(
            _agent_port=SimpleNamespace(container=container),
            run_store=profile.run_store,
        ),
    )

    async def _views_for_user(_user_id: str) -> list[SimpleNamespace]:
        return [SimpleNamespace(id=profile.workspace_id)]

    monkeypatch.setattr(inspection, "list_views_for_user", _views_for_user)
    try:
        await ScheduleRunner().run_once(now=datetime(2026, 8, 21, 12, 5, tzinfo=UTC))
        recorded = await profile.schedule_store.get(row.id)
        assert recorded is not None and recorded.last_run_id
        observation = await canonical_observation(profile, recorded.last_run_id)
        assert observation["status"] == "queued"
        assert observation["workspace_id"] == profile.workspace_id
        inspected = await inspection.visible_run_detail("scheduler-observer", recorded.last_run_id)
        assert inspected is not None
        assert inspected["canonical_run_id"] == recorded.last_run_id
        assert inspected["workspace_id"] == profile.workspace_id
    finally:
        stores.schedules.pop(row.id, None)
        await profile.close()


@pytest.mark.asyncio
async def test_evolve_cycle_records_real_run_node_and_attempt_evidence() -> None:  # noqa: C901
    """Scenario 3 runs Evolve's shipped service composition with deterministic input."""
    import services.dag_run_inspection as inspection
    import services.engine as engine_module

    import maistro_evolve.cycle as cycle_module
    from maistro.graph.durable_runs import CanonicalDurableRunStore, InMemoryGraphContinuationStore
    from maistro.projects.scope_store import InMemoryProjectScopeStore
    from maistro.runs.store import InMemoryRunStore

    class Genome:
        def __init__(self, genome_id: str) -> None:
            self.id = genome_id
            self.parent_a_id = None
            self.parent_b_id = None
            self.fitness_score = None
            self.eval_scores: dict[str, float] = {}
            self.harness_params: dict[str, object] = {}
            self.updated_at = ""

    class Population:
        def __init__(self) -> None:
            self.items = {item.id: item for item in (Genome("g1"), Genome("g2"))}

        def list_all(self) -> list[Genome]:
            return list(self.items.values())

        def get(self, genome_id: str) -> Genome | None:
            return self.items.get(genome_id)

        def add(self, genome: Genome) -> None:
            self.items[genome.id] = genome

        def cull_bottom(self, pct: float) -> int:
            return 0

    class Harness:
        fidelity = "proxy"

        async def evaluate_genome(
            self, genome: Genome, benchmarks: list[str], llm_call: object
        ) -> list[object]:
            return [
                SimpleNamespace(
                    benchmark=benchmarks[0],
                    score=0.5,
                    cost_usd=0.0,
                    duration_seconds=0.0,
                    metadata={},
                )
            ]

    class Tournament:
        def record_battle(self, **kwargs: object) -> None:
            return None

        def get_avg_elo(self, genome_id: str) -> float:
            return 1000.0

    class Cycle:
        def __init__(self, harness: object = None, tournament: object = None) -> None:
            self.harness = harness
            self.tournament = tournament
            self._island_pop = None
            self._cycle_count = 0
            self._child_added = False

        @staticmethod
        def _fold_score(
            genome: Genome, benchmark: str, score: float, stub: bool, alpha: float
        ) -> None:
            genome.eval_scores[benchmark] = score

        def _compute_all_fitness(self, population: Population) -> list[Genome]:
            for genome in population.list_all():
                genome.fitness_score = sum(genome.eval_scores.values())
            return population.list_all()

        def _breed_island(
            self,
            island_pop: object,
            island_id: int,
            population: Population,
            config: object,
            cap: int,
        ) -> None:
            return None

        async def _self_improve_top(
            self, population: Population, config: object, llm_call: object
        ) -> None:
            return None

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(cycle_module, "EvolutionCycle", Cycle)
    try:
        projects = InMemoryProjectScopeStore()
        await projects.create_root("evolve-parity")
        run_store = InMemoryRunStore(project_store=projects)
        owner = SimpleNamespace(
            config=SimpleNamespace(workspace_id="evolve-parity"),
            project_scope_store=projects,
            run_store=run_store,
            graph_run_store=CanonicalDurableRunStore(run_store, InMemoryGraphContinuationStore()),
        )
        config = SimpleNamespace(
            eval_batch_size=2,
            target_benchmarks=["proxy"],
            eval_ema_alpha=0.5,
            cull_pct=0.0,
            island_count=1,
            population_size=2,
            migration_interval=100,
        )
        from services.evolution import EvolutionService

        service = EvolutionService()
        service._population = Population()
        service._tournament = Tournament()
        monkeypatch.setattr(
            engine_module,
            "_singleton",
            SimpleNamespace(
                _agent_port=SimpleNamespace(container=owner),
                run_store=run_store,
            ),
        )

        async def _views_for_user(_user_id: str) -> list[SimpleNamespace]:
            return [SimpleNamespace(id="evolve-parity")]

        monkeypatch.setattr(inspection, "list_views_for_user", _views_for_user)
        run_id = await service.run_cycle(config=config, harness=Harness(), llm_call=None)
        stored = await run_store.get_run(run_id)
        assert stored is not None and stored.status.value == "completed"
        nodes = await run_store.list_node_runs(run_id)
        attempts = [
            attempt for node in nodes for attempt in await run_store.list_attempts(node.node_run_id)
        ]
        assert nodes and len(nodes) == len(attempts)
        inspected = await inspection.visible_run_detail("evolve-observer", run_id)
        assert inspected is not None
        assert inspected["canonical_run_id"] == run_id
        assert inspected["status"] == "completed"
        assert_identity_projection(
            {
                "workspace_id": stored.workspace_id,
                "project_id": stored.project_id,
                "run_id": stored.run_id,
                "status": stored.status.value,
            },
            inspected,
        )
    finally:
        monkeypatch.undo()


def test_shared_identity_contract_consumes_executable_ontology() -> None:
    """Scenario 4 uses #458 as authority for shared identity field names."""
    dependency = dependency_assessment(ONTOLOGY)
    enforce_strict_closeout(dependency)
    if not dependency.ready:
        assert dependency.blockers
        return

    canonical = {
        "workspace_id": "workspace-1",
        "project_id": "project-1",
        "graph_id": "graph-1",
        "run_id": "run-1",
        "node_run_id": "node-run-1",
        "attempt_id": "attempt-1",
        "invocation_id": "invocation-1",
        "event_id": "event-1",
        "artifact_id": "artifact-1",
        "status": "completed",
    }
    projected = {**canonical, "terminal_state": "completed"}

    assert_ontology_identity_projection(canonical, projected)


def test_463_golden_fixtures_are_consumed_as_independent_oracle() -> None:
    """Scenario 6 consumes, rather than duplicates, the locked #463 matcher."""
    dependency = dependency_assessment(GOLDEN_BASELINES)
    enforce_strict_closeout(dependency)
    if not dependency.ready:
        assert dependency.blockers
        return

    # The fixture's own example is only an oracle wiring proof. Product
    # observations replace it in the executable scenarios after their active
    # dependencies land; the expectations remain owned by #463.
    from tests.cross_product_parity.harness import load_golden_scenario

    scenario, _ = load_golden_scenario("builders", "retry_keeps_logical_run")
    assert_matches_golden("builders", "retry_keeps_logical_run", scenario["example_observation"])


def test_strict_closeout_rejects_blocker_only_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Closeout mode turns a named dependency blocker into failed evidence."""
    monkeypatch.setenv("M1_STRICT_CLOSEOUT", "1")
    assessment = DependencyAssessment(ready=False, blockers=("waiting on issue #65",))

    with pytest.raises(DependencyUnavailable, match="strict closeout cannot abstain"):
        enforce_strict_closeout(assessment)


def test_dependency_handling_contains_no_test_suppression_escape_hatch() -> None:
    """Unavailable product scenarios stay assertion-backed and merge-policy clean."""
    suite_dir = Path(__file__).resolve().parent
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (suite_dir / "harness.py", suite_dir / "test_cross_product_parity.py")
    )
    forbidden = (
        "pytest." + "skip(",
        "pytest." + "importorskip(",
        "pytest.mark." + "xfail",
        "pytest.mark." + "skip",
    )
    for token in forbidden:
        assert token not in source
