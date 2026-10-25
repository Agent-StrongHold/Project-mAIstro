"""Outbound delivery gateway (SPEC-251 / ADR-047).

Process entry points call :func:`wire_process_delivery_gateway` from
``create_container`` (#2312) so the registry + dispatch path is live.
"""

from maistro.delivery.dispatch import dispatch
from maistro.delivery.protocols import Channel, ChannelHealth
from maistro.delivery.registry import ChannelRegistry
from maistro.delivery.types import DeliveryPayload, DeliveryResult, DeliveryTarget
from maistro.delivery.wiring import (
    LogChannel,
    configure_process_delivery_registry,
    dispatch_process_delivery,
    get_process_delivery_registry,
    wire_process_delivery_gateway,
)

__all__ = [
    "Channel",
    "ChannelHealth",
    "ChannelRegistry",
    "DeliveryPayload",
    "DeliveryResult",
    "DeliveryTarget",
    "LogChannel",
    "configure_process_delivery_registry",
    "dispatch",
    "dispatch_process_delivery",
    "get_process_delivery_registry",
    "wire_process_delivery_gateway",
]
