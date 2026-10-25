"""Process delivery gateway wiring (#2312)."""

from __future__ import annotations

import pytest

from maistro.delivery.registry import ChannelRegistry
from maistro.delivery.types import DeliveryPayload, DeliveryTarget
from maistro.delivery.wiring import (
    LogChannel,
    configure_process_delivery_registry,
    dispatch_process_delivery,
    get_process_delivery_registry,
    wire_process_delivery_gateway,
)


@pytest.fixture(autouse=True)
def _reset_process_registry() -> None:
    """Each test starts without a leaked process registry."""
    import maistro.delivery.wiring as wiring

    wiring._process_registry = None
    yield
    wiring._process_registry = None


@pytest.mark.asyncio
async def test_log_channel_send_and_health() -> None:
    channel = LogChannel()
    target = DeliveryTarget(channel="log", address="ops@example.com")
    payload = DeliveryPayload(text="hello")

    result = await channel.send(target, payload)
    assert result.status == "sent"
    assert result.provider_message_id == "log:ops@example.com"
    assert result.attempts == 1

    health = await channel.health()
    assert health.healthy is True
    assert "log" in (health.detail or "")


def test_wire_process_delivery_gateway_registers_log_and_is_process_default() -> None:
    registry = wire_process_delivery_gateway()
    assert "log" in registry.list_channels()
    assert get_process_delivery_registry() is registry


def test_wire_skips_log_registration_when_caller_already_has_log() -> None:
    """Branch 46 False: do not double-register the default log channel."""
    existing = LogChannel()
    preloaded = ChannelRegistry()
    preloaded.register(existing)
    wired = wire_process_delivery_gateway(preloaded)
    assert wired is preloaded
    assert wired.list_channels().count("log") == 1
    assert wired.get("log") is existing


def test_get_process_delivery_registry_wires_when_absent() -> None:
    import maistro.delivery.wiring as wiring

    wiring._process_registry = None
    registry = get_process_delivery_registry()
    assert "log" in registry.list_channels()
    assert wiring._process_registry is registry


def test_configure_process_delivery_registry_replaces_default() -> None:
    custom = ChannelRegistry()
    configure_process_delivery_registry(custom)
    assert get_process_delivery_registry() is custom


@pytest.mark.asyncio
async def test_dispatch_process_delivery_uses_log_channel() -> None:
    wire_process_delivery_gateway()
    result = await dispatch_process_delivery(
        DeliveryTarget(channel="log", address="room-1"),
        DeliveryPayload(text="pong"),
        max_attempts=1,
    )
    assert result.status == "sent"
    assert result.provider_message_id == "log:room-1"
