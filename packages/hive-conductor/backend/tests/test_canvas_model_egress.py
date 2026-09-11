from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from main import app
from services.canvas_model_egress import CanvasModelEgress

from maistro.capabilities.binding import Binding
from maistro.capabilities.effect_context import new_in_memory_effect_context
from maistro.capabilities.invocation import InvocationStatus
from maistro.capabilities.model_chat import MODEL_CHAT_CAPABILITY
from maistro.capabilities.providers.llm_gateway import GatewayEndpoint
from maistro.providers.registry import InMemoryProviderRegistry
from maistro.providers.router import CostAwareRouter
from maistro.providers.types import ModelMetadata


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
def canvas_egress(monkeypatch: pytest.MonkeyPatch) -> tuple[CanvasModelEgress, Any]:
    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    effects = new_in_memory_effect_context()
    binding = Binding(
        binding_id="canvas-quality-binding",
        workspace_id="ws-canvas",
        project_id="project-canvas",
        capability=MODEL_CHAT_CAPABILITY,
    )
    import asyncio

    asyncio.run(effects.bindings.put(binding))
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
    egress = CanvasModelEgress(
        effects=effects,
        registry=registry,
        router=CostAwareRouter(registry),
        endpoint=GatewayEndpoint(base_url="http://gateway.test"),
    )
    return egress, effects


def test_shipped_canvas_route_records_correlated_invocation(
    canvas_egress: tuple[CanvasModelEgress, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    egress, effects = canvas_egress
    monkeypatch.setattr(app.state, "canvas_model_egress", egress, raising=False)
    client = TestClient(app)
    login = client.post("/v1/auth/login", json={"username": "testuser", "password": "testpass"})
    assert login.status_code == 200

    response = client.post(
        "/v1/canvas/eval",
        json={
            "description": "A blue city at dusk",
            "context": {
                "binding_id": "canvas-quality-binding",
                "workspace_id": "ws-canvas",
                "project_id": "project-canvas",
                "run_id": "run-canvas",
                "node_id": "canvas-quality",
                "node_run_id": "node-run-canvas",
                "attempt_id": "attempt-canvas",
            },
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["score"] == 91

    import asyncio

    invocations = asyncio.run(
        effects.invocation_store.list_effect(
            run_id="run-canvas",
            node_run_id="node-run-canvas",
            binding_id="canvas-quality-binding",
            effect_key="canvas.visual_quality.evaluate",
        )
    )
    assert len(invocations) == 1
    assert invocations[0].status is InvocationStatus.COMPLETED
    assert invocations[0].attempt_id == "attempt-canvas"


def test_canvas_route_refuses_missing_execution_context(
    canvas_egress: tuple[CanvasModelEgress, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app.state, "canvas_model_egress", canvas_egress[0], raising=False)
    client = TestClient(app)
    login = client.post("/v1/auth/login", json={"username": "testuser", "password": "testpass"})
    assert login.status_code == 200

    response = client.post("/v1/canvas/eval", json={"description": "A blue city at dusk"})

    assert response.status_code == 503
    assert "score" not in response.json()
