"""Tests for the outbound delivery gateway dispatch core (SPEC-251 / ADR-047)."""

from __future__ import annotations

import dataclasses
from unittest.mock import AsyncMock, patch

import pytest

from maistro.agents.circuit_breaker import CircuitBreaker
from maistro.delivery.dispatch import dispatch
from maistro.delivery.protocols import ChannelHealth
from maistro.delivery.registry import ChannelRegistry
from maistro.delivery.types import DeliveryPayload, DeliveryResult, DeliveryTarget


class FakeChannel:
    name = "fake"

    def __init__(self, fail_times: int = 0) -> None:
        self.fail_times = fail_times
        self.calls = 0

    async def send(self, target: DeliveryTarget, payload: DeliveryPayload) -> DeliveryResult:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError(f"transient failure #{self.calls}")
        return DeliveryResult(
            target=target, status="sent", provider_message_id="msg-1", error=None, attempts=1
        )

    async def health(self) -> ChannelHealth:
        return ChannelHealth(healthy=True)


def _registry(channel: FakeChannel) -> ChannelRegistry:
    registry = ChannelRegistry()
    registry.register(channel)
    return registry


def _target() -> DeliveryTarget:
    return DeliveryTarget(channel="fake", address="dest")


class TestDispatchSuccess:
    async def test_success_on_first_attempt(self) -> None:
        channel = FakeChannel(fail_times=0)
        result = await dispatch(_registry(channel), _target(), DeliveryPayload(text="hi"))
        assert result.status == "sent"
        assert result.attempts == 1

    async def test_retries_then_succeeds(self) -> None:
        channel = FakeChannel(fail_times=2)
        with patch("maistro.delivery.dispatch.asyncio.sleep", new_callable=AsyncMock) as sleep:
            result = await dispatch(
                _registry(channel), _target(), DeliveryPayload(text="hi"), max_attempts=3
            )
        assert result.status == "sent"
        assert result.attempts == 3
        assert sleep.call_count == 2


class TestDispatchFailure:
    async def test_exhausts_attempts_and_fails(self) -> None:
        channel = FakeChannel(fail_times=99)
        with patch("maistro.delivery.dispatch.asyncio.sleep", new_callable=AsyncMock):
            result = await dispatch(
                _registry(channel), _target(), DeliveryPayload(text="hi"), max_attempts=3
            )
        assert result.status == "failed"
        assert result.attempts == 3
        assert result.error


class TestIdempotency:
    async def test_duplicate_key_drops_without_calling_channel(self) -> None:
        channel = FakeChannel(fail_times=0)
        seen: set[str] = set()
        payload = DeliveryPayload(text="hi", metadata={"task_id": "t1"})
        first = await dispatch(_registry(channel), _target(), payload, seen_keys=seen)
        second = await dispatch(_registry(channel), _target(), payload, seen_keys=seen)
        assert first.status == "sent"
        assert second.status == "dropped"
        assert second.attempts == 0
        assert channel.calls == 1


class TestCircuitBreaker:
    async def test_open_breaker_drops_without_calling_channel(self) -> None:
        channel = FakeChannel(fail_times=0)
        breaker = CircuitBreaker(failure_threshold=1, name="test")
        breaker.record_failure()
        result = await dispatch(
            _registry(channel), _target(), DeliveryPayload(text="hi"), breaker=breaker
        )
        assert result.status == "dropped"
        assert channel.calls == 0


class TestRegistry:
    def test_unknown_channel_raises_key_error(self) -> None:
        registry = ChannelRegistry()
        with pytest.raises(KeyError):
            registry.get("nope")

    def test_list_channels(self) -> None:
        registry = _registry(FakeChannel())
        assert registry.list_channels() == ["fake"]


class TestNoSecretFields:
    def test_no_raw_secret_field_on_delivery_types(self) -> None:
        target_fields = {f.name for f in dataclasses.fields(DeliveryTarget)}
        payload_fields = {f.name for f in dataclasses.fields(DeliveryPayload)}
        result_fields = {f.name for f in dataclasses.fields(DeliveryResult)}
        forbidden = {"secret", "password", "token", "api_key", "credential"}
        assert not (target_fields & forbidden)
        assert not (payload_fields & forbidden)
        assert not (result_fields & forbidden)
