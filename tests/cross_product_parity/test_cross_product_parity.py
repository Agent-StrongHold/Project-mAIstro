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
from typing import ClassVar

import pytest

_BACKEND = Path(__file__).resolve().parents[2] / "packages" / "hive-conductor" / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from maistro.graph.definitions import Graph, Node  # noqa: E402
from tests.cross_product_parity.harness import (  # noqa: E402
    GOLDEN_BASELINES,
    ONTOLOGY,
    REPO_ROOT,
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
async def test_schedule_fire_admits_and_executes_a_canonical_run_from_the_live_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scenario 2 fires Hive's configured scheduler cadence, not a source probe.

    ``ScheduleRunner.run_once`` is the shipped cadence end to end: due
    occurrences are admitted through the Container-owned
    ``ScheduleRunAdmitter``, and the same tick then consumes the admitted Run
    through the Container's canonical consumer
    (``execute_admitted_runs``), because a schedule Run's admission is its
    submission -- no caller holds a receipt that will drive it later (#251).
    The scenario starts the shipped engine composition (the bridge-built
    Container over a durable SQLite spine), seeds one schedule whose template
    names a registered shipped node kind, and requires completed canonical
    Run -> NodeRun -> Attempt evidence: admission without a reachable
    execution consumer is the persisted-but-unreachable defect the M1
    evidence rule rejects, so a QUEUED-only observation fails here.
    """
    from datetime import UTC, datetime

    import services.dag_run_inspection as inspection
    import services.engine as engine_module
    from config import Settings
    from services.agent_materialization import reset_runtime_source
    from services.engine import EngineService
    from services.scheduler import ScheduleRunner

    class Row:
        id = "parity-schedule"
        user_id = "parity-user"
        workspace_id = "default"
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

    db_path = tmp_path / "scheduler.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    engine = EngineService()
    profile = None
    try:
        await engine.start(
            Settings(
                maistro_router_api_key="parity-key",
                maistro_agents_dir=str(REPO_ROOT / "agents"),
            )
        )
        # The configured scheduler reads the engine's own Container; a stub
        # port has no Container, so the cadence would fall back to the
        # standalone path and prove nothing about configured production.
        assert engine.is_configured
        container = engine.agent_port.container

        from maistro.graph.definitions import GraphTemplate, Node

        # A registered shipped node kind: the consumer resolves and executes
        # it through the production node resolver, no fixture node needed.
        await container.template_store.put(
            GraphTemplate(
                template_id="parity-template",
                workspace_id="default",
                version=1,
                name="Parity template",
                nodes=[
                    Node(
                        node_id="only",
                        node_type="transform.alias_keys",
                        parameters={"mapping": {}},
                    )
                ],
                edges=[],
            )
        )
        row = Row()
        import stores

        stores.schedules[row.id] = row
        monkeypatch.setattr(engine_module, "_singleton", engine)

        async def _views_for_user(_user_id: str) -> list[SimpleNamespace]:
            return [SimpleNamespace(id="default")]

        monkeypatch.setattr(inspection, "list_views_for_user", _views_for_user)

        await ScheduleRunner().run_once(now=datetime(2026, 8, 21, 12, 5, tzinfo=UTC))

        recorded = await container.schedule_store.get(row.id)
        assert recorded is not None and recorded.last_run_id
        run_id = recorded.last_run_id

        # Observe through an independent connection on the same durable
        # spine, like every other producer scenario.
        profile = await open_durable_profile(db_path, workspace_id="default")
        observation = await canonical_observation(profile, run_id)
        assert observation["status"] == "completed"
        assert observation["workspace_id"] == "default"
        assert len(observation["node_run_ids"]) == len(observation["attempt_ids"]) == 1

        # The physical evidence: one NodeRun driven to completion by one
        # Attempt the schedule consumer executed and leased.
        from maistro.runs.consumption import SCHEDULE_EXECUTOR_ID

        (node_run,) = await profile.run_store.list_node_runs(run_id)
        assert node_run.status.value == "completed"
        (attempt,) = await profile.run_store.list_attempts(node_run.node_run_id)
        assert attempt.status.value == "completed"
        assert attempt.executor_id == SCHEDULE_EXECUTOR_ID

        # Canonical correlation identity survived the product scheduler.
        run = await profile.run_store.get_run(run_id)
        assert run is not None
        assert run.provenance["admission_source"] == "schedule"
        assert run.provenance["schedule_id"] == row.id
        assert (
            run.provenance["scheduled_for"] == datetime(2026, 8, 21, 12, 0, tzinfo=UTC).isoformat()
        )

        # The Conductor observer resolves the same Run through the canonical
        # store; the projection cannot invent, hide, or re-terminalize it.
        inspected = await inspection.visible_run_detail("scheduler-observer", run_id)
        assert inspected is not None
        assert inspected["canonical_run_id"] == run_id
        assert inspected["workspace_id"] == "default"
        assert inspected["status"] == "completed"
        assert_identity_projection(
            {
                "workspace_id": run.workspace_id,
                "project_id": run.project_id,
                "run_id": run.run_id,
                "status": run.status.value,
            },
            inspected,
        )
    finally:
        import stores

        stores.schedules.pop("parity-schedule", None)
        if profile is not None:
            await profile.close()
        await engine.stop()
        container = getattr(engine.agent_port, "container", None)
        if container is not None:
            await container.aclose()
        # Module seams engine.start() re-pointed at this container's stores.
        reset_runtime_source()
        from services import feedback_service

        from maistro.memory.outcomes import InMemoryOutcomeStore

        feedback_service.set_outcome_store(InMemoryOutcomeStore())


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
        def __init__(self, benchmark_fidelity: str = "proxy") -> None:
            self.fidelity = benchmark_fidelity

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
        from services.evolution import _EvolutionService

        import maistro_evolve.harness as harness_module

        # The shipped service constructs its own proxy harness and config;
        # the deterministic boundary stays the benchmark/algorithm/LLM seam,
        # never the canonical admission and Run/NodeRun/Attempt spine.
        monkeypatch.setattr(harness_module, "EvalHarness", Harness)
        service = _EvolutionService()
        service._population = Population()
        service._tournament = Tournament()
        monkeypatch.setattr(service, "_build_llm_call", lambda: None)
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
        run_id = await service._run_one_cycle()
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


@pytest.mark.asyncio
async def test_hive_ordinary_chat_admits_a_canonical_run_on_the_workspace_roster(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hive's ordinary conversation chat runs on the canonical spine.

    The shipped chat composition is the engine's own door:
    ``EngineService.route_request`` -> ``MaistroCoreBridge`` ->
    ``Container.route_request``, which admits the turn as a canonical Run,
    executes it as a physical Attempt under a NodeRun, and resolves the
    turn's agent from the persistent roster the bridge materialized at boot
    over the shipped ``agents/`` manifests (fail-closed when absent). Only
    the network-facing LLM client is deterministic here; admission,
    execution, agent resolution, and the durable spine are the shipped
    wiring (#53/#1037: ordinary conversation-only chat is canonical Run /
    NodeRun / Attempt evidence, with no second chat execution identity).
    """
    import adapters.maistro_core as maistro_core_module
    import services.dag_run_inspection as inspection
    import services.engine as engine_module
    from config import Settings
    from services.agent_materialization import reset_runtime_source
    from services.engine import EngineService

    class DeterministicChatLLM:
        """Model-call boundary stand-in, mirroring the Builders scenario.

        Records what the composition offered the model so the scenario can
        assert the turn stayed conversation-only (no tool capability was
        advertised or executed).
        """

        calls: ClassVar[list[dict[str, object]]] = []

        def __init__(self, *, base_url: str = "", api_key: str = "", model: str = "") -> None:
            del base_url, api_key  # the network boundary is the replaced half
            self._model = model

        async def complete(
            self, messages: list[dict[str, object]], model: str, **kwargs: object
        ) -> dict[str, object]:
            DeterministicChatLLM.calls.append({"model": model, **kwargs})
            user = next((m for m in messages if m.get("role") == "user"), {})
            content = user.get("content", "") if isinstance(user, dict) else ""
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": f"parity chat: {content}",
                        },
                        "finish_reason": "stop",
                    }
                ]
            }

    monkeypatch.setattr(maistro_core_module, "_HttpOpenAILLMClient", DeterministicChatLLM)
    db_path = tmp_path / "hive-chat.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    engine = EngineService()
    profile = None
    try:
        await engine.start(
            Settings(
                maistro_router_api_key="parity-key",
                maistro_agents_dir=str(REPO_ROOT / "agents"),
            )
        )
        # The bridge, not the degraded stub, must be wired: a missing roster
        # fails closed at boot, and a stub port cannot fake a configured chat.
        assert engine.is_configured
        roster = engine.agent_port.container.agents
        assert roster, "the shipped workspace roster must materialize"

        monkeypatch.setattr(engine_module, "_singleton", engine)

        async def _views_for_user(_user_id: str) -> list[SimpleNamespace]:
            return [SimpleNamespace(id="default")]

        monkeypatch.setattr(inspection, "list_views_for_user", _views_for_user)

        from maistro.runs.chat_admission import CHAT_SOURCE, SESSION_ID_KEY

        DeterministicChatLLM.calls.clear()
        result = await engine.route_request(
            [{"role": "user", "content": "Parity: what does the workspace roster ship?"}],
            session_id="parity-chat-session",
        )

        # The answer names the canonical Run: no second chat execution
        # identity exists for the product to report instead.
        run_id = result.get("run_id")
        assert run_id, "the chat answer must name its canonical Run"

        # Conversation-only containment: exactly one model call, and nothing
        # the model could have executed a tool with.
        assert len(DeterministicChatLLM.calls) == 1
        assert not DeterministicChatLLM.calls[0].get("tools")

        run = await engine.run_store.get_run(run_id)
        assert run is not None
        assert run.status.value == "completed"
        assert run.workspace_id == "default"
        assert run.provenance["admission_source"] == CHAT_SOURCE
        assert run.provenance[SESSION_ID_KEY] == "parity-chat-session"

        node_runs = await engine.run_store.list_node_runs(run_id)
        assert len(node_runs) == 1
        attempts = await engine.run_store.list_attempts(node_runs[0].node_run_id)
        assert len(attempts) == 1
        # The turn resolved the persistent roster agent, and the durable
        # Attempt records the same agent that answered.
        assert result["agent"] in roster
        assert attempts[0].result["agent"] == result["agent"]

        # The Conductor observer resolves the same Run through the canonical
        # store; the projection cannot invent, hide, or re-terminalize it.
        inspected = await inspection.visible_run_detail("hive-observer", run_id)
        assert inspected is not None
        assert inspected["canonical_run_id"] == run_id
        assert inspected["status"] == "completed"
        assert inspected["workspace_id"] == "default"

        # The chat Run is on the shared durable spine, observable through an
        # independent connection like every other producer scenario.
        profile = await open_durable_profile(db_path, workspace_id="default")
        observation = await canonical_observation(profile, run_id)
        assert observation["status"] == "completed"
        assert observation["workspace_id"] == "default"
        assert len(observation["node_run_ids"]) == len(observation["attempt_ids"]) == 1
        assert_identity_projection(observation, {**observation, "terminal_state": "completed"})
    finally:
        if profile is not None:
            await profile.close()
        await engine.stop()
        container = getattr(engine.agent_port, "container", None)
        if container is not None:
            await container.aclose()
        # Module seams engine.start() re-pointed at this container's stores.
        reset_runtime_source()
        from services import feedback_service

        from maistro.memory.outcomes import InMemoryOutcomeStore

        feedback_service.set_outcome_store(InMemoryOutcomeStore())


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
