"""Named M1 cross-product parity suite (#459).

The active product convergence PRs are dependencies, not implementation material
for this branch. Source probes remain development diagnostics; strict mode requires
each scenario to return a real producer/spine/observer observation and records a
missing seam as a failure. No missing product behavior is recreated here.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from maistro.graph.definitions import Graph, Node
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID
from tests.cross_product_parity.harness import (
    BUILDERS,
    CONDUCTOR_INSPECTION,
    EVOLVE,
    GOLDEN_BASELINES,
    ONTOLOGY,
    REAL_BUILDERS_CONDUCTOR_SCENARIO,
    REAL_EVOLVE_CONDUCTOR_SCENARIO,
    REAL_GOLDEN_PRODUCT_OBSERVATION,
    REAL_SCHEDULE_CONDUCTOR_SCENARIO,
    SCHEDULER,
    CloseoutFailure,
    Dependency,
    DependencyUnavailable,
    ParityContractError,
    ParityMode,
    ParityScenario,
    ScenarioAbstained,
    ScenarioExecution,
    SourceProbe,
    assert_identity_projection,
    assert_matches_golden,
    assert_ontology_identity_projection,
    dependency_assessment,
    execute_closeout,
    execute_scenario_sync,
    open_durable_profile,
    require_dependencies,
)

pytestmark = [pytest.mark.contract("cross-service"), pytest.mark.scope("integration")]


def _unavailable_real_seam(owner: str) -> ScenarioExecution:
    """Keep missing producer/observer work owned by the product issue."""
    raise ScenarioAbstained(
        f"real {owner} producer -> canonical spine -> Conductor boundary is not shipped; "
        "the parity harness must not recreate it"
    )


def _builders_scenario() -> ScenarioExecution:
    return _unavailable_real_seam("Builders (#49/#1068)")


def _scheduler_scenario() -> ScenarioExecution:
    return _unavailable_real_seam("scheduler (#231)")


def _evolve_scenario() -> ScenarioExecution:
    return _unavailable_real_seam("Evolve (#51/#1064/#1065/#1066)")


def _golden_scenario() -> ScenarioExecution:
    return _unavailable_real_seam("golden observation (#463)")


def _validate_builders_golden(observation: Mapping[str, object]) -> None:
    """Match the independent #463 oracle against the producer's observation."""
    assert_matches_golden("builders", "retry_keeps_logical_run", observation)


BUILDERS_SCENARIO = ParityScenario(
    name="builders-producer-to-conductor",
    dependencies=(BUILDERS, CONDUCTOR_INSPECTION),
    execute=_builders_scenario,
)
SCHEDULER_SCENARIO = ParityScenario(
    name="scheduler-occurrence-to-conductor",
    dependencies=(SCHEDULER, CONDUCTOR_INSPECTION),
    execute=_scheduler_scenario,
)
EVOLVE_SCENARIO = ParityScenario(
    name="evolve-cycle-to-conductor",
    dependencies=(EVOLVE, CONDUCTOR_INSPECTION),
    execute=_evolve_scenario,
)
GOLDEN_SCENARIO = ParityScenario(
    name="golden-real-observation",
    dependencies=(GOLDEN_BASELINES,),
    execute=_golden_scenario,
    validate_observation=_validate_builders_golden,
)


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
        actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
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


def test_builders_created_work_has_public_conductor_inspection_seams() -> None:
    """Scenario 1 activation contract for Builders -> Conductor parity.

    ``REAL_BUILDERS_CONDUCTOR_SCENARIO`` stays an evidenced blocker even once
    ``CONDUCTOR_INSPECTION`` lands: the assertions below only check that the
    import/source seams exist, not that a real Run was created and observed
    through them, so this scenario cannot be trusted as closure evidence until
    that dependency's own marker lands alongside real executable assertions.
    """
    dependency = dependency_assessment(
        BUILDERS, CONDUCTOR_INSPECTION, REAL_BUILDERS_CONDUCTOR_SCENARIO
    )
    if not dependency.ready:
        assert dependency.blockers
        return

    builders_execution = importlib.import_module("maistro.builders.graph_executor")
    executor = builders_execution.CanonicalGraphPipelineExecutor
    assert executor.__name__ == "CanonicalGraphPipelineExecutor"
    route_source = (
        Path(__file__).resolve().parents[2]
        / "packages"
        / "hive-conductor"
        / "backend"
        / "routes"
        / "dag_runs.py"
    ).read_text(encoding="utf-8")
    assert "from services.dag_run_store import get_dag_run_store" not in route_source
    assert "run_store" in route_source


def test_builders_required_scenario_emits_strict_closeout_evidence() -> None:
    """Scenario 1 through the closeout machinery (#1069).

    Development mode records the abstaining scaffold as BLOCKED with its named
    blockers; the strict closeout job turns the same evidence into a FAILED
    machine-readable record and a suite failure, so a source-ready seam can
    never masquerade as an executed producer -> observer scenario.
    """
    evidence = execute_scenario_sync(BUILDERS_SCENARIO)
    if evidence.status == "BLOCKED":
        assert evidence.blockers or evidence.error


def test_schedule_fire_has_canonical_admission_and_shared_inspection_seams() -> None:
    """Scenario 2 activation contract for the live schedule fire path.

    See ``REAL_SCHEDULE_CONDUCTOR_SCENARIO`` in harness.py: source-token checks
    alone do not prove a real schedule occurrence was observed through Conductor.
    """
    dependency = dependency_assessment(
        SCHEDULER, CONDUCTOR_INSPECTION, REAL_SCHEDULE_CONDUCTOR_SCENARIO
    )
    if not dependency.ready:
        assert dependency.blockers
        return

    scheduler_source = (
        Path(__file__).resolve().parents[2]
        / "packages"
        / "hive-conductor"
        / "backend"
        / "services"
        / "scheduler.py"
    ).read_text(encoding="utf-8")
    assert "ScheduleRunAdmitter" in scheduler_source
    assert "_canonical_admitter" in scheduler_source


def test_schedule_required_scenario_emits_strict_closeout_evidence() -> None:
    """Scenario 2 through the closeout machinery (#1069); see scenario 1."""
    evidence = execute_scenario_sync(SCHEDULER_SCENARIO)
    if evidence.status == "BLOCKED":
        assert evidence.blockers or evidence.error


def test_evolve_has_canonical_run_identity_and_shared_inspection_seams() -> None:
    """Scenario 3 activation contract for the shipped Evolve cycle path.

    See ``REAL_EVOLVE_CONDUCTOR_SCENARIO`` in harness.py: source-token checks
    alone do not prove a real Evolve cycle was observed through Conductor.
    """
    dependency = dependency_assessment(EVOLVE, CONDUCTOR_INSPECTION, REAL_EVOLVE_CONDUCTOR_SCENARIO)
    if not dependency.ready:
        assert dependency.blockers
        return

    evolution_source = (
        Path(__file__).resolve().parents[2]
        / "packages"
        / "hive-conductor"
        / "backend"
        / "services"
        / "evolution.py"
    ).read_text(encoding="utf-8")
    assert "run_canonical_evolution_cycle" in evolution_source
    assert "last_run_id" in evolution_source


def test_evolve_required_scenario_emits_strict_closeout_evidence() -> None:
    """Scenario 3 through the closeout machinery (#1069); see scenario 1."""
    evidence = execute_scenario_sync(EVOLVE_SCENARIO)
    if evidence.status == "BLOCKED":
        assert evidence.blockers or evidence.error


def test_shared_identity_contract_consumes_executable_ontology() -> None:
    """Scenario 4 uses #458 as authority for shared identity field names."""
    require_dependencies(ONTOLOGY)
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
    """Scenario 6 consumes, rather than duplicates, the locked #463 matcher.

    ``REAL_GOLDEN_PRODUCT_OBSERVATION`` keeps this an evidenced blocker until a
    converged product's own observation replaces the fixture's own
    ``example_observation`` below -- feeding a fixture its own example only
    proves oracle wiring, not product behavior (#459).
    """
    dependency = dependency_assessment(GOLDEN_BASELINES, REAL_GOLDEN_PRODUCT_OBSERVATION)
    if not dependency.ready:
        assert dependency.blockers
        return

    # The fixture's own example is only an oracle wiring proof. Product
    # observations replace it in the executable scenarios after their active
    # dependencies land; the expectations remain owned by #463.
    from tests.cross_product_parity.harness import load_golden_scenario

    scenario, _ = load_golden_scenario("builders", "retry_keeps_logical_run")
    assert_matches_golden("builders", "retry_keeps_logical_run", scenario["example_observation"])


def test_golden_real_observation_emits_strict_closeout_evidence() -> None:
    """Scenario 6 through the closeout machinery (#1069); see scenario 1."""
    evidence = execute_scenario_sync(GOLDEN_SCENARIO)
    if evidence.status == "BLOCKED":
        assert evidence.error or evidence.blockers


def test_strict_mode_fails_unavailable_dependencies_and_emits_json(capsys) -> None:
    """Source probes cannot turn a missing real product seam into green evidence."""
    dependency = Dependency(
        key="unshipped producer",
        issue=49,
        pr=None,
        description="A real producer boundary owned by the product issue.",
        probes=(SourceProbe("tests/cross_product_parity/no-such-closeout-seam.py"),),
    )
    called = False

    def execute() -> ScenarioExecution:
        nonlocal called
        called = True
        return ScenarioExecution({"run_id": "never"})

    scenario = ParityScenario("strict-unavailable", (dependency,), execute)
    with pytest.raises(DependencyUnavailable):
        execute_scenario_sync(scenario, mode=ParityMode.M1_CLOSEOUT)

    assert not called
    record = json.loads(capsys.readouterr().out.split(" ", 1)[1])
    assert record["scenario"] == "strict-unavailable"
    assert record["status"] == "FAILED"
    assert record["executed"] is False
    assert record["blockers"]


def test_strict_mode_fails_a_real_seam_that_abstains() -> None:
    """A ready source probe is not evidence that the producer actually ran."""
    dependency = Dependency(
        key="ready-looking producer",
        issue=49,
        pr=None,
        description="A source token is not a product execution.",
        probes=(),
    )

    def abstain() -> ScenarioExecution:
        raise ScenarioAbstained("producer did not execute")

    scenario = ParityScenario("strict-abstention", (dependency,), abstain)
    with pytest.raises(ScenarioAbstained):
        execute_scenario_sync(scenario, mode=ParityMode.M1_CLOSEOUT)


@pytest.mark.asyncio
async def test_strict_closeout_reports_every_required_scenario() -> None:
    """The aggregate closeout does not stop after the first unavailable seam."""
    missing = Dependency(
        key="missing closeout owner",
        issue=49,
        pr=None,
        description="A required producer boundary.",
        probes=(SourceProbe("tests/cross_product_parity/no-such-closeout-seam.py"),),
    )
    scenarios = (
        ParityScenario("first-required", (missing,), _builders_scenario),
        ParityScenario("second-required", (missing,), _scheduler_scenario),
    )

    with pytest.raises(CloseoutFailure) as raised:
        await execute_closeout(scenarios)

    report = json.loads(str(raised.value))
    assert report["passed"] is False
    assert [item["scenario"] for item in report["scenarios"]] == [
        "first-required",
        "second-required",
    ]
    assert all(item["status"] == "FAILED" for item in report["scenarios"])


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


def test_strict_mode_turns_synthetic_unavailable_dependency_into_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M1 closeout mode (#459): a blocker cannot register as a pass.

    ``dependency_assessment`` normally reports an unavailable dependency as a
    named blocker so development-mode scenarios can assert it and return.
    Under ``MAISTRO_PARITY_STRICT=1`` the same unavailable dependency must
    instead raise, so a strict-closeout scenario that only proved its
    dependency missing fails the suite rather than passing it.
    """
    monkeypatch.setenv("MAISTRO_PARITY_STRICT", "1")
    synthetic = Dependency(
        key="synthetic unavailable dependency",
        issue=1036,
        pr=None,
        description="A SourceProbe pointed at a path that does not exist.",
        probes=(SourceProbe("tests/cross_product_parity/__does_not_exist__.py"),),
    )

    with pytest.raises(DependencyUnavailable, match="synthetic unavailable dependency"):
        dependency_assessment(synthetic)


def test_non_strict_mode_still_reports_named_blockers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Development mode (#459) keeps naming blockers instead of failing closed."""
    monkeypatch.delenv("MAISTRO_PARITY_STRICT", raising=False)
    monkeypatch.delenv("MAISTRO_PARITY_MODE", raising=False)
    synthetic = Dependency(
        key="synthetic unavailable dependency",
        issue=1036,
        pr=None,
        description="A SourceProbe pointed at a path that does not exist.",
        probes=(SourceProbe("tests/cross_product_parity/__does_not_exist__.py"),),
    )

    assessment = dependency_assessment(synthetic)

    assert not assessment.ready
    assert len(assessment.blockers) == 1
    assert "synthetic unavailable dependency" in assessment.blockers[0]
    assert "issue #1036" in assessment.blockers[0]


def test_scaffold_only_scenarios_stay_blocked_until_real_execution_lands() -> None:
    """A source-probe-only scenario must not read as M1 closure evidence.

    Codex review (PR #1641): once a scenario's named product dependency lands,
    an import/source-token check alone is not proof the scenario executed a
    real cross-product Run through the product's own path. Each of scenarios
    1, 2, 3 and 6 carries its own permanent, evidence-backed blocker
    (``REAL_*`` in harness.py) precisely so the compound
    ``dependency_assessment`` call stays unavailable -- and strict mode stays
    red -- until that scaffold is replaced with a real execution.
    """
    for dependency in (
        REAL_BUILDERS_CONDUCTOR_SCENARIO,
        REAL_SCHEDULE_CONDUCTOR_SCENARIO,
        REAL_EVOLVE_CONDUCTOR_SCENARIO,
        REAL_GOLDEN_PRODUCT_OBSERVATION,
    ):
        assert not dependency.available(), (
            f"{dependency.key} reads as available -- its scaffold-only scenario "
            "would now pass as if it were real execution evidence"
        )

    # Scenario 6 concretely, right now: GOLDEN_BASELINES alone is already
    # satisfied on this branch, so REAL_GOLDEN_PRODUCT_OBSERVATION is the only
    # thing keeping that scenario from reading as closure evidence. Checked via
    # `.available()`, not `dependency_assessment()`, so this assertion holds
    # regardless of MAISTRO_PARITY_STRICT in the ambient test environment.
    assert GOLDEN_BASELINES.available()
    assert not REAL_GOLDEN_PRODUCT_OBSERVATION.available()
