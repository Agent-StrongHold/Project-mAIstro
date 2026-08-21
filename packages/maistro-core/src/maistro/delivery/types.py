"""Outbound delivery types (SPEC-251 / ADR-047)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class DeliveryTarget:
    channel: str
    address: str
    config_ref: str | None = None


@dataclass(frozen=True)
class DeliveryPayload:
    text: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DeliveryResult:
    target: DeliveryTarget
    status: Literal["sent", "failed", "dropped"]
    provider_message_id: str | None
    error: str | None
    attempts: int
