from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from main import app
from pydantic import SecretStr
from routes.canvas import _canvas_execution_context, _quality_binding_id
from services import engine as engine_service
from services.canvas_dag import CanvasHillClimber, visual_quality_eval
from services.canvas_model_egress import CanvasModelEgress, build_canvas_model_egress
from starlette.requests import Request

from maistro.capabilities.binding import Binding
from maistro.capabilities.binding_store import BindingResolutionError
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


class _StubEgress:
    """Minimal governed-seam stand-in returning a score-shaped provider body."""

    def __init__(self, score: int = 88) -> None:
        self.score = score
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        *,
        context: dict[str, str],
        request: Any,
        response_validator: Any = None,
    ) -> Any:
        self.calls.append({"context": dict(context), "request": request})
        result = SimpleNamespace(
            body={
                "model": request.model,
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "score": self.score,
                                    "composition": 22,
                                    "color": 22,
                                    "style": 22,
                                    "detail": 22,
                                    "rationale": "stub",
                                }
                            )
                        }
                    }
                ],
            }
        )
        if response_validator is not None:
            response_validator(result)
        return result


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


class _MalformedResponse(_Response):
    def json(self) -> dict[str, Any]:
        return {"model": "claude-opus-4-6", "choices": []}


class _MalformedClient(_Client):
    async def post(self, *args: Any, **kwargs: Any) -> _MalformedResponse:
        return _MalformedResponse()


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
            ),
            actor_principal_id="user",
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
    import config

    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(
            litellm_api_base="http://gateway.test/v1",
            litellm_api_key=None,
            canvas_model_binding_id="canvas-quality-binding",
            model_bindings=[],
            hive_default_workspace_id="ws-canvas",
        ),
    )
    return egress, effects, context, components


def test_shipped_canvas_route_records_correlated_invocation(
    canvas_egress: tuple[CanvasModelEgress, Any, dict[str, str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _egress, effects, context, components = canvas_egress
    app.state._state.pop("canvas_model_egress", None)
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
            "run_id": context["run_id"],
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

    import asyncio

    attempt = asyncio.run(components.run_store.get_attempt(context["attempt_id"]))
    assert attempt is not None
    assert attempt.status.value == "completed"
    assert attempt.result["score"] == 91


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
        json={"description": "A blue city at dusk", "run_id": context["run_id"]},
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
        json={"description": "A blue city at dusk", "run_id": context["run_id"]},
    )

    assert response.status_code == 503
    assert "score" not in response.json()
    import asyncio

    attempt = asyncio.run(canvas_egress[3].run_store.get_attempt(context["attempt_id"]))
    assert attempt is not None
    assert attempt.status.value == "failed"


def test_canvas_route_fails_malformed_quality_response(
    canvas_egress: tuple[CanvasModelEgress, Any, dict[str, str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    egress, effects, context, components = canvas_egress
    monkeypatch.setattr(httpx, "AsyncClient", _MalformedClient)
    monkeypatch.setattr(app.state, "canvas_model_egress", egress, raising=False)
    client = TestClient(app)
    login = client.post("/v1/auth/login", json={"username": "testuser", "password": "testpass"})
    assert login.status_code == 200

    response = client.post(
        "/v1/canvas/eval",
        json={"description": "A blue city at dusk", "run_id": context["run_id"]},
    )

    assert response.status_code == 502
    assert "score" not in response.json()
    import asyncio

    attempt = asyncio.run(components.run_store.get_attempt(context["attempt_id"]))
    assert attempt is not None
    assert attempt.status.value == "failed"
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


def test_canvas_route_refuses_missing_binding(
    canvas_egress: tuple[CanvasModelEgress, Any, dict[str, str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app.state, "canvas_model_egress", canvas_egress[0], raising=False)
    client = TestClient(app)
    login = client.post("/v1/auth/login", json={"username": "testuser", "password": "testpass"})
    assert login.status_code == 200

    context = dict(canvas_egress[2])
    import config

    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(
            litellm_api_base="http://gateway.test/v1",
            litellm_api_key=None,
            canvas_model_binding_id="not-authorized",
            model_bindings=[],
            hive_default_workspace_id="ws-canvas",
        ),
    )
    response = client.post(
        "/v1/canvas/eval",
        json={"description": "A blue city at dusk", "run_id": context["run_id"]},
    )

    assert response.status_code == 503
    assert "score" not in response.json()
    import asyncio

    attempt = asyncio.run(canvas_egress[3].run_store.get_attempt(context["attempt_id"]))
    assert attempt is not None
    assert attempt.status.value == "failed"


class _PayloadCapturingClient(_Client):
    last_payload: dict[str, Any] | None = None

    async def post(self, *args: Any, **kwargs: Any) -> _Response:
        payload = kwargs.get("json")
        if isinstance(payload, dict):
            _PayloadCapturingClient.last_payload = dict(payload)
        return _Response()


def test_canvas_route_sends_legacy_json_response_format(
    canvas_egress: tuple[CanvasModelEgress, Any, dict[str, str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The governed egress carries the legacy JSON-mode constraint to the provider.

    The pre-migration call constrained responses with
    ``response_format={"type": "json_object"}`` so Canvas score parsing was a
    provider guarantee. Parity means the shipped route's provider payload keeps
    that constraint after crossing the governed seam.
    """
    egress, _effects, context, _components = canvas_egress
    _PayloadCapturingClient.last_payload = None
    monkeypatch.setattr(httpx, "AsyncClient", _PayloadCapturingClient)
    monkeypatch.setattr(app.state, "canvas_model_egress", egress, raising=False)
    client = TestClient(app)
    login = client.post("/v1/auth/login", json={"username": "testuser", "password": "testpass"})
    assert login.status_code == 200

    response = client.post(
        "/v1/canvas/eval",
        json={"description": "A blue city at dusk", "run_id": context["run_id"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["score"] == 91

    payload = _PayloadCapturingClient.last_payload
    assert payload is not None, "the governed egress must dispatch exactly one provider call"
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["model"] == "claude-opus-4-6"
    assert payload["temperature"] == 0.0
    assert payload["stream"] is False


def test_canvas_route_refuses_disabled_binding(
    canvas_egress: tuple[CanvasModelEgress, Any, dict[str, str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A disabled Binding fails the evaluation truthfully, never a fake score."""
    egress, effects, context, components = canvas_egress
    import asyncio

    asyncio.run(
        effects.bindings.put(
            Binding(
                binding_id="canvas-quality-disabled",
                workspace_id=context["workspace_id"],
                project_id=context["project_id"],
                capability=MODEL_CHAT_CAPABILITY,
                disabled=True,
            )
        )
    )
    import config

    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(
            litellm_api_base="http://gateway.test/v1",
            litellm_api_key=None,
            canvas_model_binding_id="canvas-quality-disabled",
            model_bindings=[],
            hive_default_workspace_id="ws-canvas",
        ),
    )
    monkeypatch.setattr(app.state, "canvas_model_egress", egress, raising=False)
    client = TestClient(app)
    login = client.post("/v1/auth/login", json={"username": "testuser", "password": "testpass"})
    assert login.status_code == 200

    response = client.post(
        "/v1/canvas/eval",
        json={"description": "A blue city at dusk", "run_id": context["run_id"]},
    )

    assert response.status_code == 503
    assert "score" not in response.json()
    attempt = asyncio.run(components.run_store.get_attempt(context["attempt_id"]))
    assert attempt is not None
    assert attempt.status.value == "failed"


def _request_with_state(
    state: dict[str, Any],
) -> Request:
    scope: dict[str, Any] = {
        "type": "http",
        "method": "POST",
        "path": "/v1/canvas/eval",
        "headers": [],
        "query_string": b"",
        "app": app,
        "state": dict(state),
    }
    return Request(scope)


def _seed_run(
    run_store: Any,
    *,
    project_id: str,
    actor_principal_id: str | None,
    node_type: str = "canvas.visual_quality",
    with_node_run: bool = True,
    with_attempt: bool = True,
) -> tuple[Any, Any | None, Any | None]:
    """Seed one canonical Canvas execution with the requested shape."""

    async def _create() -> tuple[Any, Any | None, Any | None]:
        run = await run_store.create_run(
            Graph(
                graph_id=f"canvas-graph-{node_type}-{actor_principal_id}",
                workspace_id="ws-canvas",
                project_id=project_id,
                name="Canvas quality",
                nodes=[Node(node_id="canvas-quality", node_type=node_type)],
            ),
            actor_principal_id=actor_principal_id,
        )
        node_run = attempt = None
        if with_node_run:
            node_run = await run_store.create_node_run(run.run_id, node_id="canvas-quality")
            if with_attempt:
                attempt = await run_store.create_attempt(node_run.node_run_id)
        return run, node_run, attempt

    import asyncio

    return asyncio.run(_create())


def test_canvas_route_refuses_run_owned_by_another_principal(
    canvas_egress: tuple[CanvasModelEgress, Any, dict[str, str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Run minted by another principal is refused, never re-owned."""
    egress, _effects, _context, components = canvas_egress
    run, _node_run, _attempt = _seed_run(
        components.run_store,
        project_id=canvas_egress[2]["project_id"],
        actor_principal_id="someone-else",
    )
    monkeypatch.setattr(app.state, "canvas_model_egress", egress, raising=False)
    client = TestClient(app)
    login = client.post("/v1/auth/login", json={"username": "testuser", "password": "testpass"})
    assert login.status_code == 200

    response = client.post(
        "/v1/canvas/eval",
        json={"description": "A blue city at dusk", "run_id": run.run_id},
    )

    assert response.status_code == 403
    assert "score" not in response.json()


def test_canvas_route_refuses_run_without_execution_principal(
    canvas_egress: tuple[CanvasModelEgress, Any, dict[str, str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An admin may inspect any Run, but a principal-less Run still refuses."""
    egress, _effects, _context, components = canvas_egress
    run, _node_run, _attempt = _seed_run(
        components.run_store,
        project_id=canvas_egress[2]["project_id"],
        actor_principal_id=None,
    )
    monkeypatch.setattr(app.state, "canvas_model_egress", egress, raising=False)
    client = TestClient(app)
    login = client.post("/v1/auth/login", json={"username": "testadmin", "password": "adminpass"})
    assert login.status_code == 200

    response = client.post(
        "/v1/canvas/eval",
        json={"description": "A blue city at dusk", "run_id": run.run_id},
    )

    assert response.status_code == 503
    assert "score" not in response.json()


def test_canvas_route_refuses_run_without_quality_node(
    canvas_egress: tuple[CanvasModelEgress, Any, dict[str, str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Run whose Graph carries no visual-quality Node cannot be evaluated."""
    egress, _effects, _context, components = canvas_egress
    run, _node_run, _attempt = _seed_run(
        components.run_store,
        project_id=canvas_egress[2]["project_id"],
        actor_principal_id="user",
        node_type="canvas.generate",
    )
    monkeypatch.setattr(app.state, "canvas_model_egress", egress, raising=False)
    client = TestClient(app)
    login = client.post("/v1/auth/login", json={"username": "testuser", "password": "testpass"})
    assert login.status_code == 200

    response = client.post(
        "/v1/canvas/eval",
        json={"description": "A blue city at dusk", "run_id": run.run_id},
    )

    assert response.status_code == 503
    assert "score" not in response.json()


def test_canvas_route_refuses_quality_node_without_node_run(
    canvas_egress: tuple[CanvasModelEgress, Any, dict[str, str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A quality Node that never became a NodeRun has no execution to settle."""
    egress, _effects, _context, components = canvas_egress
    run, _node_run, _attempt = _seed_run(
        components.run_store,
        project_id=canvas_egress[2]["project_id"],
        actor_principal_id="user",
        with_node_run=False,
    )
    monkeypatch.setattr(app.state, "canvas_model_egress", egress, raising=False)
    client = TestClient(app)
    login = client.post("/v1/auth/login", json={"username": "testuser", "password": "testpass"})
    assert login.status_code == 200

    response = client.post(
        "/v1/canvas/eval",
        json={"description": "A blue city at dusk", "run_id": run.run_id},
    )

    assert response.status_code == 503
    assert "score" not in response.json()


def test_canvas_route_refuses_quality_node_run_without_open_attempt(
    canvas_egress: tuple[CanvasModelEgress, Any, dict[str, str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No open Attempt means no evaluation lifecycle to settle truthfully."""
    egress, _effects, _context, components = canvas_egress
    run, _node_run, _attempt = _seed_run(
        components.run_store,
        project_id=canvas_egress[2]["project_id"],
        actor_principal_id="user",
        with_attempt=False,
    )
    monkeypatch.setattr(app.state, "canvas_model_egress", egress, raising=False)
    client = TestClient(app)
    login = client.post("/v1/auth/login", json={"username": "testuser", "password": "testpass"})
    assert login.status_code == 200

    response = client.post(
        "/v1/canvas/eval",
        json={"description": "A blue city at dusk", "run_id": run.run_id},
    )

    assert response.status_code == 503
    assert "score" not in response.json()


def test_canvas_route_fails_when_model_egress_is_uncomposed(
    canvas_egress: tuple[CanvasModelEgress, Any, dict[str, str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A container without a composed agent port is an unavailable evaluation."""
    _egress, _effects, context, _components = canvas_egress
    app.state._state.pop("canvas_model_egress", None)
    monkeypatch.setattr(engine_service.get_engine(), "_agent_port", SimpleNamespace(container=None))
    client = TestClient(app)
    login = client.post("/v1/auth/login", json={"username": "testuser", "password": "testpass"})
    assert login.status_code == 200

    response = client.post(
        "/v1/canvas/eval",
        json={"description": "A blue city at dusk", "run_id": context["run_id"]},
    )

    assert response.status_code == 503
    assert "score" not in response.json()


def test_canvas_route_fails_when_model_egress_is_incompletely_composed(
    canvas_egress: tuple[CanvasModelEgress, Any, dict[str, str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A container missing one canonical authority is unavailable, not degraded."""
    _egress, effects, context, components = canvas_egress
    app.state._state.pop("canvas_model_egress", None)
    monkeypatch.setattr(
        engine_service.get_engine(),
        "_agent_port",
        SimpleNamespace(
            container=SimpleNamespace(
                capability_effects=effects,
                provider_registry=components.provider_registry,
                llm_router=components.llm_router,
                run_store=None,
            )
        ),
    )
    client = TestClient(app)
    login = client.post("/v1/auth/login", json={"username": "testuser", "password": "testpass"})
    assert login.status_code == 200

    response = client.post(
        "/v1/canvas/eval",
        json={"description": "A blue city at dusk", "run_id": context["run_id"]},
    )

    assert response.status_code == 503
    assert "score" not in response.json()


def test_trusted_canvas_context_resolves_supplied_execution_identity(
    canvas_egress: tuple[CanvasModelEgress, Any, dict[str, str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The execution path's trusted state resolves against canonical state.

    The Canvas execution path (#735) stamps Run/NodeRun/Attempt identity it
    already holds onto request state; the route must accept exactly that
    identity, including the Binding it names, without re-deriving it.
    """
    egress, _effects, context, _components = canvas_egress
    monkeypatch.setattr(app.state, "canvas_model_egress", egress, raising=False)
    request = _request_with_state(
        {
            "user": {"id": "user", "role": "user"},
            "canvas_execution_context": {
                "binding_id": context["binding_id"],
                "run_id": context["run_id"],
                "node_id": context["node_id"],
                "node_run_id": context["node_run_id"],
                "attempt_id": context["attempt_id"],
            },
        }
    )

    import asyncio

    resolved = asyncio.run(_canvas_execution_context(request, None))

    assert resolved == {
        "binding_id": context["binding_id"],
        "run_id": context["run_id"],
        "node_id": context["node_id"],
        "node_run_id": context["node_run_id"],
        "attempt_id": context["attempt_id"],
        "workspace_id": context["workspace_id"],
        "project_id": context["project_id"],
    }


def test_trusted_canvas_context_refuses_run_mismatch(
    canvas_egress: tuple[CanvasModelEgress, Any, dict[str, str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Trusted state naming one Run cannot evaluate a different Run."""
    egress, _effects, context, _components = canvas_egress
    monkeypatch.setattr(app.state, "canvas_model_egress", egress, raising=False)
    request = _request_with_state(
        {
            "user": {"id": "user", "role": "user"},
            "canvas_execution_context": {"run_id": context["run_id"]},
        }
    )

    import asyncio

    with pytest.raises(BindingResolutionError, match="does not match the selected Run"):
        asyncio.run(_canvas_execution_context(request, "another-run"))


def test_trusted_canvas_context_refuses_unknown_quality_node(
    canvas_egress: tuple[CanvasModelEgress, Any, dict[str, str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    egress, _effects, context, _components = canvas_egress
    monkeypatch.setattr(app.state, "canvas_model_egress", egress, raising=False)
    request = _request_with_state(
        {
            "user": {"id": "user", "role": "user"},
            "canvas_execution_context": {
                "run_id": context["run_id"],
                "node_id": "not-a-quality-node",
            },
        }
    )

    import asyncio

    with pytest.raises(BindingResolutionError, match="does not name a quality Node"):
        asyncio.run(_canvas_execution_context(request, None))


def test_trusted_canvas_context_refuses_unknown_node_run(
    canvas_egress: tuple[CanvasModelEgress, Any, dict[str, str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    egress, _effects, context, _components = canvas_egress
    monkeypatch.setattr(app.state, "canvas_model_egress", egress, raising=False)
    request = _request_with_state(
        {
            "user": {"id": "user", "role": "user"},
            "canvas_execution_context": {
                "run_id": context["run_id"],
                "node_run_id": "no-such-node-run",
            },
        }
    )

    import asyncio

    with pytest.raises(BindingResolutionError, match="does not name this Run's NodeRun"):
        asyncio.run(_canvas_execution_context(request, None))


def test_trusted_canvas_context_refuses_foreign_node_run(
    canvas_egress: tuple[CanvasModelEgress, Any, dict[str, str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A NodeRun from another Run cannot settle this Run's evaluation."""
    egress, _effects, context, components = canvas_egress
    other_run, other_node_run, _other_attempt = _seed_run(
        components.run_store,
        project_id=canvas_egress[2]["project_id"],
        actor_principal_id="user",
    )
    assert other_run.run_id != context["run_id"]
    monkeypatch.setattr(app.state, "canvas_model_egress", egress, raising=False)
    request = _request_with_state(
        {
            "user": {"id": "user", "role": "user"},
            "canvas_execution_context": {
                "run_id": context["run_id"],
                "node_run_id": other_node_run.node_run_id,
            },
        }
    )

    import asyncio

    with pytest.raises(BindingResolutionError, match="does not name this Run's NodeRun"):
        asyncio.run(_canvas_execution_context(request, None))


def test_trusted_canvas_context_refuses_foreign_attempt(
    canvas_egress: tuple[CanvasModelEgress, Any, dict[str, str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An Attempt belonging to another NodeRun is not this evaluation's."""
    egress, _effects, context, components = canvas_egress
    _other_run, _other_node_run, other_attempt = _seed_run(
        components.run_store,
        project_id=canvas_egress[2]["project_id"],
        actor_principal_id="user",
    )
    monkeypatch.setattr(app.state, "canvas_model_egress", egress, raising=False)
    request = _request_with_state(
        {
            "user": {"id": "user", "role": "user"},
            "canvas_execution_context": {
                "run_id": context["run_id"],
                "node_run_id": context["node_run_id"],
                "attempt_id": other_attempt.attempt_id,
            },
        }
    )

    import asyncio

    with pytest.raises(BindingResolutionError, match="does not name this NodeRun's Attempt"):
        asyncio.run(_canvas_execution_context(request, None))


def test_canvas_context_requires_authenticated_principal(
    canvas_egress: tuple[CanvasModelEgress, Any, dict[str, str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The route re-checks the principal even if upstream middleware is bypassed."""
    monkeypatch.setattr(app.state, "canvas_model_egress", canvas_egress[0], raising=False)
    request = _request_with_state({"canvas_execution_context": {"run_id": "run-any"}})

    import asyncio

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(_canvas_execution_context(request, "run-any"))
    assert excinfo.value.status_code == 401
    assert excinfo.value.detail == "Authentication required"


def test_quality_binding_id_prefers_one_deployment_scoped_binding() -> None:
    """With no route-level binding, one scoped declaration is selected."""
    settings = SimpleNamespace(
        canvas_model_binding_id="",
        hive_default_workspace_id="ws-canvas",
        model_bindings=[
            SimpleNamespace(
                binding_id="binding-other-project",
                workspace_id="",
                project_id="project-b",
                node_id="",
            ),
            SimpleNamespace(
                binding_id="binding-canvas",
                workspace_id="",
                project_id="project-a",
                node_id="",
            ),
        ],
    )
    run = SimpleNamespace(workspace_id="ws-canvas", project_id="project-a")

    selected = _quality_binding_id(settings, run, "canvas-quality", {})

    assert selected == "binding-canvas"


def test_quality_binding_id_returns_stable_unconfigured_reference() -> None:
    """Ambiguous or absent declarations resolve to a stable missing reference.

    The reference is resolved (and failed truthfully) by the governed egress
    rather than being rejected at route level, so the owning Attempt still
    settles as failed.
    """
    settings = SimpleNamespace(
        canvas_model_binding_id="",
        hive_default_workspace_id="ws-canvas",
        model_bindings=[],
    )
    run = SimpleNamespace(workspace_id="ws-canvas", project_id="project-a")

    absent = _quality_binding_id(settings, run, "canvas-quality", {})
    assert absent == "__canvas_binding_unconfigured__"

    ambiguous_settings = SimpleNamespace(
        canvas_model_binding_id="",
        hive_default_workspace_id="ws-canvas",
        model_bindings=[
            SimpleNamespace(
                binding_id="binding-one",
                workspace_id="ws-canvas",
                project_id="project-a",
                node_id="",
            ),
            SimpleNamespace(
                binding_id="binding-two",
                workspace_id="ws-canvas",
                project_id="project-a",
                node_id="",
            ),
        ],
    )
    ambiguous = _quality_binding_id(ambiguous_settings, run, "canvas-quality", {})
    assert ambiguous == "__canvas_binding_unconfigured__"


def test_visual_quality_eval_requires_governed_egress() -> None:
    """No egress means an unavailable evaluation, never a fallback score."""
    import asyncio

    with pytest.raises(RuntimeError, match="no governed model egress"):
        asyncio.run(visual_quality_eval("A blue city at dusk"))
    with pytest.raises(RuntimeError, match="requires canonical execution context"):
        asyncio.run(
            visual_quality_eval(
                "A blue city at dusk",
                context=None,
                egress=_StubEgress(),
            )
        )


def test_parse_visual_quality_result_keeps_canvas_parsing_contract() -> None:
    """Score parsing stays Canvas behavior: each malformed shape is a refusal."""
    from services.canvas_dag import _parse_visual_quality_result

    happy = _parse_visual_quality_result(
        SimpleNamespace(
            body={"choices": [{"message": {"content": '{"score": 91, "rationale": "ok"}'}}]}
        )
    )
    assert happy == {"score": 91, "rationale": "ok"}

    with pytest.raises(ValueError, match="no response body"):
        _parse_visual_quality_result(SimpleNamespace(body="not-a-dict"))
    with pytest.raises(ValueError, match="no message content"):
        _parse_visual_quality_result(SimpleNamespace(body={"choices": []}))
    with pytest.raises(ValueError, match="non-text message content"):
        _parse_visual_quality_result(
            SimpleNamespace(body={"choices": [{"message": {"content": {"score": 90}}}]})
        )
    with pytest.raises(ValueError, match="must be a JSON object"):
        _parse_visual_quality_result(
            SimpleNamespace(body={"choices": [{"message": {"content": "[1, 2, 3]"}}]})
        )


def test_hill_climb_pass_evaluates_through_governed_egress() -> None:
    """The climber's evaluation crosses the governed seam it was composed with."""
    import asyncio

    egress = _StubEgress(score=88)

    async def _run_dag(dag: dict[str, Any], text: str) -> dict[str, Any]:
        return {"node_results": {"refiner": {"output": "A calm harbor at dusk"}}}

    climber = CanvasHillClimber(egress=egress)
    record = asyncio.run(
        climber.run_pass("paint a harbor", _run_dag, context={"binding_id": "canvas-binding"})
    )

    assert record["score"] == 88
    assert record["improved"] is True
    assert len(egress.calls) == 1
    assert egress.calls[0]["context"] == {"binding_id": "canvas-binding"}
    assert egress.calls[0]["request"].model == "claude-opus-4-6"


def test_canvas_egress_requires_canonical_run_store(
    canvas_egress: tuple[CanvasModelEgress, Any, dict[str, str], Any],
) -> None:
    """Without the composed Run store the evaluation refuses, not invents."""
    _egress, effects, context, components = canvas_egress
    import asyncio

    uncomposed = CanvasModelEgress(
        effects=effects,
        registry=components.provider_registry,
        router=components.llm_router,
        endpoint=GatewayEndpoint(base_url="http://gateway.test"),
        run_store=None,
    )
    with pytest.raises(BindingResolutionError, match="no canonical Run store"):
        asyncio.run(
            uncomposed.complete(
                context=dict(context),
                request=_stub_request(),
            )
        )


def _stub_request() -> Any:
    from maistro.capabilities.providers.llm_gateway import ModelChatRequest

    return ModelChatRequest(model="claude-opus-4-6", messages=[{"role": "user", "content": "x"}])


def test_canvas_egress_requires_existing_execution_chain(
    canvas_egress: tuple[CanvasModelEgress, Any, dict[str, str], Any],
) -> None:
    """Context naming state the store never held is a refusal."""
    egress, _effects, context, _components = canvas_egress
    import asyncio

    unknown = {**context, "run_id": "run-never-created"}
    with pytest.raises(BindingResolutionError, match="existing canonical Run"):
        asyncio.run(egress.complete(context=unknown, request=_stub_request()))


def test_canvas_egress_requires_one_canonical_chain(
    canvas_egress: tuple[CanvasModelEgress, Any, dict[str, str], Any],
) -> None:
    """A NodeRun from another Run does not settle this Run's evaluation."""
    egress, _effects, context, components = canvas_egress
    import asyncio

    _other_run, other_node_run, _other_attempt = _seed_run(
        components.run_store,
        project_id=context["project_id"],
        actor_principal_id="user",
    )
    mismatched = {**context, "node_run_id": other_node_run.node_run_id}
    with pytest.raises(BindingResolutionError, match="one canonical chain"):
        asyncio.run(egress.complete(context=mismatched, request=_stub_request()))


def test_canvas_egress_refuses_mismatched_execution_scope(
    canvas_egress: tuple[CanvasModelEgress, Any, dict[str, str], Any],
) -> None:
    """Workspace/Project/node identity must match the canonical chain."""
    egress, _effects, context, _components = canvas_egress
    import asyncio

    wrong_workspace = {**context, "workspace_id": "ws-somewhere-else"}
    with pytest.raises(BindingResolutionError, match="Workspace does not match"):
        asyncio.run(egress.complete(context=wrong_workspace, request=_stub_request()))

    wrong_project = {**context, "project_id": "project-somewhere-else"}
    with pytest.raises(BindingResolutionError, match="Project does not match"):
        asyncio.run(egress.complete(context=wrong_project, request=_stub_request()))

    wrong_node = {**context, "node_id": "not-the-quality-node"}
    with pytest.raises(BindingResolutionError, match="node does not match"):
        asyncio.run(egress.complete(context=wrong_node, request=_stub_request()))


def test_canvas_egress_requires_context_identity(
    canvas_egress: tuple[CanvasModelEgress, Any, dict[str, str], Any],
) -> None:
    """Blank context identity is a refusal naming what is missing."""
    egress, _effects, context, _components = canvas_egress
    import asyncio

    blank = {**context, "binding_id": ""}
    with pytest.raises(BindingResolutionError, match="binding_id"):
        asyncio.run(egress.complete(context=blank, request=_stub_request()))


def test_canvas_egress_refuses_terminal_attempt(
    canvas_egress: tuple[CanvasModelEgress, Any, dict[str, str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An already-settled Attempt is never re-evaluated or re-settled."""
    egress, effects, context, components = canvas_egress
    import asyncio

    from maistro.runs.model import AttemptStatus

    asyncio.run(
        components.run_store.transition_attempt(context["attempt_id"], AttemptStatus.RUNNING)
    )
    asyncio.run(
        components.run_store.transition_attempt(context["attempt_id"], AttemptStatus.COMPLETED)
    )
    with pytest.raises(BindingResolutionError, match="already terminal"):
        asyncio.run(egress.complete(context=dict(context), request=_stub_request()))

    invocations = asyncio.run(
        effects.invocation_store.list_effect(
            run_id=context["run_id"],
            node_run_id=context["node_run_id"],
            binding_id=context["binding_id"],
            effect_key="canvas.visual_quality.evaluate",
        )
    )
    assert invocations == []
    attempt = asyncio.run(components.run_store.get_attempt(context["attempt_id"]))
    assert attempt is not None
    assert attempt.status is AttemptStatus.COMPLETED


def test_build_canvas_model_egress_materializes_secret_and_plain_keys(
    canvas_egress: tuple[CanvasModelEgress, Any, dict[str, str], Any],
) -> None:
    """Both SecretStr and plain-string gateway keys reach the provider endpoint."""
    _egress, effects, _context, components = canvas_egress
    base = {
        "effects": effects,
        "registry": components.provider_registry,
        "router": components.llm_router,
        "run_store": components.run_store,
    }

    secret = build_canvas_model_egress(
        settings=SimpleNamespace(
            litellm_api_base="http://gateway.test/v1", litellm_api_key=SecretStr("sk-secret")
        ),
        **base,  # type: ignore[arg-type]
    )
    assert secret._egress._endpoint.api_key == "sk-secret"

    plain = build_canvas_model_egress(
        settings=SimpleNamespace(litellm_api_base="http://gateway.test/v1", litellm_api_key="sk"),
        **base,  # type: ignore[arg-type]
    )
    assert plain._egress._endpoint.api_key == "sk"
    assert plain.run_store is components.run_store
