"""Tests for conductor agent — top-level orchestrator for engineering tasks."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from pydantic import ValidationError

from maistro.agents.circuit_breaker import (
    CircuitOpenError,
    CircuitState,
    DomainCircuitBank,
    llm_circuits,
    resolve_failure_domain,
)
from maistro.agents.conductor import (
    ConductorCall,
    _admit_call,
    _call_gateway,
    _get_tier_config,
    _is_retryable,
    _parse_json_output,
    _run_with_retry,
    build_conductor,
    run_task,
)
from maistro.agents.types import ConductorOutput, LLMProviderError
from maistro.capabilities.binding_store import BindingResolutionError
from maistro.capabilities.governed_invocation import InvocationApprovalRequired, InvocationDenied
from maistro.capabilities.invocation import (
    CapabilityUnavailable,
    EffectNotApplied,
    UnsafeEffectRetry,
)
from maistro.config.models import DEFAULT_TIERS, Tier
from maistro.credentials.router import CredentialScopeError
from maistro.providers.errors import ModelNotFoundError
from maistro.providers.types import ModelMetadata
from maistro.quota.invocation_quota import InvocationQuotaDenied
from maistro.runs.store import RunIntegrityError
from maistro.tasks.models import TaskCreate


@pytest.fixture(autouse=True)
def _dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run all conductor tests in dry-run mode unless explicitly disabled."""
    monkeypatch.setenv("MAISTRO_DRY_RUN", "1")


@pytest.fixture(autouse=True)
def _reset_circuit() -> None:
    llm_circuits.reset()


def _admitted_composition(base_url: str | None = "http://gw") -> SimpleNamespace:
    """Explicit target for pure retry/circuit tests whose completion is stubbed.

    The real preflight still resolves the pin and endpoint. This fixture owns
    no physical completion; persisted admission and HTTP remain covered by
    test_conductor_admission.py.
    """
    return SimpleNamespace(
        pinned_model=AsyncMock(return_value=""),
        gateway_base_url=base_url,
    )


def _patched_client(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    # Retry/circuit/prompt unit tests stub the admitted-call seam. Physical
    # transport and admission are exercised in test_conductor_admission.py.
    async def completion(call: ConductorCall, prompt: str, max_tokens: int, *_: Any) -> str:
        request = httpx.Request(
            "POST",
            "http://gw/chat/completions",
            json={
                "model": call.model,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": call.system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "response_format": {"type": "json_object"},
            },
        )
        try:
            response = handler(request)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise EffectNotApplied("fixture proved no dispatch") from exc
        response.request = request
        response.raise_for_status()
        return str(response.json()["choices"][0]["message"]["content"])

    monkeypatch.setattr("maistro.agents.conductor._call_gateway", completion)


class TestConductorDryRun:
    async def test_returns_structured_output(self) -> None:
        task = TaskCreate(description="Add hello world endpoint")
        result = await run_task(task)
        assert result.success is True
        assert result.plan is not None
        assert len(result.plan.subtasks) > 0
        assert "DRY RUN" in result.final_answer

    async def test_respects_workspace(self) -> None:
        task = TaskCreate(
            description="Fix bug",
            workspace="/repos/test-repo",
        )
        result = await run_task(task)
        assert result.success is True

    async def test_handles_constraints(self) -> None:
        task = TaskCreate(
            description="Implement auth",
            constraints=["Use bcrypt", "Add tests"],
        )
        result = await run_task(task)
        assert result.success is True


class TestGetTierConfig:
    def test_known_tier_returns_matching_config(self) -> None:
        config = _get_tier_config(Tier.THOROUGH.value)
        assert config.tier == Tier.THOROUGH

    def test_none_tier_defaults_to_standard(self) -> None:
        config = _get_tier_config(None)
        assert config.tier == Tier.STANDARD

    def test_unknown_tier_value_defaults_to_standard(self) -> None:
        config = _get_tier_config(999)
        assert config.tier == Tier.STANDARD

    def test_zero_tier_defaults_to_standard(self) -> None:
        config = _get_tier_config(0)
        assert config.tier == Tier.STANDARD


class TestBuildConductor:
    def test_uses_master_key_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LITELLM_MASTER_KEY", "secret")
        call = build_conductor(model="openai:gpt-4", base_url="http://gw")
        assert call.api_key == "secret"
        assert call.model == "gpt-4"
        assert call.base_url == "http://gw"

    def test_falls_back_to_ollama_key_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)
        call = build_conductor()
        assert call.api_key == "ollama"

    def test_defaults_model_when_none(self) -> None:
        call = build_conductor()
        assert call.model == "maistro-default"

    def test_system_prompt_includes_json_schema(self) -> None:
        call = build_conductor()
        assert "MUST respond with valid JSON" in call.system_prompt


class TestCallGateway:
    @pytest.mark.parametrize("base_url", [None, "http://gw"])
    async def test_missing_admitted_calls_fails_closed(self, base_url: str | None) -> None:
        call = ConductorCall(model="m", base_url=base_url, api_key="key", system_prompt="sys")
        with pytest.raises(LLMProviderError, match="admitted model calls are not configured"):
            await _call_gateway(call, "hi", max_tokens=100, timeout=10)

    async def test_forwards_explicit_identity_and_json_request(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        calls = SimpleNamespace(
            complete=AsyncMock(
                return_value=SimpleNamespace(body={"choices": [{"message": {"content": "{}"}}]})
            )
        )
        call = ConductorCall(model="m", base_url=None, api_key="", system_prompt="sys")
        result = await _call_gateway(
            call,
            "do thing",
            max_tokens=512,
            timeout=10,
            admitted_calls=calls,  # type: ignore[arg-type]
            invocation_identity=("run", "node", "attempt"),
            invocation_number=2,
        )
        kwargs = calls.complete.await_args.kwargs
        assert result == "{}"
        assert kwargs["identity"] == ("run", "node", "attempt")
        assert kwargs["timeout_s"] == 10
        assert kwargs["effect_key"] == "conductor-llm-2"
        assert kwargs["request"].model == "m"
        assert kwargs["request"].max_tokens == 512
        assert kwargs["request"].response_format == {"type": "json_object"}
        assert kwargs["request"].messages == [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "do thing"},
        ]

    async def test_missing_identity_is_resolved_by_admitted_calls(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        calls = SimpleNamespace(
            complete=AsyncMock(
                return_value=SimpleNamespace(body={"choices": [{"message": {"content": "{}"}}]})
            )
        )
        await _call_gateway(
            build_conductor(),
            "hi",
            max_tokens=100,
            timeout=10,
            admitted_calls=calls,  # type: ignore[arg-type]
        )
        assert calls.complete.await_args.kwargs["identity"] is None

    async def test_legacy_response_hook_cannot_authorize_raw_http(self) -> None:
        from unittest.mock import Mock

        hook = Mock()
        with pytest.raises(LLMProviderError, match="admitted model calls are not configured"):
            await _call_gateway(
                build_conductor(base_url="http://gw"), "hi", 100, 10, on_response=hook
            )
        hook.assert_not_called()


class TestIsRetryable:
    def test_timeout_error_is_not_retryable(self) -> None:
        assert _is_retryable(TimeoutError()) is False

    def test_raw_connect_error_requires_non_dispatch_proof(self) -> None:
        assert _is_retryable(httpx.ConnectError("boom")) is False

    def test_raw_connect_timeout_requires_non_dispatch_proof(self) -> None:
        # ConnectTimeout is not a TimeoutError subclass in httpx 0.28.x;
        # mirror llm_gateway.py, which treats both as an unreachable gateway.
        assert _is_retryable(httpx.ConnectTimeout("timed out")) is False

    def test_transient_status_is_not_proof_of_no_effect(self) -> None:
        request = httpx.Request("GET", "http://x")
        response = httpx.Response(503, request=request)
        exc = httpx.HTTPStatusError("err", request=request, response=response)
        assert _is_retryable(exc) is False

    def test_non_retryable_status_code_is_not_retryable(self) -> None:
        request = httpx.Request("GET", "http://x")
        response = httpx.Response(400, request=request)
        exc = httpx.HTTPStatusError("err", request=request, response=response)
        assert _is_retryable(exc) is False

    def test_json_decode_error_is_retryable(self) -> None:
        try:
            json.loads("not json")
        except json.JSONDecodeError as exc:
            assert _is_retryable(exc, response_completed=True) is True
            assert _is_retryable(exc) is False

    def test_validation_error_is_retryable(self) -> None:
        try:
            ConductorOutput.model_validate({"plan": "not-a-dict-of-plan-output"})
        except ValidationError as exc:
            assert _is_retryable(exc, response_completed=True) is True
            assert _is_retryable(exc) is False

    def test_key_error_is_not_retryable(self) -> None:
        assert _is_retryable(KeyError("missing")) is False

    def test_proven_not_applied_is_retryable(self) -> None:
        assert _is_retryable(EffectNotApplied("no dispatch")) is True

    def test_other_exception_is_not_retryable(self) -> None:
        assert _is_retryable(ValueError("nope")) is False


class TestParseJsonOutput:
    def test_parses_valid_json(self) -> None:
        result = _parse_json_output('{"success": true, "final_answer": "done"}')
        assert result.success is True
        assert result.final_answer == "done"

    def test_raises_on_invalid_json(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            _parse_json_output("not json")


class TestRunWithRetry:
    @pytest.mark.parametrize(
        "refusal",
        [
            BindingResolutionError,
            InvocationDenied,
            InvocationApprovalRequired,
            InvocationQuotaDenied,
            CredentialScopeError,
            CapabilityUnavailable,
            UnsafeEffectRetry,
            RunIntegrityError,
        ],
    )
    async def test_admission_refusal_does_not_retry_or_penalize_provider(
        self, monkeypatch: pytest.MonkeyPatch, refusal: type[Exception]
    ) -> None:
        calls = 0

        async def refuse(*_args: object, **_kwargs: object) -> str:
            nonlocal calls
            calls += 1
            raise refusal("admission refused")

        monkeypatch.setattr("maistro.agents.conductor._call_gateway", refuse)
        call = build_conductor(model="fixture", base_url="http://gateway.fixture")
        circuits = DomainCircuitBank(failure_threshold=1)
        with pytest.raises(refusal):
            await _run_with_retry(
                call,
                "task",
                DEFAULT_TIERS[Tier.STANDARD],
                128,
                circuits=circuits,
                admitted_calls=_admitted_composition(call.base_url),
            )
        assert calls == 1
        assert all(row["state"] == "closed" for row in circuits.snapshot())

    @pytest.mark.asyncio
    async def test_raises_when_circuit_open(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm_circuits, "admit", lambda _domain: False)
        call = ConductorCall(model="m", base_url="http://gw", api_key="key", system_prompt="sys")
        tier_config = DEFAULT_TIERS[Tier.STANDARD]
        with pytest.raises(CircuitOpenError):
            await _run_with_retry(
                call,
                "prompt",
                tier_config,
                max_tokens=100,
                admitted_calls=_admitted_composition(call.base_url),
            )

    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": '{"success": true}'}}]},
            )

        _patched_client(monkeypatch, handler)
        call = ConductorCall(model="m", base_url="http://gw", api_key="key", system_prompt="sys")
        tier_config = DEFAULT_TIERS[Tier.STANDARD]
        result = await _run_with_retry(
            call,
            "prompt",
            tier_config,
            max_tokens=100,
            admitted_calls=_admitted_composition(call.base_url),
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_retries_on_retryable_error_then_succeeds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        attempts = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise httpx.ConnectError("fixture connection failed", request=request)
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": '{"success": true}'}}]},
            )

        _patched_client(monkeypatch, handler)
        monkeypatch.setattr("maistro.agents.conductor.asyncio.sleep", lambda _delay: _noop())
        call = ConductorCall(model="m", base_url="http://gw", api_key="key", system_prompt="sys")
        tier_config = DEFAULT_TIERS[Tier.STANDARD].model_copy(update={"max_llm_retries": 3})
        result = await _run_with_retry(
            call,
            "prompt",
            tier_config,
            max_tokens=100,
            admitted_calls=_admitted_composition(call.base_url),
        )
        assert result.success is True
        assert attempts["count"] == 2

    @pytest.mark.asyncio
    async def test_raises_llm_provider_error_after_exhausting_retries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("fixture connection failed", request=request)

        _patched_client(monkeypatch, handler)
        monkeypatch.setattr("maistro.agents.conductor.asyncio.sleep", lambda _delay: _noop())
        call = ConductorCall(model="m", base_url="http://gw", api_key="key", system_prompt="sys")
        tier_config = DEFAULT_TIERS[Tier.STANDARD].model_copy(update={"max_llm_retries": 2})
        with pytest.raises(LLMProviderError, match="failed after 2 retries"):
            await _run_with_retry(
                call,
                "prompt",
                tier_config,
                max_tokens=100,
                admitted_calls=_admitted_composition(call.base_url),
            )

    @pytest.mark.asyncio
    async def test_raises_immediately_on_non_retryable_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400)

        _patched_client(monkeypatch, handler)
        call = ConductorCall(model="m", base_url="http://gw", api_key="key", system_prompt="sys")
        tier_config = DEFAULT_TIERS[Tier.STANDARD]
        with pytest.raises(httpx.HTTPStatusError):
            await _run_with_retry(
                call,
                "prompt",
                tier_config,
                max_tokens=100,
                admitted_calls=_admitted_composition(call.base_url),
            )

    @pytest.mark.asyncio
    async def test_timeout_error_does_not_retry_ambiguous_outcome(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        attempts = 0

        async def _timeout_call_gateway(*_args: object, **_kwargs: object) -> str:
            nonlocal attempts
            attempts += 1
            raise TimeoutError("too slow")

        monkeypatch.setattr("maistro.agents.conductor._call_gateway", _timeout_call_gateway)
        monkeypatch.setattr("maistro.agents.conductor.asyncio.sleep", lambda _delay: _noop())
        call = ConductorCall(model="m", base_url="http://gw", api_key="key", system_prompt="sys")
        tier_config = DEFAULT_TIERS[Tier.STANDARD].model_copy(update={"max_llm_retries": 2})
        with pytest.raises(TimeoutError):
            await _run_with_retry(
                call,
                "prompt",
                tier_config,
                max_tokens=100,
                admitted_calls=_admitted_composition(call.base_url),
            )

        assert attempts == 1


class TestRunScopedCircuits:
    """#1203: breaker scope follows the call's failure domain, not one flag."""

    @staticmethod
    def _call(model: str, base_url: str = "http://gw") -> ConductorCall:
        return ConductorCall(model=model, base_url=base_url, api_key="key", system_prompt="sys")

    @pytest.mark.asyncio
    async def test_failing_provider_does_not_block_healthy_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.read())
            if body["model"] == "flaky-model":
                return httpx.Response(503)
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": '{"success": true}'}}]},
            )

        _patched_client(monkeypatch, handler)
        monkeypatch.setattr("maistro.agents.conductor.asyncio.sleep", lambda _delay: _noop())
        tier_config = DEFAULT_TIERS[Tier.STANDARD].model_copy(update={"max_llm_retries": 3})

        flaky = self._call("flaky-model")
        for _ in range(llm_circuits.failure_threshold):
            with pytest.raises(httpx.HTTPStatusError):
                await _run_with_retry(
                    flaky,
                    "p",
                    tier_config,
                    max_tokens=100,
                    admitted_calls=_admitted_composition(flaky.base_url),
                )

        # Separate failed calls open only this provider domain.
        flaky_domain = resolve_failure_domain("flaky-model", "http://gw")
        assert llm_circuits.breaker(flaky_domain).state is CircuitState.OPEN

        # The healthy provider on the same gateway still admits and succeeds.
        healthy = self._call("healthy-model")
        result = await _run_with_retry(
            healthy,
            "p",
            tier_config,
            max_tokens=100,
            admitted_calls=_admitted_composition(healthy.base_url),
        )
        assert result.success is True
        healthy_domain = resolve_failure_domain("healthy-model", "http://gw")
        assert llm_circuits.breaker(healthy_domain).state is CircuitState.CLOSED

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "exc",
        [
            httpx.ConnectError("connection refused"),
            httpx.ConnectTimeout("connect timed out"),
        ],
    )
    async def test_shared_gateway_failure_blocks_every_provider_behind_it(
        self, monkeypatch: pytest.MonkeyPatch, exc: Exception
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise exc

        _patched_client(monkeypatch, handler)
        monkeypatch.setattr("maistro.agents.conductor.asyncio.sleep", lambda _delay: _noop())
        tier_config = DEFAULT_TIERS[Tier.STANDARD].model_copy(update={"max_llm_retries": 3})

        for model in ("model-a", "model-b"):
            with pytest.raises(LLMProviderError):
                await _run_with_retry(
                    self._call(model),
                    "p",
                    tier_config,
                    max_tokens=100,
                    admitted_calls=_admitted_composition(self._call(model).base_url),
                )

        # ConnectError/ConnectTimeout are explicit shared-dependency
        # failures: the gateway-level breaker represents them for both
        # providers.
        for model in ("model-a", "model-b"):
            with pytest.raises(CircuitOpenError):
                await _run_with_retry(
                    self._call(model),
                    "p",
                    tier_config,
                    max_tokens=100,
                    admitted_calls=_admitted_composition(self._call(model).base_url),
                )
        # ...while the provider-level breakers stayed closed (not their fault).
        gw_domain = resolve_failure_domain("model-a", "http://gw")
        assert llm_circuits.breaker(gw_domain).state is CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_router_fallback_selects_healthy_alternative(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        requested: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.read())
            requested.append(body["model"])
            if body["model"] == "flaky-model":
                return httpx.Response(503)
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": '{"success": true}'}}]},
            )

        _patched_client(monkeypatch, handler)
        monkeypatch.setattr("maistro.agents.conductor.asyncio.sleep", lambda _delay: _noop())
        tier_config = DEFAULT_TIERS[Tier.STANDARD].model_copy(update={"max_llm_retries": 3})

        flaky = self._call("flaky-model")
        for _ in range(llm_circuits.failure_threshold):
            with pytest.raises(httpx.HTTPStatusError):
                await _run_with_retry(
                    flaky,
                    "p",
                    tier_config,
                    max_tokens=100,
                    admitted_calls=_admitted_composition(flaky.base_url),
                )

        class _Router:
            """Registry-declared chain: flaky-model falls back to healthy-model."""

            async def fallback_chain(self, name: str) -> list[ModelMetadata]:
                assert name == "flaky-model"
                return [
                    ModelMetadata(
                        name="flaky-model",
                        provider="flaky-inc",
                        cost_per_1k_input=0,
                        cost_per_1k_output=0,
                        latency_p50_ms=1,
                    ),
                    ModelMetadata(
                        name="healthy-model",
                        provider="healthy-inc",
                        cost_per_1k_input=0,
                        cost_per_1k_output=0,
                        latency_p50_ms=2,
                    ),
                ]

        result = await _run_with_retry(
            flaky,
            "p",
            tier_config,
            max_tokens=100,
            router=_Router(),
            admitted_calls=_admitted_composition(flaky.base_url),
        )
        assert result.success is True
        assert requested[-1] == "healthy-model"

    @pytest.mark.asyncio
    async def test_blocked_domain_without_router_raises_circuit_open(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        _patched_client(monkeypatch, handler)
        monkeypatch.setattr("maistro.agents.conductor.asyncio.sleep", lambda _delay: _noop())
        tier_config = DEFAULT_TIERS[Tier.STANDARD].model_copy(update={"max_llm_retries": 3})
        call = self._call("flaky-model")
        for _ in range(llm_circuits.failure_threshold):
            with pytest.raises(httpx.HTTPStatusError):
                await _run_with_retry(
                    call,
                    "p",
                    tier_config,
                    max_tokens=100,
                    admitted_calls=_admitted_composition(call.base_url),
                )
        with pytest.raises(CircuitOpenError, match="flaky-model"):
            await _run_with_retry(
                call,
                "p",
                tier_config,
                max_tokens=100,
                admitted_calls=_admitted_composition(call.base_url),
            )

    @pytest.mark.asyncio
    async def test_router_unknown_model_fails_closed_naming_the_blocked_domain(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A router that cannot resolve the model is not a fallback path.

        The registry raising ModelNotFoundError must degrade to the same
        fail-fast CircuitOpenError as having no router at all — never to an
        unhandled error, and never to silently widening the call.
        """

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        _patched_client(monkeypatch, handler)
        monkeypatch.setattr("maistro.agents.conductor.asyncio.sleep", lambda _delay: _noop())
        tier_config = DEFAULT_TIERS[Tier.STANDARD].model_copy(update={"max_llm_retries": 3})

        class _UnknownModelRouter:
            async def fallback_chain(self, name: str) -> list[ModelMetadata]:
                raise ModelNotFoundError(name)

        call = self._call("flaky-model")
        for _ in range(llm_circuits.failure_threshold):
            with pytest.raises(httpx.HTTPStatusError):
                await _run_with_retry(
                    call,
                    "p",
                    tier_config,
                    max_tokens=100,
                    admitted_calls=_admitted_composition(call.base_url),
                )
        with pytest.raises(CircuitOpenError, match="provider=flaky-model"):
            await _run_with_retry(
                call,
                "p",
                tier_config,
                max_tokens=100,
                router=_UnknownModelRouter(),
                admitted_calls=_admitted_composition(call.base_url),
            )

    @pytest.mark.asyncio
    async def test_fallback_chain_exhaustion_fails_closed_on_primary_domain(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Every fallback candidate blocked: the call fails fast naming the
        requested domain rather than retrying into a known-open breaker."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        _patched_client(monkeypatch, handler)
        monkeypatch.setattr("maistro.agents.conductor.asyncio.sleep", lambda _delay: _noop())
        tier_config = DEFAULT_TIERS[Tier.STANDARD].model_copy(update={"max_llm_retries": 3})

        for model in ("flaky-model", "sibling-model"):
            for _ in range(llm_circuits.failure_threshold):
                with pytest.raises(httpx.HTTPStatusError):
                    await _run_with_retry(
                        self._call(model),
                        "p",
                        tier_config,
                        max_tokens=100,
                        admitted_calls=_admitted_composition(self._call(model).base_url),
                    )

        class _ExhaustedRouter:
            """Registry chain: flaky-model -> sibling-model, itself blocked."""

            async def fallback_chain(self, name: str) -> list[ModelMetadata]:
                assert name == "flaky-model"
                return [
                    ModelMetadata(
                        name="sibling-model",
                        provider="sibling-model",
                        cost_per_1k_input=0,
                        cost_per_1k_output=0,
                        latency_p50_ms=1,
                    )
                ]

        with pytest.raises(CircuitOpenError, match="provider=flaky-model"):
            await _run_with_retry(
                self._call("flaky-model"),
                "p",
                tier_config,
                max_tokens=100,
                router=_ExhaustedRouter(),
                admitted_calls=_admitted_composition(self._call("flaky-model").base_url),
            )

    @pytest.mark.asyncio
    async def test_domain_recovering_during_fallback_resolution_proceeds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The admission re-check absorbs the recovery race (#1203).

        The domain was open when admission started, and recovered (crossed
        its recovery timeout, entering HALF_OPEN) while the fallback chain
        was resolving and admitted no candidate. The re-check must lease the
        recovery probe and proceed on the ORIGINAL call — the fallback chain
        is a detour, not a rerouting mandate.
        """
        bank = DomainCircuitBank(failure_threshold=1, recovery_timeout=0.05)
        call = self._call("flaky-model")
        domain = resolve_failure_domain(model=call.model, base_url=call.base_url)
        bank.record_failure(domain)  # opens the provider breaker
        assert not bank.admit(domain)

        class _SlowEmptyRouter:
            async def fallback_chain(self, name: str) -> list[ModelMetadata]:
                await asyncio.sleep(0.1)  # recovery timeout elapses meanwhile
                return []  # no candidate admits: _admitted_fallback_call -> None

        admitted, admitted_domain = await _admit_call(call, bank, _SlowEmptyRouter())
        assert admitted is call
        assert admitted_domain.key() == domain.key()
        # The probe lease was taken by this caller, per-domain.
        assert bank.breaker(domain).state is CircuitState.HALF_OPEN


async def _noop() -> None:
    return None


class TestRunTaskLive:
    async def test_calls_gateway_when_not_dry_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAISTRO_DRY_RUN", "0")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": '{"success": true, "final_answer": "ok"}'}}]
                },
            )

        _patched_client(monkeypatch, handler)
        with patch(
            "maistro.agents.conductor.resolve_model",
            return_value=("m", "http://gw", False),
        ):
            task = TaskCreate(description="Implement feature")
            result = await run_task(task, admitted_calls=_admitted_composition())
        assert result.success is True
        assert result.final_answer == "ok"

    async def test_no_constraints_uses_none_placeholder(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAISTRO_DRY_RUN", "0")
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.read())
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": '{"success": true}'}}]},
            )

        _patched_client(monkeypatch, handler)
        with patch(
            "maistro.agents.conductor.resolve_model",
            return_value=("m", "http://gw", False),
        ):
            task = TaskCreate(description="Implement feature")
            await run_task(task, admitted_calls=_admitted_composition())
        body = captured["body"]
        user_msg = body["messages"][1]["content"]  # type: ignore[index]
        assert "Constraints:\nNone" in user_msg

    async def test_unconfigured_run_task_refuses_before_http(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAISTRO_DRY_RUN", "0")
        with pytest.raises(
            LLMProviderError, match="conductor requires admitted model-call authority"
        ):
            await run_task(TaskCreate(description="Implement feature"))


class TestGovernedCompletionGuards:
    """The governed gateway path must fail loudly on unusable bodies (#718).

    A governed completion is the canonical Invocation's physical call; a
    200 whose body carries no choices (or no message content) is provider
    breakage, not an empty answer -- returning "" would terminalize the
    Invocation as a successful zero-content call and record usage evidence
    for a response the conductor never received.
    """

    async def test_no_choices_is_a_provider_error(self) -> None:
        from types import SimpleNamespace

        from maistro.agents.conductor import ConductorCall, _governed_completion

        call = ConductorCall(model="m", base_url="http://gw", api_key="k", system_prompt="s")

        class _Egress:
            async def complete(self, **kwargs: object) -> SimpleNamespace:
                return SimpleNamespace(body={"model": "m", "choices": []})

        with pytest.raises(LLMProviderError, match="no choices"):
            await _governed_completion(
                call,
                "user prompt",
                128,
                _Egress(),  # type: ignore[arg-type]
                ("run-1", "node-1", "attempt-1"),
                1,
            )

    async def test_no_content_is_a_provider_error(self) -> None:
        from types import SimpleNamespace

        from maistro.agents.conductor import ConductorCall, _governed_completion

        call = ConductorCall(model="m", base_url="http://gw", api_key="k", system_prompt="s")

        class _Egress:
            async def complete(self, **kwargs: object) -> SimpleNamespace:
                return SimpleNamespace(body={"model": "m", "choices": [{"message": {}}]})

        with pytest.raises(LLMProviderError, match="no content"):
            await _governed_completion(
                call,
                "user prompt",
                128,
                _Egress(),  # type: ignore[arg-type]
                ("run-1", "node-1", "attempt-1"),
                1,
            )
