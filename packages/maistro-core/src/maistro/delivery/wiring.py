"""Process composition for the outbound delivery gateway (#2312 / ADR-047)."""

from __future__ import annotations

from maistro.delivery.dispatch import dispatch
from maistro.delivery.protocols import ChannelHealth
from maistro.delivery.registry import ChannelRegistry
from maistro.delivery.types import DeliveryPayload, DeliveryResult, DeliveryTarget

_process_registry: ChannelRegistry | None = None


class LogChannel:
    """Process-local channel that records a send without leaving the host.

    Ships as the default so ``dispatch`` has a real Channel on the process
    registry without requiring ops to wire Slack/email first (#2312).
    """

    name = "log"

    async def send(self, target: DeliveryTarget, payload: DeliveryPayload) -> DeliveryResult:
        return DeliveryResult(
            target=target,
            status="sent",
            provider_message_id=f"log:{target.address}",
            error=None,
            attempts=1,
        )

    async def health(self) -> ChannelHealth:
        return ChannelHealth(healthy=True, detail="process log channel")


def wire_process_delivery_gateway(
    registry: ChannelRegistry | None = None,
) -> ChannelRegistry:
    """Build the process ChannelRegistry and install the default log channel.

    Called from ``create_container`` so ``maistro.delivery*`` is reachable from
    the composition root. Callers that need a real provider register additional
    channels on the returned registry (or replace the process default via
    :func:`configure_process_delivery_registry`).
    """
    selected = registry if registry is not None else ChannelRegistry()
    if "log" not in selected.list_channels():
        selected.register(LogChannel())
    configure_process_delivery_registry(selected)
    # Touch dispatch so the idempotent send path stays on the same import edge.
    assert dispatch is not None
    return selected


def configure_process_delivery_registry(registry: ChannelRegistry) -> None:
    """Publish ``registry`` as the process default delivery gateway."""
    global _process_registry
    _process_registry = registry


def get_process_delivery_registry() -> ChannelRegistry:
    """Return the process default registry, wiring one if absent."""
    if _process_registry is None:
        return wire_process_delivery_gateway()
    return _process_registry


async def dispatch_process_delivery(
    target: DeliveryTarget,
    payload: DeliveryPayload,
    *,
    max_attempts: int = 3,
) -> DeliveryResult:
    """Dispatch through the process default registry (#2312)."""
    return await dispatch(
        get_process_delivery_registry(),
        target,
        payload,
        max_attempts=max_attempts,
    )


__all__ = [
    "LogChannel",
    "configure_process_delivery_registry",
    "dispatch_process_delivery",
    "get_process_delivery_registry",
    "wire_process_delivery_gateway",
]
