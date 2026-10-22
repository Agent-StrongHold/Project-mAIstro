"""Failed benchmark calls are missing evidence, never a zero-quality baseline.

These consumer tests patch execution and evaluation at their service boundaries.
Run with PYTHONPATH=packages/hive-conductor/backend and --noconftest to avoid
starting the full Hive application; no gateway, engine, persistent store, or
network call is needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, Request
from routes import optimizer
from services import benchmark_eval, graph_runner, validation_gate
from services.dag_execution_scope import DagExecutionScope

from maistro.identity import Principal

pytestmark = [pytest.mark.contract("behavioral"), pytest.mark.scope("unit")]


@dataclass
class ConsumerHarness:
    dag: dict[str, Any]
    scope: DagExecutionScope
    request: Request
    execute: AsyncMock
    evaluate: AsyncMock


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> ConsumerHarness:
    import stores

    dag = {
        "id": "benchmark-consumer",
        "description": "Implement the task",
        "nodes": [{"id": "worker", "role": "worker", "model": "gpt-5.5"}],
        "edges": [],
    }
    scope = DagExecutionScope(workspace_id="workspace", project_id="project", user_id="actor")
    request = Request({"type": "http"})
    request.state.principal = Principal(user_id="actor", username="actor")
    execute = AsyncMock(return_value={"status": "completed", "run_id": "canonical-run"})
    evaluate = AsyncMock(return_value={"total": 0, "pass": False})
    monkeypatch.setattr(stores, "dags", {dag["id"]: dag})
    monkeypatch.setattr(optimizer, "authorize_hive_dag_scope", AsyncMock(return_value=scope))
    monkeypatch.setattr(
        optimizer,
        "run_optimizer",
        AsyncMock(return_value={"proposals": [{"kind": "topology_mutation"}], "auto_applied": 0}),
    )
    monkeypatch.setattr(graph_runner, "execute_dag", execute)
    monkeypatch.setattr(benchmark_eval, "evaluate_dag_run", evaluate)
    monkeypatch.setattr(validation_gate, "CANDIDATE_MODELS", ["gpt-4.1-nano"])
    monkeypatch.setattr(validation_gate, "PARAM_GRID", {"temperature": [0.1]})
    return ConsumerHarness(dag, scope, request, execute, evaluate)


@pytest.mark.parametrize("failure_stage", ["execution", "evaluation", "missing_total"])
async def test_optimizer_refuses_unavailable_baseline_before_testing_variants(
    harness: ConsumerHarness, monkeypatch: pytest.MonkeyPatch, failure_stage: str
) -> None:
    if failure_stage == "execution":
        harness.execute.side_effect = RuntimeError("private execution failure")
    elif failure_stage == "evaluation":
        harness.evaluate.side_effect = RuntimeError("private provider failure")
    else:
        harness.evaluate.return_value = {"pass": False}
    variants = [AsyncMock(return_value=[]) for _ in range(3)]
    for name, mock in zip(
        ("validate_and_filter_proposals", "hill_climb_models", "hill_climb_params"),
        variants,
        strict=True,
    ):
        monkeypatch.setattr(validation_gate, name, mock)

    with pytest.raises(HTTPException) as caught:
        await optimizer.trigger_optimizer(
            harness.dag["id"], harness.request, workspace_id=harness.scope.workspace_id
        )

    assert caught.value.status_code == 502
    assert "private" not in str(caught.value.detail)
    harness.execute.assert_awaited_once_with(harness.dag, scope=harness.scope)
    assert harness.evaluate.await_count == (failure_stage != "execution")
    for mock in variants:
        mock.assert_not_awaited()


@pytest.mark.parametrize(
    ("error_type", "status_code"),
    [("BenchmarkAuthorizationError", 403), ("BenchmarkEvaluationError", 502)],
)
async def test_optimizer_maps_typed_baseline_failure_without_variant_calls(
    harness: ConsumerHarness,
    monkeypatch: pytest.MonkeyPatch,
    error_type: str,
    status_code: int,
) -> None:
    harness.evaluate.side_effect = getattr(benchmark_eval, error_type)("private failure detail")
    variants = [AsyncMock(return_value=[]) for _ in range(3)]
    for name, mock in zip(
        ("validate_and_filter_proposals", "hill_climb_models", "hill_climb_params"),
        variants,
        strict=True,
    ):
        monkeypatch.setattr(validation_gate, name, mock)

    with pytest.raises(HTTPException) as caught:
        await optimizer.trigger_optimizer(
            harness.dag["id"], harness.request, workspace_id=harness.scope.workspace_id
        )

    assert caught.value.status_code == status_code
    assert "private" not in str(caught.value.detail)
    for mock in variants:
        mock.assert_not_awaited()


@pytest.mark.parametrize("total", [0, 34.5, 50])
async def test_optimizer_keeps_successful_baseline_and_scope(
    harness: ConsumerHarness, monkeypatch: pytest.MonkeyPatch, total: float
) -> None:
    harness.evaluate.return_value = {"total": total, "pass": total >= 35}
    expected = [{"kind": kind} for kind in ("topology", "model", "param")]
    variants = [AsyncMock(return_value=[proposal]) for proposal in expected]
    for name, mock in zip(
        ("validate_and_filter_proposals", "hill_climb_models", "hill_climb_params"),
        variants,
        strict=True,
    ):
        monkeypatch.setattr(validation_gate, name, mock)

    result = await optimizer.trigger_optimizer(
        harness.dag["id"], harness.request, workspace_id=harness.scope.workspace_id
    )

    assert result["validated"] is True
    assert result["baseline_score"] == total
    assert result["proposals"] == expected
    variants[0].assert_awaited_once_with(
        harness.dag, [{"kind": "topology_mutation"}], total, scope=harness.scope
    )
    for mock in variants[1:]:
        mock.assert_awaited_once_with(harness.dag, total, scope=harness.scope)


@pytest.mark.parametrize("failure_stage", ["execution", "evaluation", "missing_total"])
async def test_hill_climb_never_promotes_unscored_cheaper_model(
    harness: ConsumerHarness, failure_stage: str
) -> None:
    if failure_stage == "execution":
        harness.execute.side_effect = RuntimeError("execution failed")
    elif failure_stage == "evaluation":
        harness.evaluate.side_effect = RuntimeError("scoring failed")
    else:
        harness.evaluate.return_value = {"pass": False}

    winners = await validation_gate.hill_climb_models(harness.dag, 0, scope=harness.scope)

    assert winners == []
    assert harness.execute.await_count == 1
    assert harness.evaluate.await_count == (failure_stage != "execution")


@pytest.mark.parametrize("error_type", ["BenchmarkAuthorizationError", "BenchmarkEvaluationError"])
async def test_hill_climb_rejects_typed_evaluation_failures(
    harness: ConsumerHarness, error_type: str
) -> None:
    harness.evaluate.side_effect = getattr(benchmark_eval, error_type)("scoring refused")

    assert await validation_gate.hill_climb_models(harness.dag, 0, scope=harness.scope) == []
    assert await validation_gate.hill_climb_params(harness.dag, 0, scope=harness.scope) == []
    assert harness.execute.await_count == harness.evaluate.await_count == 2


@pytest.mark.parametrize("total", [0, 12.5, 50])
async def test_hill_climb_keeps_measured_cheaper_or_better_model(
    harness: ConsumerHarness, total: float
) -> None:
    harness.evaluate.return_value = {"total": total, "pass": total >= 35}

    winners = await validation_gate.hill_climb_models(harness.dag, 0, scope=harness.scope)

    assert len(winners) == 1
    assert winners[0]["validated"] is True
    assert winners[0]["variant_b_score"] == total
    assert winners[0]["model_tested"] == "gpt-4.1-nano"
    assert harness.dag["nodes"][0]["model"] == "gpt-5.5"


async def test_parameter_sweep_preserves_strict_improvement(harness: ConsumerHarness) -> None:
    assert await validation_gate.hill_climb_params(harness.dag, 0, scope=harness.scope) == []

    harness.evaluate.return_value = {"total": 4, "pass": False}
    winners = await validation_gate.hill_climb_params(harness.dag, 0, scope=harness.scope)

    assert len(winners) == 1
    assert winners[0]["validated"] is True
    assert winners[0]["variant_b_score"] == 4
