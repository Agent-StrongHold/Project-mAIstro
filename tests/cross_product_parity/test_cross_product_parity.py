"""Named M1 cross-product parity suite (#459).

The active product convergence PRs are dependencies, not implementation material
for this branch. Tests that need one of those seams expected-fail only for the
narrow ``DependencyUnavailable`` assertion. Any actual parity failure remains a
normal red test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from maistro.graph.definitions import Graph, Node
from tests.cross_product_parity.harness import (
    BUILDERS,
    CONDUCTOR_INSPECTION,
    EVOLVE,
    GOLDEN_BASELINES,
    ONTOLOGY,
    SCHEDULER,
    ParityContractError,
    assert_identity_projection,
    assert_matches_golden,
    assert_ontology_identity_projection,
    dependency_xfail,
    open_durable_profile,
    require_dependencies,
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


@dependency_xfail(BUILDERS, CONDUCTOR_INSPECTION)
def test_builders_created_work_has_public_conductor_inspection_seams() -> None:
    """Scenario 1 activation contract.

    This branch does not reproduce Builders or Conductor behavior. Once both
    owners land, this stops x-failing and proves the public producer plus public
    inspection plane are simultaneously present for the executable scenario.
    """
    require_dependencies(BUILDERS, CONDUCTOR_INSPECTION)

    from maistro.builders.canonical_execution import CanonicalGraphPipelineExecutor

    assert CanonicalGraphPipelineExecutor.__name__ == "CanonicalGraphPipelineExecutor"
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


@dependency_xfail(SCHEDULER, CONDUCTOR_INSPECTION)
def test_schedule_fire_has_canonical_admission_and_shared_inspection_seams() -> None:
    """Scenario 2 activation contract for the live schedule fire path."""
    require_dependencies(SCHEDULER, CONDUCTOR_INSPECTION)
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


@dependency_xfail(EVOLVE, CONDUCTOR_INSPECTION)
def test_evolve_has_canonical_run_identity_and_shared_inspection_seams() -> None:
    """Scenario 3 activation contract for the shipped Evolve cycle path."""
    require_dependencies(EVOLVE, CONDUCTOR_INSPECTION)
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


@dependency_xfail(ONTOLOGY)
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


@dependency_xfail(GOLDEN_BASELINES)
def test_463_golden_fixtures_are_consumed_as_independent_oracle() -> None:
    """Scenario 6 consumes, rather than duplicates, the locked #463 matcher."""
    require_dependencies(GOLDEN_BASELINES)

    # The fixture's own example is only an oracle wiring proof. Product
    # observations replace it in the executable scenarios after their active
    # dependencies land; the expectations remain owned by #463.
    from tests.cross_product_parity.harness import load_golden_scenario

    scenario, _ = load_golden_scenario("builders", "retry_keeps_logical_run")
    assert_matches_golden("builders", "retry_keeps_logical_run", scenario["example_observation"])


def test_dependency_handling_contains_no_silent_skip_escape_hatch() -> None:
    """Unavailable product scenarios must stay visible in pytest output."""
    suite_dir = Path(__file__).resolve().parent
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (suite_dir / "harness.py", suite_dir / "test_cross_product_parity.py")
    )
    assert "pytest.skip(" not in source
    assert "pytest.importorskip(" not in source
