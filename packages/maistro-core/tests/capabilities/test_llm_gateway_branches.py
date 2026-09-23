"""Branch closers for the one approved model Provider (llm_gateway.py).

Diff coverage on PR #1040 flagged four partial arcs:
- 113 ``if request.tools:`` — payload merges tools only when present;
- 128 ``if not isinstance(body, dict):`` — non-object gateway bodies refuse;
- 145/147 — only gateway providers and governed request shapes may cross
  the seam; foreign types are wiring errors, not silent alternates.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.capabilities.providers.llm_gateway import (
    GatewayEndpoint,
    LlmAuthError,
    LlmGatewayProvider,
    LlmHttpError,
    ModelChatRequest,
    _chat_payload,
    _checked_body,
    execute_model_chat,
)


class _ForeignProvider:
    """Any non-gateway provider handle is a wiring error at this seam."""

    name = "foreign"
    slot = "model.chat"
    trust_tier = "t9"


class _Resp:
    def __init__(self, status_code: int, body: Any) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> Any:
        return self._body


def test_chat_payload_merges_tools_only_when_present() -> None:
    """Arc 113 both ways: tools ride along when set, stay absent otherwise."""

    provider = LlmGatewayProvider(None, model="m1")
    tools: list[dict[str, object]] = [
        {"type": "function", "function": {"name": "lookup", "parameters": {}}}
    ]

    with_tools = _chat_payload(
        provider, ModelChatRequest(messages=[{"role": "user", "content": "hi"}], tools=tools)
    )
    assert with_tools["tools"] == tools  # arc 113 True

    without_tools = _chat_payload(
        provider, ModelChatRequest(messages=[{"role": "user", "content": "hi"}])
    )
    assert "tools" not in without_tools  # arc 113 False
    assert without_tools["model"] == "m1"
    assert without_tools["stream"] is False


def test_checked_body_accepts_object_body() -> None:
    """Arc 128 False: an object body passes through unchanged."""

    body = {"choices": [{"message": {"content": "ok"}}]}
    assert _checked_body(_Resp(200, body)) is body


def test_checked_body_refuses_non_object_body() -> None:
    """Arc 128 True: a JSON array (or scalar) body is refused, not coerced."""

    with pytest.raises(RuntimeError, match="non-object response body"):
        _checked_body(_Resp(200, ["choices"]))
    with pytest.raises(RuntimeError, match="non-object response body"):
        _checked_body(_Resp(200, "ok"))


def test_checked_body_401_carries_status_code_for_credential_routing() -> None:
    """#1079 finding 5: a bare PermissionError could not be classified — the
    CredentialRouter's status extraction (and the resilience classifier's)
    both read ``status_code`` off the exception first, so without it a real
    401 fell through to ErrorCategory.UNKNOWN and never blocked the key."""

    with pytest.raises(LlmAuthError) as excinfo:
        _checked_body(_Resp(401, {}))
    assert excinfo.value.status_code == 401
    assert isinstance(
        excinfo.value, PermissionError
    )  # existing `except PermissionError` still works


def test_checked_body_429_carries_status_code_for_credential_routing() -> None:
    with pytest.raises(LlmHttpError) as excinfo:
        _checked_body(_Resp(429, {}))
    assert excinfo.value.status_code == 429
    assert isinstance(excinfo.value, RuntimeError)  # existing `except RuntimeError` still works


def test_checked_body_other_4xx_carries_status_code_for_credential_routing() -> None:
    with pytest.raises(LlmHttpError) as excinfo:
        _checked_body(_Resp(403, {}))
    assert excinfo.value.status_code == 403


def test_credential_router_blocks_and_cools_on_the_carried_status() -> None:
    """End-to-end proof, not just that the exception carries the attribute:
    the router's own status extraction and cooldown table actually act on it."""

    from maistro.credentials.router import _status_from_error, cooldown_for_failure
    from maistro.resilience.classifier import classify_error

    auth_error = LlmAuthError("llm_auth_failed status=401", status_code=401)
    assert _status_from_error(auth_error) == 401
    classified = classify_error(auth_error)
    cooldown, should_block = cooldown_for_failure(
        classified, status_code=_status_from_error(auth_error)
    )
    assert should_block is True  # 401 blocks the credential permanently

    rate_limit_error = LlmHttpError("llm_rate_limited status=429", status_code=429)
    assert _status_from_error(rate_limit_error) == 429
    classified = classify_error(rate_limit_error)
    cooldown, should_block = cooldown_for_failure(
        classified, status_code=_status_from_error(rate_limit_error)
    )
    assert should_block is False
    assert cooldown > 0  # 429 cools down rather than blocking outright


async def test_foreign_provider_handle_refuses_seam() -> None:
    """Arc 145: a non-gateway provider handle cannot cross the egress seam."""

    with pytest.raises(TypeError, match="non-gateway provider"):
        await execute_model_chat(
            _ForeignProvider(),
            ModelChatRequest(messages=[{"role": "user", "content": "hi"}]),
            endpoint=GatewayEndpoint(base_url="http://gw"),
        )


async def test_foreign_request_shape_refuses_seam() -> None:
    """Arc 147: only governed ModelChatRequest payloads may cross."""

    with pytest.raises(TypeError, match="foreign request"):
        await execute_model_chat(
            LlmGatewayProvider(None, model="m1"),
            {"model": "m1", "messages": []},  # raw dict, not the governed shape
            endpoint=GatewayEndpoint(base_url="http://gw"),
        )
