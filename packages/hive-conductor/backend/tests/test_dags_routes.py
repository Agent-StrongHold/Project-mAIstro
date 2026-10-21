"""Route coverage for the Conductor DAG CRUD and canonical Run projection."""

from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import UTC, datetime
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def _seed(client: Any) -> str:
    response = client.post("/v1/dags", json={"name": "seed", "description": ""})
    assert response.status_code == 201
    return response.json()["id"]


def _workspace(client: Any) -> str:
    response = client.post(
        "/v1/workspaces", json={"persona_template_id": "pm_fleet", "name": "DAG runs"}
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_list_dags_returns_array(admin_client: Any) -> None:
    response = admin_client.get("/v1/dags")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_get_dag_by_id_returns_payload(admin_client: Any) -> None:
    dag_id = _seed(admin_client)
    response = admin_client.get(f"/v1/dags/{dag_id}")
    assert response.status_code == 200
    assert response.json()["id"] == dag_id
    assert response.json()["name"] == "seed"


def test_get_dag_missing_returns_404(admin_client: Any) -> None:
    assert admin_client.get("/v1/dags/missing-xyz").status_code == 404


def test_add_and_remove_node(admin_client: Any) -> None:
    dag_id = _seed(admin_client)
    response = admin_client.post(
        f"/v1/dags/{dag_id}/nodes",
        json={"role": "scout", "name": "Scout"},
    )
    assert response.status_code == 200
    node_id = response.json()["id"]
    assert response.json()["role"] == "scout"

    removed = admin_client.delete(f"/v1/dags/{dag_id}/nodes/{node_id}")
    assert removed.status_code == 200
    assert removed.json()["id"] == node_id


def test_add_node_dag_404(admin_client: Any) -> None:
    response = admin_client.post(
        "/v1/dags/missing-dag/nodes",
        json={"role": "scout", "name": "x"},
    )
    assert response.status_code == 404


def test_remove_node_dag_404(admin_client: Any) -> None:
    assert admin_client.delete("/v1/dags/missing-dag/nodes/any").status_code == 404


def test_remove_node_not_found(admin_client: Any) -> None:
    dag_id = _seed(admin_client)
    assert admin_client.delete(f"/v1/dags/{dag_id}/nodes/no-such").status_code == 404


def test_add_and_remove_edge(admin_client: Any) -> None:
    dag_id = _seed(admin_client)
    current = admin_client.get(f"/v1/dags/{dag_id}").json()
    src = current["nodes"][0]["id"]
    dst = current["nodes"][1]["id"]
    response = admin_client.post(
        f"/v1/dags/{dag_id}/edges",
        json={"from_node": src, "to_node": dst, "condition": "if x"},
    )
    assert response.status_code == 200
    edge_id = response.json()["id"]
    assert response.json()["condition"] == "if x"

    removed = admin_client.delete(f"/v1/dags/{dag_id}/edges/{edge_id}")
    assert removed.status_code == 200
    assert removed.json()["id"] == edge_id


def test_add_edge_dag_404(admin_client: Any) -> None:
    response = admin_client.post(
        "/v1/dags/missing/edges",
        json={"from_node": "a", "to_node": "b"},
    )
    assert response.status_code == 404


def test_remove_edge_dag_404(admin_client: Any) -> None:
    assert admin_client.delete("/v1/dags/missing/edges/any").status_code == 404


def test_remove_edge_not_found(admin_client: Any) -> None:
    dag_id = _seed(admin_client)
    assert admin_client.delete(f"/v1/dags/{dag_id}/edges/no-such").status_code == 404


def test_delete_dag_succeeds_and_then_404s(admin_client: Any) -> None:
    dag_id = _seed(admin_client)
    assert admin_client.delete(f"/v1/dags/{dag_id}").status_code == 204
    assert admin_client.get(f"/v1/dags/{dag_id}").status_code == 404


def test_delete_dag_missing_returns_404(admin_client: Any) -> None:
    assert admin_client.delete("/v1/dags/never-existed").status_code == 404


def test_activate_dag(admin_client: Any) -> None:
    import stores

    before_audit = len(stores.audit_log)
    dag_id = _seed(admin_client)
    response = admin_client.post(f"/v1/dags/{dag_id}/activate")
    assert response.status_code == 200
    assert response.json()["status"] == "active"
    entries = list(stores.audit_log.values())
    assert any(
        entry["action"] == "dag_activate" and entry["target"] == dag_id
        for entry in entries[before_audit:]
    )


def test_activate_dag_missing_404(admin_client: Any) -> None:
    assert admin_client.post("/v1/dags/missing-dag/activate").status_code == 404


def _completed_result(run_id: str = "run-canonical-1") -> dict[str, Any]:
    return {
        "status": "completed",
        "run_id": run_id,
        "cycles": 1,
        "node_results": {
            "n1": {
                "role": "worker",
                "success": True,
                "response": "did the thing",
                "model": "model-a",
            }
        },
        "annotations": {},
    }


def test_run_dag_success_uses_canonical_run_id(
    admin_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import services.graph_runner as graph_runner

    async def ok(_dag_data: Any, **_kwargs: Any) -> dict[str, Any]:
        return _completed_result()

    monkeypatch.setattr(graph_runner, "execute_dag", ok)
    dag_id = _seed(admin_client)
    workspace_id = _workspace(admin_client)
    response = admin_client.post(f"/v1/dags/{dag_id}/run", json={"workspace_id": workspace_id})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["execution_id"] == "run-canonical-1"
    assert body["run_id"] == "run-canonical-1"
    assert body["result"]["run_id"] == "run-canonical-1"

    from services.dag_run_store import get_dag_run_store

    projection = get_dag_run_store().get_run("run-canonical-1")
    assert projection is not None
    assert projection["canonical_run_id"] == "run-canonical-1"
    assert projection["status"] == "completed"
    assert projection["event_count"] == 1


def test_activate_then_run_dag_with_a_selected_workspace_succeeds(
    admin_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replicates the PM-workflow e2e spec's "activate and run a DAG" step
    (tests/e2e/pm-workflow.spec.ts #06) at the HTTP layer: create, activate,
    then run with an explicit Workspace selection. Before #766's Workspace
    scope selection was wired into the e2e spec, this same sequence without a
    ``workspace_id`` got a 403 (see `test_run_dag_missing_scope_fails_before_execution`
    above) — this is the corresponding success path the fix restores."""
    import services.graph_runner as graph_runner

    async def ok(_dag_data: Any, **_kwargs: Any) -> dict[str, Any]:
        return _completed_result("run-activate-then-run")

    monkeypatch.setattr(graph_runner, "execute_dag", ok)

    create = admin_client.post("/v1/dags", json={"name": "E2E Run Test", "description": "test"})
    assert create.status_code == 201
    dag_id = create.json()["id"]

    activate = admin_client.post(f"/v1/dags/{dag_id}/activate")
    assert activate.status_code == 200
    assert activate.json()["status"] == "active"

    workspace_id = _workspace(admin_client)
    run = admin_client.post(f"/v1/dags/{dag_id}/run", json={"workspace_id": workspace_id})
    assert run.status_code == 200
    body = run.json()
    assert body["execution_id"]


def test_run_dag_canonical_failure_stays_failed(
    admin_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import services.graph_runner as graph_runner

    failed = {
        "status": "failed",
        "run_id": "run-failed-1",
        "cycles": 1,
        "node_results": {"n1": {"role": "worker", "success": False, "response": "node failed"}},
        "error": "node failed",
    }

    async def fail(_dag_data: Any, **_kwargs: Any) -> dict[str, Any]:
        raise graph_runner.CanonicalDagExecutionError(failed)

    monkeypatch.setattr(graph_runner, "execute_dag", fail)
    dag_id = _seed(admin_client)
    workspace_id = _workspace(admin_client)
    response = admin_client.post(f"/v1/dags/{dag_id}/run", json={"workspace_id": workspace_id})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["execution_id"] == "run-failed-1"
    assert body["run_id"] == "run-failed-1"
    assert "node failed" in body["error"]

    from services.dag_run_store import get_dag_run_store

    projection = get_dag_run_store().get_run("run-failed-1")
    assert projection is not None
    assert projection["canonical_run_id"] == "run-failed-1"
    assert projection["status"] == "failed"
    assert projection["node_states"]["worker.n1"] == "failed"


def test_run_dag_pre_admission_failure_has_no_fake_execution_id(
    admin_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import services.graph_runner as graph_runner

    async def boom(_dag_data: Any, **_kwargs: Any) -> dict[str, Any]:
        raise ValueError("cyclic DAG rejected before execution")

    monkeypatch.setattr(graph_runner, "execute_dag", boom)
    dag_id = _seed(admin_client)
    workspace_id = _workspace(admin_client)
    response = admin_client.post(f"/v1/dags/{dag_id}/run", json={"workspace_id": workspace_id})
    assert response.status_code == 200
    body = response.json()
    # The exception kind, never its text: messages carry paths and provider
    # replies, which stay in the server log (CodeQL py/stack-trace-exposure).
    assert body == {"status": "failed", "error": "ValueError: execution failed; see server logs"}


def test_run_dag_projection_failure_does_not_rewrite_execution(
    admin_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import services.dag_run_store as history
    import services.graph_runner as graph_runner

    async def ok(_dag_data: Any, **_kwargs: Any) -> dict[str, Any]:
        return _completed_result("run-with-history-failure")

    def unavailable() -> Any:
        raise RuntimeError("history unavailable")

    monkeypatch.setattr(graph_runner, "execute_dag", ok)
    monkeypatch.setattr(history, "get_dag_run_store", unavailable)

    dag_id = _seed(admin_client)
    workspace_id = _workspace(admin_client)
    response = admin_client.post(f"/v1/dags/{dag_id}/run", json={"workspace_id": workspace_id})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["run_id"] == "run-with-history-failure"


def test_run_dag_missing_scope_fails_before_execution(
    admin_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import services.graph_runner as graph_runner

    async def should_not_run(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("execution admitted without Workspace scope")

    monkeypatch.setattr(graph_runner, "execute_dag", should_not_run)
    dag_id = _seed(admin_client)
    response = admin_client.post(f"/v1/dags/{dag_id}/run")
    assert response.status_code == 403


def test_run_dag_carries_distinct_authorized_scopes(
    admin_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import services.graph_runner as graph_runner

    captured: list[Any] = []

    async def ok(_dag_data: Any, **kwargs: Any) -> dict[str, Any]:
        captured.append(kwargs["scope"])
        return _completed_result(f"run-{len(captured)}")

    monkeypatch.setattr(graph_runner, "execute_dag", ok)
    dag_id = _seed(admin_client)
    workspace_a = _workspace(admin_client)
    workspace_b = _workspace(admin_client)
    assert (
        admin_client.post(f"/v1/dags/{dag_id}/run", json={"workspace_id": workspace_a}).status_code
        == 200
    )
    assert (
        admin_client.post(f"/v1/dags/{dag_id}/run", json={"workspace_id": workspace_b}).status_code
        == 200
    )
    assert [scope.workspace_id for scope in captured] == [workspace_a, workspace_b]
    assert captured[0].project_id != captured[1].project_id


def test_run_dag_missing_dag_returns_404(admin_client: Any) -> None:
    assert admin_client.post("/v1/dags/missing-dag/run").status_code == 404


def test_run_champion_success_uses_canonical_run_id(
    admin_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import services.graph_runner as graph_runner

    async def ok(**_kwargs: Any) -> dict[str, Any]:
        return {"status": "completed", "run_id": "champion-run", "champion": True}

    monkeypatch.setattr(graph_runner, "execute_champion", ok)
    workspace_id = _workspace(admin_client)
    response = admin_client.post("/v1/dags/run-champion", json={"workspace_id": workspace_id})
    assert response.status_code == 200
    body = response.json()
    assert body["result"]["champion"] is True
    assert body["execution_id"] == "champion-run"
    assert body["run_id"] == "champion-run"


def test_run_champion_failure(admin_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    import services.graph_runner as graph_runner

    async def boom(**_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("champion crash")

    monkeypatch.setattr(graph_runner, "execute_champion", boom)
    workspace_id = _workspace(admin_client)
    response = admin_client.post("/v1/dags/run-champion", json={"workspace_id": workspace_id})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["error"] == "RuntimeError: execution failed; see server logs"
    assert "champion crash" not in body["error"]


@pytest.mark.asyncio
async def test_a_result_without_a_run_id_projects_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Recent Runs projection keys on the canonical Run id; a result that
    never got one (pre-admission failure shapes) must not mint a projection
    row under some synthesized key."""
    import routes.dags as dags_routes
    import services.dag_run_store as history

    def _unexpected_store() -> Any:  # pragma: no cover
        raise AssertionError("no store may be consulted without a run id")

    monkeypatch.setattr(history, "get_dag_run_store", _unexpected_store)

    await dags_routes._record_run_projection(
        dag_id="dag-1",
        user_id="admin",
        result={"status": "failed", "error": "no run was admitted"},
    )


# --- #1839: canonical admission backpressure on the DAG HTTP routes ---


@pytest.fixture
def canonical_dag_spine(_chat_spine_container: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Wire a real canonical Container onto the engine (same shape as the
    transport-parity suite's ``canonical_run_spine``): without it the DAG
    route's runner sees no Container, never calls ``RunStore.create_run``,
    and a capacity refusal could not happen at all."""
    from types import SimpleNamespace

    from services.engine import get_engine

    container = _chat_spine_container
    spine = SimpleNamespace(
        run_store=container.run_store,
        graph_run_store=container.graph_run_store,
        workspace_store=container.workspace_store,
        project_scope_store=container.project_scope_store,
    )
    monkeypatch.setattr(get_engine(), "_agent_port", SimpleNamespace(container=spine))
    yield container


def _real_champion(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install a real EvolutionService whose population holds a genuinely
    champion-eligible genome: a real ``PopulationStore`` whose ``get_champion``
    runs the shared #854 eligibility contract. Missing evolution/population/
    champion returns before admission, so a saturation test needs the real
    thing, not a stub that skips the admission path under test."""
    import services.evolution as evolution_service

    from maistro_evolve.population import PopulationStore
    from maistro_evolve.types import DAGTopology, EvalWeights, NodeGenome, PipelineGenome

    genome = PipelineGenome(
        id="capacity-champion",
        name="capacity-champion",
        topology=DAGTopology(
            nodes=[
                NodeGenome(
                    id="q1",
                    role="queen",
                    strategy="react",
                    model="gpt-4",
                    temperature=0.3,
                    max_tokens=4096,
                    system_prompt="champion pipeline",
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
        fitness_score=0.8,
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )
    genome.eval_scores = {"proxy_ifeval": 0.8}
    genome.harness_params["eval_samples"] = {"proxy_ifeval": 2}
    genome.harness_params["eval_history"] = {"proxy_ifeval": [0.79, 0.81]}
    genome.harness_params["objective_version"] = "objective-test"
    genome.harness_params["evidence_cycle"] = 1

    population = PopulationStore()
    population.add(genome)
    champion = population.get_champion()
    assert champion is not None, "seeded genome must be champion-eligible for real"

    service = evolution_service._EvolutionService()
    service._population = population
    monkeypatch.setattr(evolution_service, "_service", service)


def _enforced_limits(store: Any) -> Any:
    """The active-root ceilings the store under test actually enforces."""
    from maistro.runs.concurrency import RunConcurrencyLimits

    limits = getattr(store, "_concurrency_limits", None)
    return limits if limits is not None else RunConcurrencyLimits.configured()


def _active_root_snapshot(store: Any) -> dict[str, tuple[str, str, str]]:
    """run_id -> (status, principal, workspace) for every active root Run."""
    from maistro.runs.concurrency import ACTIVE_ROOT_STATUSES

    return {
        run.run_id: (run.status.value, str(run.actor_principal_id), str(run.workspace_id))
        for run in store._runs.values()
        if run.parent_run_id is None and run.status in ACTIVE_ROOT_STATUSES
    }


def _active_count(store: Any, *, ceiling: str, workspace_id: str) -> int:
    active = _active_root_snapshot(store)
    if ceiling == "principal":
        return sum(1 for _, principal, _ws in active.values() if principal == "admin")
    return sum(1 for _, _principal, ws in active.values() if ws == workspace_id)


def _seed_active_root(store: Any, scope: Any, *, actor: str, name: str) -> str:
    """Admit one genuinely active root Run through the real ``create_run``."""
    from services.canonical_dag_runner import graph_from_legacy_dag

    from maistro.runs.model import RunStatus

    graph = graph_from_legacy_dag(
        {
            "id": name,
            "name": name,
            "description": "capacity saturation seed",
            "nodes": [
                {
                    "id": "n1",
                    "role": "worker",
                    "name": "n1",
                    "prompt": "seed work",
                    "config": {"execution_tier": "safe"},
                }
            ],
            "edges": [],
        },
        workspace_id=scope.workspace_id,
        project_id=scope.project_id,
    )
    run = asyncio.run(
        store.create_run(
            graph,
            initial_status=RunStatus.QUEUED,
            actor_principal_id=actor,
            provenance={"admission_source": "test_capacity_seed", "legacy_dag_id": name},
        )
    )
    return run.run_id


def _saturate(container: Any, scope: Any, *, ceiling: str) -> list[str]:
    """Seed genuinely active roots up to the enforced ceiling.

    Never a capacity-exception stub: the saturated state is real canonical
    Runs in QUEUED (an active status), admitted through the same
    ``RunStore.create_run`` the route under test is refused by.
    """
    import math
    from collections import defaultdict

    store = container.run_store
    limits = _enforced_limits(store)
    if ceiling == "principal":
        needed = limits.per_principal - _active_count(
            store, ceiling="principal", workspace_id=scope.workspace_id
        )
        actors = ["admin"]
    else:
        needed = limits.per_workspace - _active_count(
            store, ceiling="workspace", workspace_id=scope.workspace_id
        )
        # Seed roots for other principals: each stays within its own principal
        # ceiling (creating the limit-th root is legal), so the saturation is
        # purely the Workspace ceiling.
        actors = [f"seed-actor-{i}" for i in range(math.ceil(needed / limits.per_principal) + 1)]
    if needed <= 0:
        # Already at (or over) the ceiling from genuinely active roots --
        # e.g. a failed sibling parameterization left its saturation in the
        # shared session container. The premise (a saturated store) holds;
        # there is nothing left to seed.
        return []
    seeded: list[str] = []
    per_actor: dict[str, int] = defaultdict(int)
    actor_cycle = iter(actors * (math.ceil(needed / len(actors)) + 1))
    while len(seeded) < needed:
        actor = next(actor_cycle)
        if per_actor[actor] >= limits.per_principal:
            continue
        seeded.append(
            _seed_active_root(store, scope, actor=actor, name=f"saturation-{ceiling}-{len(seeded)}")
        )
        per_actor[actor] += 1
    return seeded


@pytest.mark.parametrize(
    ("endpoint", "ceiling"),
    [
        ("dag", "principal"),
        ("dag", "workspace"),
        ("champion", "principal"),
        ("champion", "workspace"),
    ],
)
def test_dag_http_capacity_refusal_returns_429(
    admin_client: Any,
    canonical_dag_spine: Any,
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
    ceiling: str,
) -> None:
    """A saturated canonical RunStore turns a DAG submission into retryable
    admission backpressure (#1182/#1839): HTTP 429 with scoped detail and
    Retry-After -- never a 200 receipt, never new canonical state, never a
    model dispatch -- and the same submission succeeds once capacity is
    released through the same runner."""
    import services.graph_runner as graph_runner
    import stores
    from services.dag_agents import get_run_store
    from services.dag_execution_scope import authorize_hive_dag_scope
    from services.dag_run_store import get_dag_run_store

    from maistro.runs.model import RunStatus

    container = canonical_dag_spine
    store = container.run_store
    dag_id = "capacity-refusal-dag"
    stores.dags[dag_id] = {
        "id": dag_id,
        "name": dag_id,
        "description": "under saturation",
        "nodes": [
            {
                "id": "n1",
                "role": "worker",
                "name": "n1",
                "prompt": "real work",
                "config": {"execution_tier": "safe"},
            }
        ],
        "edges": [],
    }
    try:
        workspace_id = _workspace(admin_client)
        scope = asyncio.run(authorize_hive_dag_scope(workspace_id=workspace_id, user_id="admin"))

        _saturate(container, scope, ceiling=ceiling)
        limits = _enforced_limits(store)
        active_at_ceiling = _active_count(store, ceiling=ceiling, workspace_id=scope.workspace_id)
        enforced = limits.per_principal if ceiling == "principal" else limits.per_workspace
        assert active_at_ceiling >= enforced, "saturation did not reach the enforced ceiling"

        if endpoint == "champion":
            _real_champion(monkeypatch)

        dispatches: list[str] = []

        def _spying_builder(on_response: Any = None) -> Any:
            dispatches.append("built")

            async def _call(messages: list[dict[str, Any]], **_kwargs: Any) -> str:
                dispatches.append("dispatched")
                return "model output during a capacity refusal"

            return _call

        monkeypatch.setattr(graph_runner, "_build_llm_call", _spying_builder)

        active_before = _active_root_snapshot(store)
        counts_before = (len(store._runs), len(store._node_runs), len(store._attempts))
        graph_rows_before = set(get_run_store()._continuations._rows)
        projection_before = set(get_dag_run_store()._runs)

        if endpoint == "dag":
            response = admin_client.post(
                f"/v1/dags/{dag_id}/run", json={"workspace_id": workspace_id}
            )
        else:
            response = admin_client.post(
                "/v1/dags/run-champion", json={"workspace_id": workspace_id}
            )

        # Backpressure, not a failure receipt: the same contract as the chat
        # transport's 429 -- scoped detail (the ceiling kind, never the
        # exception text) and Retry-After.
        assert response.status_code == 429, response.text
        assert response.headers["retry-after"] == "5"
        assert response.json() == {
            "detail": f"too many active runs for this {ceiling}; retry shortly"
        }

        # The refusal created nothing and disturbed nothing: no Run, NodeRun
        # or Attempt, no durable graph execution record, no Recent Runs row,
        # no model/tool dispatch, and every admitted Run keeps its identity
        # and lifecycle state.
        assert dispatches == []
        assert _active_root_snapshot(store) == active_before
        assert (len(store._runs), len(store._node_runs), len(store._attempts)) == counts_before
        assert set(get_run_store()._continuations._rows) == graph_rows_before
        assert set(get_dag_run_store()._runs) == projection_before

        # Capacity released by terminalizing the admitted work: every active
        # root in this Workspace, plus every admin root (the principal case).
        for run_id, (_status, principal, workspace) in active_before.items():
            if principal == "admin" or workspace == scope.workspace_id:
                asyncio.run(store.transition_run(run_id, RunStatus.CANCELLED))

        runs_before_release = set(store._runs)
        if endpoint == "dag":
            released = admin_client.post(
                f"/v1/dags/{dag_id}/run", json={"workspace_id": workspace_id}
            )
        else:
            released = admin_client.post(
                "/v1/dags/run-champion", json={"workspace_id": workspace_id}
            )
        assert released.status_code == 200, released.text
        # The same runner re-engaged: exactly one new canonical Run was
        # admitted for the released submission.
        new_run_ids = set(store._runs) - runs_before_release
        assert len(new_run_ids) == 1
        run_id = new_run_ids.pop()
        if endpoint == "dag":
            body = released.json()
            assert body["run_id"] == run_id
            assert body["execution_id"] == run_id
        record = asyncio.run(store.get_run(run_id))
        assert record is not None
        assert str(record.workspace_id) == scope.workspace_id
        node_runs = asyncio.run(store.list_node_runs(run_id))
        assert node_runs, "the same runner must have dispatched the admitted Run"
        if endpoint == "dag":
            # Interactive execution completes in this environment.
            assert record.status is RunStatus.COMPLETED
        else:
            # The champion path executes `autonomous` (its existing contract);
            # in this sandbox that ends at the ADR-093 isolation floor, which
            # is an honest node outcome, not an admission refusal. What this
            # leg proves is that the submission was admitted and dispatched --
            # not refused -- and reached a terminal state through the runner
            # under its own canonical identity.
            from maistro.runs.model import TERMINAL_RUN_STATUSES

            assert record.status in TERMINAL_RUN_STATUSES
        # The same runner really executed the admitted work: the spy builder
        # was consulted only after admission, never for the refused attempt.
        assert dispatches or endpoint == "champion", (
            "released submission must dispatch through the runner"
        )
    finally:
        stores.dags.pop(dag_id, None)
