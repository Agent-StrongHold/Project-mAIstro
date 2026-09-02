"""Event bus: compatibility delivery for cross-service triggers.

Services (conductor, CoinSwarm, Turing, HA) historically emit ``Event`` objects
here. Canonical event identity and Workspace ordering now belong to
``EventEnvelope``; this bus remains a compatibility consumer and may accept a
domain fact only when that fact explicitly projects itself to legacy ``Event``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol
from uuid import uuid4

logger = logging.getLogger("maistro.events")


class EventCategory(StrEnum):
    TRADING = "trading"
    SMART_HOME = "smart_home"
    AGENT = "agent"
    SYSTEM = "system"
    TURING = "turing"
    SECURITY = "security"


@dataclass
class Event:
    """Legacy trigger-delivery projection, not canonical Event identity."""

    event_id: str = field(default_factory=lambda: uuid4().hex[:12])
    category: EventCategory = EventCategory.SYSTEM
    event_type: str = ""
    source: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    correlation_id: str = ""


class LegacyEventProjector(Protocol):
    """Domain fact that can be projected onto the legacy trigger bus."""

    def to_legacy_event(self) -> Event: ...


@dataclass
class TriggerCondition:
    field: str
    op: str = "eq"
    value: Any = None

    def matches(self, payload: dict[str, Any]) -> bool:
        actual = payload.get(self.field)
        if actual is None:
            return False
        if self.op == "eq":
            return bool(actual == self.value)
        if self.op == "ne":
            return bool(actual != self.value)
        if self.op == "gt":
            return float(actual) > float(self.value)
        if self.op == "lt":
            return float(actual) < float(self.value)
        if self.op == "gte":
            return float(actual) >= float(self.value)
        if self.op == "lte":
            return float(actual) <= float(self.value)
        if self.op == "contains":
            return str(self.value) in str(actual)
        if self.op == "regex":
            import re

            return bool(re.search(str(self.value), str(actual)))
        return False


@dataclass
class Trigger:
    trigger_id: str = field(default_factory=lambda: uuid4().hex[:8])
    name: str = ""
    event_types: list[str] = field(default_factory=list)
    conditions: list[TriggerCondition] = field(default_factory=list)
    action_type: str = "webhook"
    action_config: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    fire_count: int = 0
    last_fired: float | None = None
    cooldown_seconds: float = 60.0

    def matches(self, event: Event) -> bool:
        if not self.enabled:
            return False
        if self.event_types and event.event_type not in self.event_types:
            return False
        if self.last_fired and (time.time() - self.last_fired) < self.cooldown_seconds:
            return False
        return all(c.matches(event.payload) for c in self.conditions)


ActionHandler = Callable[[Trigger, Event], Coroutine[Any, Any, None]]


def _project_legacy_event(event: Event | LegacyEventProjector) -> Event:
    """Return the trigger-bus projection without treating it as canonical."""
    if isinstance(event, Event):
        return event
    projector = getattr(event, "to_legacy_event", None)
    if not callable(projector):
        raise TypeError("legacy EventBus requires Event or explicit to_legacy_event() projection")
    projected = projector()
    if not isinstance(projected, Event):
        raise TypeError("to_legacy_event() must return maistro.events.bus.Event")
    return projected


class EventBus:
    """In-memory compatibility event bus with trigger matching."""

    def __init__(self, max_history: int = 1000) -> None:
        self._triggers: list[Trigger] = []
        self._handlers: dict[str, ActionHandler] = {}
        self._history: list[Event] = []
        self._max_history = max_history
        self._subscribers: list[Callable[[Event], Coroutine[Any, Any, None]]] = []

    def register_handler(self, action_type: str, handler: ActionHandler) -> None:
        self._handlers[action_type] = handler

    def add_trigger(self, trigger: Trigger) -> None:
        self._triggers.append(trigger)

    def remove_trigger(self, trigger_id: str) -> None:
        self._triggers = [t for t in self._triggers if t.trigger_id != trigger_id]

    def subscribe(self, callback: Callable[[Event], Coroutine[Any, Any, None]]) -> None:
        self._subscribers.append(callback)

    async def emit(self, event: Event | LegacyEventProjector) -> list[Trigger]:
        projected = _project_legacy_event(event)
        self._history.append(projected)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history :]

        fired: list[Trigger] = []
        for trigger in self._triggers:
            try:
                matched = trigger.matches(projected)
            except Exception:
                logger.exception(
                    "Trigger %s match evaluation failed for event %s",
                    trigger.trigger_id,
                    projected.event_id,
                )
                continue
            if matched:
                handler = self._handlers.get(trigger.action_type)
                if handler:
                    try:
                        await handler(trigger, projected)
                    except Exception:
                        logger.exception("Trigger %s action failed", trigger.trigger_id)
                trigger.fire_count += 1
                trigger.last_fired = time.time()
                fired.append(trigger)

        for sub in self._subscribers:
            try:
                await sub(projected)
            except Exception:
                logger.exception("Subscriber failed for event %s", projected.event_id)

        if fired:
            logger.info(
                "Event %s/%s fired %d triggers",
                projected.category,
                projected.event_type,
                len(fired),
            )

        return fired

    def get_history(
        self,
        category: EventCategory | None = None,
        source: str | None = None,
        limit: int = 100,
    ) -> list[Event]:
        result = self._history
        if category:
            result = [e for e in result if e.category == category]
        if source:
            result = [e for e in result if e.source == source]
        return result[-limit:]

    def list_triggers(self) -> list[dict[str, Any]]:
        return [
            {
                "id": t.trigger_id,
                "name": t.name,
                "event_types": t.event_types,
                "action_type": t.action_type,
                "enabled": t.enabled,
                "fire_count": t.fire_count,
                "last_fired": t.last_fired,
            }
            for t in self._triggers
        ]


_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus
