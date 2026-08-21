"""Tests for conductor agent — top-level orchestrator for engineering tasks."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from pydantic import ValidationError

from maistro.agents.circuit_breaker import CircuitOpenError, llm_circuit
from maistro.agents.conductor import (
    ConductorCall,
    _call_gateway,
    _get_tier_config,
    _is_retryable,
    _parse_json_output,
    _run_with_retry,
    build_conductor,
    run_task,
)
from maistro.agents.types import ConductorOutput, LLMProviderError
from maistro.config.models import DEFAULT_TIERS, Tier
from maistro.http import set_test_transport
from maistro.tasks.models import TaskCreate


@pytest.fixture(autouse=True)
def _dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run all conductor tests in dry-run mode unless explicitly disabled."""
    monkeypatch.setenv("MAISTRO_DRY_RUN", "1")


@pytest.fixture(autouse=True)
def _reset_circuit() -> None:
    llm_circuit.record_success()


def _patched_client(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    transport = httpx.MockTransport(handler)
    set_test_transport(transport)


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
    @pytest.mark.asyncio
    async def test_raises_when_base_url_missing(self) -> None:
        call = ConductorCall(model="m", base_url=None, api_key="k", system_prompt="sys")
        with pytest.raises(LLMProviderError, match="no gateway base_url configured"):
            await _call_gateway(call, "hi", max_tokens=100, timeout=10)

    @pytest.mark.asyncio
    async def test_posts_and_returns_content(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["headers"] = dict(request.headers)
            captured["body"] = json.loads(request.read())
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": '{"success": true}'}}]},
            )

        _patched_client(monkeypatch, handler)
        call = ConductorCall(model="m", base_url="http://gw", api_key="key", system_prompt="sys")
        result = await _call_gateway(call, "do thing", max_tokens=512, timeout=10)
        assert result == '{"success": true}'
        assert captured["url"] == "http://gw/chat/completions"
        assert captured["headers"]["authorization"] == "Bearer key"  # type: ignore[index]
        body = captured["body"]
        assert body["model"] == "m"  # type: ignore[index]
        assert body["max_tokens"] == 512  # type: ignore[index]
        assert body["response_format"] == {"type": "json_object"}  # type: ignore[index]

    @pytest.mark.asyncio
    async def test_raises_on_error_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        _patched_client(monkeypatch, handler)
        call = ConductorCall(model="m", base_url="http://gw", api_key="key", system_prompt="sys")
        with pytest.raises(httpx.HTTPStatusError):
            await _call_gateway(call, "do thing", max_tokens=512, timeout=10)

    @pytest.mark.asyncio
    async def test_on_response_hook_receives_body_and_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"x-ratelimit-remaining-requests": "10"},
                json={
                    "choices": [{"message": {"content": '{"success": true}'}}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 7},
                },
            )

        _patched_client(monkeypatch, handler)
        captured: dict[str, object] = {}

        def on_response(data: dict, response: httpx.Response) -> None:
            captured["data"] = data
            captured["headers"] = dict(response.headers)

        call = ConductorCall(model="m", base_url="http://gw", api_key="key", system_prompt="sys")
        result = await _call_gateway(
            call, "do thing", max_tokens=512, timeout=10, on_response=on_response
        )
        assert result == '{"success": true}'
        assert captured["data"]["usage"] == {"prompt_tokens": 5, "completion_tokens": 7}  # type: ignore[index]
        assert captured["headers"]["x-ratelimit-remaining-requests"] == "10"  # type: ignore[index]

    @pytest.mark.asyncio
    async def test_on_response_hook_failure_is_swallowed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"choices": [{"message": {"content": '{"success": true}'}}]}
            )

        def broken_hook(data: dict, response: httpx.Response) -> None:
            raise RuntimeError("recording hook blew up")

        _patched_client(monkeypatch, handler)
        call = ConductorCall(model="m", base_url="http://gw", api_key="key", system_prompt="sys")
        result = await _call_gateway(
            call, "do thing", max_tokens=512, timeout=10, on_response=broken_hook
        )
        assert result == '{"success": true}'


class TestIsRetryable:
    def test_timeout_error_is_retryable(self) -> None:
        assert _is_retryable(TimeoutError()) is True

    def test_connect_error_is_retryable(self) -> None:
        assert _is_retryable(httpx.ConnectError("boom")) is True

    def test_retryable_status_code_is_retryable(self) -> None:
        request = httpx.Request("GET", "http://x")
        response = httpx.Response(503, request=request)
        exc = httpx.HTTPStatusError("err", request=request, response=response)
        assert _is_retryable(exc) is True

    def test_non_retryable_status_code_is_not_retryable(self) -> None:
        request = httpx.Request("GET", "http://x")
        response = httpx.Response(400, request=request)
        exc = httpx.HTTPStatusError("err", request=request, response=response)
        assert _is_retryable(exc) is False

    def test_json_decode_error_is_retryable(self) -> None:
        try:
            json.loads("not json")
        except json.JSONDecodeError as exc:
            assert _is_retryable(exc) is True

    def test_validation_error_is_retryable(self) -> None:
        try:
            ConductorOutput.model_validate({"plan": "not-a-dict-of-plan-output"})
        except ValidationError as exc:
            assert _is_retryable(exc) is True

    def test_key_error_is_retryable(self) -> None:
        assert _is_retryable(KeyError("missing")) is True

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
    @pytest.mark.asyncio
    async def test_raises_when_circuit_open(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm_circuit, "allow_request", lambda: False)
        call = ConductorCall(model="m", base_url="http://gw", api_key="key", system_prompt="sys")
        tier_config = DEFAULT_TIERS[Tier.STANDARD]
        with pytest.raises(CircuitOpenError):
            await _run_with_retry(call, "prompt", tier_config, max_tokens=100)

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
        result = await _run_with_retry(call, "prompt", tier_config, max_tokens=100)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_retries_on_retryable_error_then_succeeds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        attempts = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["count"] += 1
            if attempts["count"] == 1:
                return httpx.Response(503)
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": '{"success": true}'}}]},
            )

        _patched_client(monkeypatch, handler)
        monkeypatch.setattr("maistro.agents.conductor.asyncio.sleep", lambda _delay: _noop())
        call = ConductorCall(model="m", base_url="http://gw", api_key="key", system_prompt="sys")
        tier_config = DEFAULT_TIERS[Tier.STANDARD].model_copy(update={"max_llm_retries": 3})
        result = await _run_with_retry(call, "prompt", tier_config, max_tokens=100)
        assert result.success is True
        assert attempts["count"] == 2

    @pytest.mark.asyncio
    async def test_raises_llm_provider_error_after_exhausting_retries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        _patched_client(monkeypatch, handler)
        monkeypatch.setattr("maistro.agents.conductor.asyncio.sleep", lambda _delay: _noop())
        call = ConductorCall(model="m", base_url="http://gw", api_key="key", system_prompt="sys")
        tier_config = DEFAULT_TIERS[Tier.STANDARD].model_copy(update={"max_llm_retries": 2})
        with pytest.raises(LLMProviderError, match="failed after 2 retries"):
            await _run_with_retry(call, "prompt", tier_config, max_tokens=100)

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
            await _run_with_retry(call, "prompt", tier_config, max_tokens=100)

    @pytest.mark.asyncio
    async def test_timeout_error_is_retried(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _timeout_call_gateway(*_args: object, **_kwargs: object) -> str:
            raise TimeoutError("too slow")

        monkeypatch.setattr("maistro.agents.conductor._call_gateway", _timeout_call_gateway)
        monkeypatch.setattr("maistro.agents.conductor.asyncio.sleep", lambda _delay: _noop())
        call = ConductorCall(model="m", base_url="http://gw", api_key="key", system_prompt="sys")
        tier_config = DEFAULT_TIERS[Tier.STANDARD].model_copy(update={"max_llm_retries": 2})
        with pytest.raises(LLMProviderError):
            await _run_with_retry(call, "prompt", tier_config, max_tokens=100)


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
            result = await run_task(task)
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
            await run_task(task)
        body = captured["body"]
        user_msg = body["messages"][1]["content"]  # type: ignore[index]
        assert "Constraints:\nNone" in user_msg

    async def test_forwards_on_response_hook_to_gateway(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAISTRO_DRY_RUN", "0")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": '{"success": true}'}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 2},
                },
            )

        _patched_client(monkeypatch, handler)
        captured: dict[str, object] = {}

        def on_response(data: dict, response: httpx.Response) -> None:
            captured["data"] = data

        with patch(
            "maistro.agents.conductor.resolve_model",
            return_value=("m", "http://gw", False),
        ):
            task = TaskCreate(description="Implement feature")
            result = await run_task(task, on_response=on_response)
        assert result.success is True
        assert captured["data"]["usage"] == {"prompt_tokens": 1, "completion_tokens": 2}  # type: ignore[index]
