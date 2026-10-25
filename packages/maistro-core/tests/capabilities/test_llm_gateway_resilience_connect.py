"""Diff-coverage closers for #2318 gateway resilience helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from maistro.capabilities.providers.llm_gateway import (
    LlmGatewayProvider,
    LlmHttpError,
    ModelChatRequest,
    _adapter_response_body,
    _chat_payload,
    _note_context_outcome,
    _raise_if_gateway_rate_limited,
    _record_gateway_rate_limit,
    _resolved_max_tokens,
    reset_gateway_resilience_state,
)
from maistro.providers.types import ModelMetadata
from maistro.resilience.context_probe import ContextProbe


@pytest.fixture(autouse=True)
def _reset_gateway_singletons() -> Any:
    reset_gateway_resilience_state()
    yield
    reset_gateway_resilience_state()


def test_resolved_max_tokens_caps_explicit_against_known_window() -> None:
    provider = LlmGatewayProvider(
        ModelMetadata(
            name="m1",
            provider="test",
            cost_per_1k_input=0.0,
            cost_per_1k_output=0.0,
            latency_p50_ms=10,
            max_tokens=100,
        ),
        model="m1",
    )
    from maistro.capabilities.providers import llm_gateway as gw

    gw._CONTEXT_PROBE.set_known_length("m1", 100)
    capped = _resolved_max_tokens(provider, ModelChatRequest(messages=[], max_tokens=500))
    assert capped == 100


def test_resolved_max_tokens_keeps_explicit_when_under_known() -> None:
    provider = LlmGatewayProvider(None, model="m1")
    from maistro.capabilities.providers import llm_gateway as gw

    gw._CONTEXT_PROBE.set_known_length("m1", 8_000)
    assert _resolved_max_tokens(provider, ModelChatRequest(messages=[], max_tokens=128)) == 128


def test_chat_payload_omits_max_tokens_when_caller_omits() -> None:
    payload = _chat_payload(
        LlmGatewayProvider(None, model="m1"),
        ModelChatRequest(messages=[{"role": "user", "content": "hi"}]),
    )
    assert "max_tokens" not in payload


def test_record_gateway_rate_limit_parses_retry_after_and_falls_back() -> None:
    from maistro.capabilities.providers import llm_gateway as gw

    _record_gateway_rate_limit(SimpleNamespace(headers={"Retry-After": "1.5"}))
    assert gw._GATEWAY_RATE_LIMITS.is_rate_limited(gw._GATEWAY_RATE_LIMIT_SCOPE)

    reset_gateway_resilience_state()
    _record_gateway_rate_limit(SimpleNamespace(headers={"Retry-After": "not-a-float"}))
    assert gw._GATEWAY_RATE_LIMITS.is_rate_limited(gw._GATEWAY_RATE_LIMIT_SCOPE)

    reset_gateway_resilience_state()
    _record_gateway_rate_limit(SimpleNamespace())  # no headers attr → 60s default
    assert gw._GATEWAY_RATE_LIMITS.is_rate_limited(gw._GATEWAY_RATE_LIMIT_SCOPE)


def test_raise_if_gateway_rate_limited_fails_closed() -> None:
    from maistro.capabilities.providers import llm_gateway as gw

    _raise_if_gateway_rate_limited()  # noop when clear
    gw._GATEWAY_RATE_LIMITS.record_rate_limit(gw._GATEWAY_RATE_LIMIT_SCOPE, 9_999_999_999.0)
    with pytest.raises(LlmHttpError, match="llm_rate_limited") as excinfo:
        _raise_if_gateway_rate_limited()
    assert excinfo.value.status_code == 429


def test_note_context_outcome_records_overflow_and_success_clear() -> None:
    from maistro.capabilities.providers import llm_gateway as gw

    overflow = SimpleNamespace(status_code=400, text="context length maximum tokens exceeded")
    _note_context_outcome("m1", overflow, requested_tokens=2048)
    assert gw._CONTEXT_PROBE.get_context_length("m1") is not None

    # Unreadable body still exercises the except path without recording.
    class _BadText:
        status_code = 400

        @property
        def text(self) -> str:
            raise RuntimeError("no body")

    _note_context_outcome("m2", _BadText(), requested_tokens=10)

    gw._GATEWAY_RATE_LIMITS.record_rate_limit(gw._GATEWAY_RATE_LIMIT_SCOPE, 9_999_999_999.0)
    ok = SimpleNamespace(status_code=200, text="ok")
    _note_context_outcome("m1", ok, requested_tokens=64)
    assert not gw._GATEWAY_RATE_LIMITS.is_rate_limited(gw._GATEWAY_RATE_LIMIT_SCOPE)


def test_adapter_response_body_rejects_non_object_normalized() -> None:
    class _Adapter:
        def normalize_response(self, body: dict[str, object]) -> list[str]:
            return ["not-a-dict"]

        def map_error(self, status: int) -> Exception:
            return RuntimeError(f"status={status}")

    provider = SimpleNamespace(spec=object(), adapter=_Adapter())
    response = SimpleNamespace(status_code=200, json=lambda: {"ok": True})
    with pytest.raises(RuntimeError, match="non-object body"):
        _adapter_response_body(provider, response)


def test_context_probe_type_alias_stays_importable() -> None:
    """Keep ContextProbe on the gateway import edge for CONNECT."""
    assert isinstance(ContextProbe(), ContextProbe)
