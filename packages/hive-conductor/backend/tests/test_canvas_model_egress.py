from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from main import app
from services import engine as engine_service
from services.canvas_model_egress import CanvasModelEgress

from maistro.capabilities.binding import Binding
from maistro.capabilities.effect_context import new_in_memory_effect_context
from maistro.capabilities.invocation import InvocationStatus
from maistro.capabilities.model_chat import MODEL_CHAT_CAPABILITY
from maistro.capabilities.providers.llm_gateway import GatewayEndpoint
from maistro.graph.definitions import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.providers.registry import InMemoryProviderRegistry
from maistro.providers.router import CostAwareRouter
from maistro.providers.types import ModelMetadata
from maistro.runs.store import InMemoryRunStore


class _Response:
    status_code = 200

    def json(self) -> dict[str, Any]:
        return {
            "model": "claude-opus-4-6",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": '{"score": 91, "composition": 23, "color": 24, "style": 22, "detail": 22, "rationale": "clear"}',
                    }
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 12},
        }


class _Client:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    async def post(self, *args: Any, **kwargs: Any) -> _Response:
        return _Response()


@pytest.fixture
def canvas_egress(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[CanvasModelEgress, Any, dict[str, str], Any]:
    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    effects = new_in_memory_effect_context()
    import asyncio

    async def _seed_execution() -> tuple[dict[str, str], InMemoryRunStore]:
        project_store = InMemoryProjectScopeStore()
        project = await project_store.create_root("ws-canvas")
        binding = Binding(
            binding_id="canvas-quality-binding",
            workspace_id="ws-canvas",
            project_id=project.project_id,
            capability=MODEL_CHAT_CAPABILITY,
        )
        await effects.bindings.put(binding)
        run_store = InMemoryRunStore(project_store=project_store)
        run = await run_store.create_run(
            Graph(
                graph_id="canvas-graph",
                workspace_id="ws-canvas",
                project_id=project.project_id,
                name="Canvas quality",
                nodes=[Node(node_id="canvas-quality", node_type="canvas.visual_quality")],
            )
        )
        node_run = await run_store.create_node_run(run.run_id, node_id="canvas-quality")
        attempt = await run_store.create_attempt(node_run.node_run_id)
        return {
            "binding_id": binding.binding_id,
            "workspace_id": run.workspace_id,
            "project_id": run.project_id,
            "run_id": run.run_id,
            "node_id": node_run.node_id,
            "node_run_id": node_run.node_run_id,
            "attempt_id": attempt.attempt_id,
        }, run_store

    context, run_store = asyncio.run(_seed_execution())
    registry = InMemoryProviderRegistry(
        models=[
            ModelMetadata(
                name="claude-opus-4-6",
                provider="test-gateway",
                cost_per_1k_input=1.0,
                cost_per_1k_output=1.0,
                latency_p50_ms=100,
            )
        ]
    )
    router = CostAwareRouter(registry)
    egress = CanvasModelEgress(
        effects=effects,
        registry=registry,
        router=router,
        endpoint=GatewayEndpoint(base_url="http://gateway.test"),
        run_store=run_store,
    )
    components = SimpleNamespace(
        capability_effects=effects,
        provider_registry=registry,
        llm_router=router,
        run_store=run_store,
    )
    return egress, effects, context, components


def test_shipped_canvas_route_records_correlated_invocation(
    canvas_egress: tuple[CanvasModelEgress, Any, dict[str, str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _egress, effects, context, components = canvas_egress
    monkeypatch.setattr(
        engine_service.get_engine(),
        "_agent_port",
        SimpleNamespace(container=components),
    )
    client = TestClient(app)
    login = client.post("/v1/auth/login", json={"username": "testuser", "password": "testpass"})
    assert login.status_code == 200

    response = client.post(
        "/v1/canvas/eval",
        json={
            "description": "A blue city at dusk",
            "context": context,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["score"] == 91

    import asyncio

    invocations = asyncio.run(
        effects.invocation_store.list_effect(
            run_id=context["run_id"],
            node_run_id=context["node_run_id"],
            binding_id=context["binding_id"],
            effect_key="canvas.visual_quality.evaluate",
        )
    )
    assert len(invocations) == 1
    assert invocations[0].status is InvocationStatus.COMPLETED
    assert invocations[0].attempt_id == context["attempt_id"]
    assert invocations[0].workspace_id == context["workspace_id"]
    assert invocations[0].project_id == context["project_id"]
    assert invocations[0].binding.workspace_id == context["workspace_id"]
    assert invocations[0].binding.project_id == context["project_id"]


def test_canvas_route_refuses_missing_execution_context(
    canvas_egress: tuple[CanvasModelEgress, Any, dict[str, str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app.state, "canvas_model_egress", canvas_egress[0], raising=False)
    client = TestClient(app)
    login = client.post("/v1/auth/login", json={"username": "testuser", "password": "testpass"})
    assert login.status_code == 200

    response = client.post("/v1/canvas/eval", json={"description": "A blue city at dusk"})

    assert response.status_code == 503
    assert "score" not in response.json()


def test_canvas_route_refuses_fabricated_execution_identity(
    canvas_egress: tuple[CanvasModelEgress, Any, dict[str, str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app.state, "canvas_model_egress", canvas_egress[0], raising=False)
    client = TestClient(app)
    login = client.post("/v1/auth/login", json={"username": "testuser", "password": "testpass"})
    assert login.status_code == 200

    context = dict(canvas_egress[2])
    context["run_id"] = "fabricated-run"
    response = client.post(
        "/v1/canvas/eval",
        json={"description": "A blue city at dusk", "context": context},
    )

    assert response.status_code == 503
    assert "score" not in response.json()


def test_canvas_route_refuses_unavailable_provider(
    canvas_egress: tuple[CanvasModelEgress, Any, dict[str, str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    egress, _effects, context, components = canvas_egress
    components.provider_registry.mark_unavailable("claude-opus-4-6")
    monkeypatch.setattr(app.state, "canvas_model_egress", egress, raising=False)
    client = TestClient(app)
    login = client.post("/v1/auth/login", json={"username": "testuser", "password": "testpass"})
    assert login.status_code == 200

    response = client.post(
        "/v1/canvas/eval",
        json={"description": "A blue city at dusk", "context": context},
    )

    assert response.status_code == 503
    assert "score" not in response.json()


def test_canvas_route_refuses_missing_binding(
    canvas_egress: tuple[CanvasModelEgress, Any, dict[str, str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app.state, "canvas_model_egress", canvas_egress[0], raising=False)
    client = TestClient(app)
    login = client.post("/v1/auth/login", json={"username": "testuser", "password": "testpass"})
    assert login.status_code == 200

    context = dict(canvas_egress[2])
    context["binding_id"] = "not-authorized"
    response = client.post(
        "/v1/canvas/eval",
        json={"description": "A blue city at dusk", "context": context},
    )

    assert response.status_code == 503
    assert "score" not in response.json()
