"""Channel protocol for outbound delivery (SPEC-251 / ADR-047)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from maistro.delivery.types import DeliveryPayload, DeliveryResult, DeliveryTarget


@dataclass(frozen=True)
class ChannelHealth:
    healthy: bool
    detail: str = ""


@runtime_checkable
class Channel(Protocol):
    name: str

    async def send(self, target: DeliveryTarget, payload: DeliveryPayload) -> DeliveryResult: ...

    async def health(self) -> ChannelHealth: ...
