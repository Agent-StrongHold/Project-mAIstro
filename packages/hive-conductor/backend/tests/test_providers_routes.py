"""LLM provider activation routes (SPEC-072726-3439 Phase 4).

Keys are deployment-wide vault material behind config.write; activation
registers models with LiteLLM and runs a one-token test completion.
"""

from __future__ import annotations

import asyncio
import pathlib
import shutil
import sys
from contextlib import asynccontextmanager
from typing import Any

import pytest

from maistro.capabilities.effect_context import binding_scope_policy

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def _needs_age() -> None:
    if shutil.which("age") is None or shutil.which("age-keygen") is None:
        pytest.skip("age not installed")


_GROQ_TEST_MODEL = "groq/llama-3.3-70b-versatile"


def _wire_governed_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    endpoint: Any,
    # Explicit M1 baseline default (#846): an omitted evaluator is an
    # unavailable dependency and denies, so behavior tests opt in here and
    # denial tests pass their denying evaluator explicitly.
    policy_evaluator: Any = binding_scope_policy,
    project_scope_store: Any = True,
) -> tuple[Any, Any]:
    """Build an in-memory governed runtime and aim the route's ``_runtime()``
    at it, so activation runs the real governed path without a core Container.
    ``project_scope_store=False`` omits the scope store to exercise the route's
    fail-closed refusal.
    """
    import config
    from services import governed_model

    from maistro.capabilities.effect_context import new_in_memory_effect_context
    from maistro.capabilities.providers.llm_gateway import GatewayEndpoint
    from maistro.projects.scope_store import InMemoryProjectScopeStore
    from maistro.providers.registry import InMemoryProviderRegistry
    from maistro.providers.router import CostAwareRouter
    from maistro.providers.types import ModelMetadata
    from maistro.runs.store import InMemoryRunStore

    async def _build() -> tuple[InMemoryProjectScopeStore, InMemoryRunStore]:
        scope = InMemoryProjectScopeStore()
        await scope.create_root("default")
        return scope, InMemoryRunStore(project_store=scope)

    scope, run_store = asyncio.run(_build())
    registry = InMemoryProviderRegistry(
        models=[
            ModelMetadata(
                name=_GROQ_TEST_MODEL,
                provider="groq",
                cost_per_1k_input=0.0,
                cost_per_1k_output=0.0,
                latency_p50_ms=100,
            )
        ]
    )
    runtime = governed_model.GovernedModelRuntime(
        effects=new_in_memory_effect_context(policy_evaluator=policy_evaluator),
        registry=registry,
        router=CostAwareRouter(registry),
        endpoint=endpoint
        if isinstance(endpoint, GatewayEndpoint)
        else GatewayEndpoint(base_url=str(endpoint), api_key="master"),
        project_scope_store=scope if project_scope_store is True else None,
        run_store=run_store,
    )
    monkeypatch.setattr(governed_model, "_runtime", lambda: runtime)
    settings = type("Settings", (), {"hive_default_workspace_id": "default"})()
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    return runtime, run_store


def _patch_llm_http(
    monkeypatch: pytest.MonkeyPatch, responder: Any
) -> list[tuple[str, dict[str, Any]]]:
    """Route the gateway module's shared_client seam to ``responder(url, json)``.
    The seam stays the real governed path; only the HTTP socket is pinned."""
    from contextlib import asynccontextmanager

    from maistro.capabilities.providers import llm_gateway

    calls: list[tuple[str, dict[str, Any]]] = []

    class _Client:
        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *args: Any) -> None:
            del args

        async def post(self, url: str, **kwargs: Any) -> Any:
            calls.append((url, kwargs.get("json", {})))
            return await responder(url, kwargs.get("json", {}))

    @asynccontextmanager
    async def _shared_client(*args: Any, **kwargs: Any):
        del args, kwargs
        yield _Client()

    monkeypatch.setattr(llm_gateway, "shared_client", _shared_client)
    return calls


def _activation_run(run_store: Any, outcome: str) -> Any:
    """The canonical provider-activation:groq operation run in ``outcome``."""
    from maistro.runs.model import RunStatus

    async def _find() -> Any:
        runs = await run_store.list_by_status(RunStatus[outcome.upper()], limit=50)
        matches = [
            run for run in runs if run.provenance.get("operation") == "provider-activation:groq"
        ]
        assert len(matches) == 1
        return matches[0]

    return asyncio.run(_find())


def _deny_policy() -> Any:
    from maistro.policy.types import Decision, PolicyVerdict

    async def deny(*args: Any, **kwargs: Any) -> PolicyVerdict:
        del args, kwargs
        return PolicyVerdict(Decision.DENY, reason="operator binding denied", rule="test-deny")

    return deny


class _FakeVault:
    """In-memory vault stand-in for the activation error-path tests.

    The fault these tests inject lives at the runtime/policy/HTTP seams, not
    in the vault, so faking the vault keeps them meaningful on runners where
    the age toolchain is absent — notably the quality workflow's coverage
    job, which installs no age and therefore skips every ``_needs_age``
    test (the diff-coverage gate then measures execution paths nothing ran).
    """

    def __init__(self, api_key: str = "sk-groq") -> None:
        self._api_key = api_key

    def has(self, name: str) -> bool:
        assert name == "GROQ_API_KEY"
        return True

    def use(self, name: str, callback: Any) -> Any:
        assert name == "GROQ_API_KEY"
        return callback(self._api_key)


class _HttpOk:
    """Minimal successful gateway JSON response."""

    status_code = 200

    def json(self) -> dict[str, Any]:
        return {"status": "ok"}


@pytest.mark.asyncio
async def test_activate_route_delegates_to_governed_health_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The route supplies canonical scope and never owns the provider call."""
    from services import governed_model

    from maistro.capabilities.effect_context import (
        binding_scope_policy,
        new_in_memory_effect_context,
    )
    from maistro.capabilities.model_chat import ModelCallResult
    from maistro.capabilities.providers.llm_gateway import GatewayEndpoint
    from maistro.projects.scope_store import InMemoryProjectScopeStore
    from maistro.providers.registry import InMemoryProviderRegistry
    from maistro.providers.router import CostAwareRouter
    from maistro.runs.store import InMemoryRunStore

    class _Vault:
        def has(self, name: str) -> bool:
            assert name == "MISTRAL_API_KEY"
            return True

        def use(self, name: str, callback):
            assert name == "MISTRAL_API_KEY"
            return callback("provider-secret")

    class _Root:
        project_id = "root-project"

    scope = InMemoryProjectScopeStore()
    root = await scope.create_root("default")
    run_store = InMemoryRunStore(project_store=scope)

    registry = InMemoryProviderRegistry()
    runtime = governed_model.GovernedModelRuntime(
        # Explicit M1 baseline policy (#846): an omitted policy evaluator now
        # denies rather than defaulting permissive.
        effects=new_in_memory_effect_context(policy_evaluator=binding_scope_policy),
        registry=registry,
        router=CostAwareRouter(registry),
        endpoint=GatewayEndpoint(base_url="http://gateway"),
        project_scope_store=scope,
        run_store=run_store,
    )
    calls: list[dict[str, Any]] = []

    async def health(**kwargs: Any) -> ModelCallResult:
        calls.append(kwargs)
        return ModelCallResult(invocation_id="inv-1", model="mistral/test", body={})

    import config
    import routes.providers as providers_mod

    monkeypatch.setattr(providers_mod, "_vault", lambda: _Vault())
    monkeypatch.setattr(providers_mod, "_record_activation", lambda name: None)
    monkeypatch.setattr(governed_model, "_runtime", lambda: runtime)
    monkeypatch.setattr(governed_model, "register_and_health_check", health)
    settings = type("Settings", (), {"hive_default_workspace_id": "default"})()
    monkeypatch.setattr(config, "get_settings", lambda: settings)

    response = await providers_mod.activate_provider("mistral")

    assert response["first_model_call"]["invocation_id"] == "inv-1"
    assert calls[0]["binding"].project_id == root.project_id
    assert calls[0]["api_key"] == "provider-secret"
    # The activation correlates to a real canonical operation record.
    operation_run = await run_store.get_run(calls[0]["run_id"])
    assert operation_run is not None
    assert operation_run.parent_run_id is None
    assert operation_run.provenance["provider"] == "mistral"
    assert (await run_store.get_node_run(calls[0]["node_run_id"])) is not None
    assert (await run_store.get_attempt(calls[0]["attempt_id"])) is not None
    completed = await run_store.get_run(calls[0]["run_id"])
    assert completed is not None and completed.status.value == "completed"


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
        """An unreachable gateway surfaces as 502 with the operation failed.
        The governed runtime is injected the same way every deployed
        activation has one; the socket alone is pinned unreachable."""
        import httpx
        import routes.providers as providers_mod

        monkeypatch.setattr(providers_mod, "_vault", lambda: _FakeVault())
        _runtime, run_store = _wire_governed_runtime(monkeypatch, endpoint="http://127.0.0.1:9")

        async def refuse(url: str, body: dict[str, Any]) -> Any:
            del url, body
            raise httpx.ConnectError("connection refused")

        calls = _patch_llm_http(monkeypatch, refuse)

        r = admin_client.post("/v1/providers/groq/activate")
        assert r.status_code == 502
        assert "gateway" in r.json()["detail"].lower()
        # Only the registration was attempted; the health call never ran.
        assert [url for url, _ in calls] == ["http://127.0.0.1:9/model/new"]
        # The canonical operation recorded the failure truthfully.
        assert _activation_run(run_store, "failed") is not None

    def test_activate_without_container_is_503(
        self, admin_client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Degraded mode (no core Container on the agent port) is an honest
        503 — the route refuses instead of faking a gateway verdict."""
        import routes.providers as providers_mod

        monkeypatch.setattr(providers_mod, "_vault", lambda: _FakeVault())
        r = admin_client.post("/v1/providers/groq/activate")
        assert r.status_code == 503
        assert "canonical model egress is unavailable" in r.json()["detail"]

    def test_activate_without_scope_authority_is_503(
        self, admin_client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A runtime without the canonical scope tree refuses: activation must
        correlate to a real Workspace/Project, never invent one."""
        import routes.providers as providers_mod

        monkeypatch.setattr(providers_mod, "_vault", lambda: _FakeVault())
        _wire_governed_runtime(monkeypatch, endpoint="http://gateway", project_scope_store=False)
        r = admin_client.post("/v1/providers/groq/activate")
        assert r.status_code == 503
        assert "canonical project scope is unavailable" in r.json()["detail"]

    def test_activate_identity_lookup_failure_is_403(
        self, admin_client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A canonical Run that fails identity correlation is a 403, and no
        operation is minted."""
        import routes.providers as providers_mod
        from services import governed_model

        monkeypatch.setattr(providers_mod, "_vault", lambda: _FakeVault())
        _wire_governed_runtime(monkeypatch, endpoint="http://gateway")

        async def refuse_identity(*args: Any, **kwargs: Any) -> Any:
            del args, kwargs
            raise LookupError("canonical Run 'missing' does not exist")

        monkeypatch.setattr(governed_model, "mint_operation_identity", refuse_identity)
        r = admin_client.post("/v1/providers/groq/activate")
        assert r.status_code == 403
        assert "does not exist" in r.json()["detail"]

    def test_activate_secret_missing_settles_cancelled_409(
        self, admin_client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A vault secret that vanishes mid-activation settles the canonical
        operation as CANCELLED and reports 409 (missing configuration)."""
        import routes.providers as providers_mod

        from maistro.vault import SecretMissingError

        admin_client.put("/v1/providers/groq/key", json={"api_key": "sk-groq"})
        _runtime, run_store = _wire_governed_runtime(monkeypatch, endpoint="http://gateway")

        class _VanishingVault:
            def has(self, name: str) -> bool:
                assert name == "GROQ_API_KEY"
                return True

            def use(self, name: str, callback: Any) -> Any:
                del name, callback
                raise SecretMissingError("GROQ_API_KEY")

        monkeypatch.setattr(providers_mod, "_vault", lambda: _VanishingVault())
        r = admin_client.post("/v1/providers/groq/activate")
        assert r.status_code == 409
        assert "No key stored for 'groq'" in r.json()["detail"]
        assert _activation_run(run_store, "cancelled") is not None

    def test_activate_authorization_failure_is_403(
        self, admin_client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A policy-deny on the health probe settles CANCELLED and surfaces as
        403 — egress denied is an authorization verdict, not a transport one."""
        import routes.providers as providers_mod

        monkeypatch.setattr(providers_mod, "_vault", lambda: _FakeVault())
        _runtime, run_store = _wire_governed_runtime(
            monkeypatch, endpoint="http://gateway", policy_evaluator=_deny_policy()
        )
        r = admin_client.post("/v1/providers/groq/activate")
        assert r.status_code == 403
        assert "authorization failed" in r.json()["detail"].lower()
        assert _activation_run(run_store, "cancelled") is not None

    def test_activate_health_probe_failure_is_502(
        self, admin_client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Registration that succeeds followed by a chat probe that cannot
        reach the gateway is a 502 with the operation settled FAILED."""
        import httpx
        import routes.providers as providers_mod

        monkeypatch.setattr(providers_mod, "_vault", lambda: _FakeVault())
        _runtime, run_store = _wire_governed_runtime(monkeypatch, endpoint="http://gateway")

        async def half_up(url: str, body: dict[str, Any]) -> Any:
            del body
            if url.endswith("/model/new"):
                return _HttpOk()
            raise httpx.ConnectError("gateway dropped after registration")

        calls = _patch_llm_http(monkeypatch, half_up)
        r = admin_client.post("/v1/providers/groq/activate")
        assert r.status_code == 502
        assert [url for url, _ in calls] == [
            "http://gateway/model/new",
            "http://gateway/v1/chat/completions",
        ]
        assert _activation_run(run_store, "failed") is not None

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

        from maistro.capabilities.effect_context import (
            binding_scope_policy,
            new_in_memory_effect_context,
        )
        from maistro.capabilities.providers import llm_gateway
        from maistro.capabilities.providers.llm_gateway import GatewayEndpoint
        from maistro.projects.scope_store import InMemoryProjectScopeStore
        from maistro.providers.registry import InMemoryProviderRegistry
        from maistro.providers.router import CostAwareRouter
        from maistro.providers.types import ModelMetadata
        from maistro.runs.model import RunStatus
        from maistro.runs.store import InMemoryRunStore

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

        async def _wire_scope() -> tuple[InMemoryProjectScopeStore, InMemoryRunStore]:
            scope = InMemoryProjectScopeStore()
            await scope.create_root("default")
            return scope, InMemoryRunStore(project_store=scope)

        scope, run_store = asyncio.run(_wire_scope())

        runtime = GovernedModelRuntime(
            # Explicit M1 baseline policy (#846): an omitted policy evaluator
            # now denies rather than defaulting permissive.
            effects=new_in_memory_effect_context(policy_evaluator=binding_scope_policy),
            registry=registry,
            router=CostAwareRouter(registry),
            endpoint=GatewayEndpoint(base_url="http://litellm.test", api_key="master"),
            project_scope_store=scope,
            run_store=run_store,
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

        # The activation's canonical operation terminalized as completed.
        async def _verify_operation() -> None:
            operations = await run_store.list_by_status(RunStatus.COMPLETED, limit=10)
            activation = [
                run
                for run in operations
                if run.provenance.get("operation") == "provider-activation:mistral"
            ]
            assert len(activation) == 1
            node_runs = await run_store.list_node_runs(activation[0].run_id)
            assert node_runs[0].status is RunStatus.COMPLETED

        asyncio.run(_verify_operation())
