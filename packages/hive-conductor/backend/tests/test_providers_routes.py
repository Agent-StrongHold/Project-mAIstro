"""LLM provider activation routes (SPEC-072726-3439 Phase 4).

Keys are deployment-wide vault material behind config.write; activation
registers models with LiteLLM and runs a one-token test completion.
"""

from __future__ import annotations

import pathlib
import shutil
import sys
from contextlib import asynccontextmanager
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def _needs_age() -> None:
    if shutil.which("age") is None or shutil.which("age-keygen") is None:
        pytest.skip("age not installed")


class TestAuthz:
    def test_put_key_requires_config_write(self, authed_client) -> None:
        """A plain daily-driver session must not be able to store deployment-wide
        LLM keys — the route is gated under config.write in _PROTECTED_OPS."""
        r = authed_client.put("/v1/providers/anthropic/key", json={"api_key": "sk-x"})
        assert r.status_code == 403

    def test_activate_requires_config_write(self, authed_client) -> None:
        r = authed_client.post("/v1/providers/anthropic/activate")
        assert r.status_code == 403

    def test_unauthenticated_is_401(self) -> None:
        from fastapi.testclient import TestClient
        from main import app

        r = TestClient(app).get("/v1/providers")
        assert r.status_code == 401


class TestKeyAndActivate:
    def test_unknown_provider_404(self, admin_client) -> None:
        _needs_age()
        r = admin_client.put("/v1/providers/nonsense/key", json={"api_key": "k"})
        assert r.status_code == 404

    def test_empty_key_422(self, admin_client) -> None:
        _needs_age()
        r = admin_client.put("/v1/providers/anthropic/key", json={"api_key": "  "})
        assert r.status_code == 422

    def test_put_key_stores_in_vault_and_lists(self, admin_client) -> None:
        _needs_age()
        r = admin_client.put("/v1/providers/anthropic/key", json={"api_key": "sk-test-123"})
        assert r.status_code == 200
        assert r.json() == {"name": "anthropic", "has_key": True}

        listing = admin_client.get("/v1/providers").json()
        assert listing["vault_available"] is True
        by_name = {p["name"]: p for p in listing["providers"]}
        assert by_name["anthropic"]["has_key"] is True
        assert by_name["anthropic"]["activated"] is False

    def test_activate_without_key_409(self, admin_client) -> None:
        _needs_age()
        r = admin_client.post("/v1/providers/openai/activate")
        assert r.status_code == 409

    def test_activate_gateway_unreachable_502(
        self, admin_client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _needs_age()
        admin_client.put("/v1/providers/groq/key", json={"api_key": "sk-groq"})
        monkeypatch.setenv("LITELLM_PROXY_URL", "http://127.0.0.1:9")
        monkeypatch.setenv("LITELLM_PROXY_KEY", "master")
        r = admin_client.post("/v1/providers/groq/activate")
        assert r.status_code == 502

    def test_activate_happy_path_registers_and_tests(
        self, admin_client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _needs_age()
        admin_client.put("/v1/providers/mistral/key", json={"api_key": "sk-mistral"})
        monkeypatch.setenv("LITELLM_PROXY_URL", "http://litellm.test")
        monkeypatch.setenv("LITELLM_PROXY_KEY", "master")

        calls: list[tuple[str, dict[str, Any]]] = []

        from services import governed_model
        from services.governed_model import GovernedModelRuntime

        from maistro.capabilities.effect_context import new_in_memory_effect_context
        from maistro.capabilities.providers import llm_gateway
        from maistro.capabilities.providers.llm_gateway import GatewayEndpoint
        from maistro.providers.registry import InMemoryProviderRegistry
        from maistro.providers.router import CostAwareRouter
        from maistro.providers.types import ModelMetadata

        class _Resp:
            status_code = 200

            @staticmethod
            def json() -> dict[str, Any]:
                return {
                    "model": "mistral/mistral-large-latest",
                    "choices": [{"message": {"content": "pong"}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                }

        class _Client:
            async def __aenter__(self) -> _Client:
                return self

            async def __aexit__(self, *args: Any) -> None:
                del args

            async def post(self, url: str, **kwargs: Any) -> _Resp:
                calls.append((url, kwargs.get("json", {})))
                return _Resp()

        @asynccontextmanager
        async def _shared_client(*args: Any, **kwargs: Any):
            del args, kwargs
            yield _Client()

        registry = InMemoryProviderRegistry(
            models=[
                ModelMetadata(
                    name="mistral/mistral-large-latest",
                    provider="mistral",
                    cost_per_1k_input=0.0,
                    cost_per_1k_output=0.0,
                    latency_p50_ms=100,
                )
            ]
        )

        class _Root:
            project_id = "root-project"

        class _ProjectScope:
            async def root_for_workspace(self, workspace_id: str) -> _Root:
                assert workspace_id == "default"
                return _Root()

        runtime = GovernedModelRuntime(
            effects=new_in_memory_effect_context(),
            registry=registry,
            router=CostAwareRouter(registry),
            endpoint=GatewayEndpoint(base_url="http://litellm.test", api_key="master"),
            project_scope_store=_ProjectScope(),
        )
        monkeypatch.setattr(governed_model, "_runtime", lambda: runtime)
        monkeypatch.setattr(llm_gateway, "shared_client", _shared_client)

        r = admin_client.post("/v1/providers/mistral/activate")
        assert r.status_code == 200
        body = r.json()
        assert body["activated"] is True
        assert body["first_model_call"]["model"] == "mistral/mistral-large-latest"

        urls = [u for u, _ in calls]
        assert "http://litellm.test/model/new" in urls
        assert urls[-1] == "http://litellm.test/v1/chat/completions"
        # The vault key travels into the LiteLLM registration, never the response.
        assert calls[0][1]["litellm_params"]["api_key"] == "sk-mistral"
        assert "sk-mistral" not in r.text
