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


class TriggerActionFailure(Exception):
    """A matched trigger's action handler raised; the emission did not succeed.

    Raised by :meth:`EventBus.emit` after delivery of the event has finished,
    so one failing handler neither aborts the remaining triggers/subscribers nor
    silently advances the trigger's success state. ``failures`` carries every
    ``(trigger, exception)`` pair; the first exception is also set as the
    ``__cause__`` so its traceback stays reachable.
    """

    def __init__(self, failures: list[tuple[Trigger, Exception]]) -> None:
        self.failures = failures
        self.subscriber_failures: list[tuple[Callable[..., Any], Exception]] = []
        detail = "; ".join(
            f"trigger {t.name or t.trigger_id} (action_type={t.action_type!r}): {exc!r}"
            for t, exc in failures
        )
        super().__init__(f"{len(failures)} trigger action handler(s) failed: {detail}")


class EventSubscriberFailure(Exception):
    """A bus subscriber failed; delivery evidence must not be silently lost."""

    def __init__(self, failures: list[tuple[Callable[..., Any], Exception]]) -> None:
        self.failures = failures
        detail = "; ".join(f"{callback!r}: {exc!r}" for callback, exc in failures)
        super().__init__(f"{len(failures)} event subscriber(s) failed: {detail}")


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
        self._subscribers: list[tuple[Callable[[Event], Coroutine[Any, Any, None]], bool]] = []

    def register_handler(self, action_type: str, handler: ActionHandler) -> None:
        self._handlers[action_type] = handler

    def add_trigger(self, trigger: Trigger) -> None:
        self._triggers.append(trigger)

    def remove_trigger(self, trigger_id: str) -> None:
        self._triggers = [t for t in self._triggers if t.trigger_id != trigger_id]

    def subscribe(
        self,
        callback: Callable[[Event], Coroutine[Any, Any, None]],
        *,
        before_handlers: bool = False,
    ) -> None:
        """Register an async subscriber.

        ``before_handlers`` is for authoritative adapters such as the durable
        event-log bridge. A failure there aborts emission before any trigger can
        claim success. Ordinary subscribers remain post-handler notifications.
        """
        self._subscribers.append((callback, before_handlers))

    async def _notify_before_handlers(self, projected: Event) -> None:
        """Run authoritative subscribers before trigger matching."""
        failures: list[tuple[Callable[..., Any], Exception]] = []
        for sub, before_handlers in self._subscribers:
            if not before_handlers:
                continue
            try:
                await sub(projected)
            except Exception as exc:
                logger.exception(
                    "Authoritative event subscriber failed for event %s", projected.event_id
                )
                failures.append((sub, exc))
        if failures:
            raise EventSubscriberFailure(failures) from failures[0][1]

    async def _notify_after_handlers(
        self, projected: Event
    ) -> list[tuple[Callable[..., Any], Exception]]:
        """Run notification subscribers and retain failures for emit."""
        failures: list[tuple[Callable[..., Any], Exception]] = []
        for sub, before_handlers in self._subscribers:
            if before_handlers:
                continue
            try:
                await sub(projected)
            except Exception as exc:
                logger.exception("Subscriber failed for event %s", projected.event_id)
                failures.append((sub, exc))
        return failures

    async def _fire_if_matched(
        self,
        trigger: Trigger,
        projected: Event,
        failures: list[tuple[Trigger, Exception]],
    ) -> Trigger | None:
        """Fire ``trigger`` for ``projected``; return it only on handler success.

        Success state (``fire_count`` / ``last_fired``) is advanced only on the
        path where a registered handler completed without raising. A matched
        trigger with no registered handler is skipped with a warning; a raising
        handler is logged and appended to ``failures`` for ``emit`` to surface.
        """
        try:
            matched = trigger.matches(projected)
        except Exception:
            logger.exception(
                "Trigger %s match evaluation failed for event %s",
                trigger.trigger_id,
                projected.event_id,
            )
            return None
        if not matched:
            return None
        handler = self._handlers.get(trigger.action_type)
        if handler is None:
            logger.warning(
                "Trigger %s matched event %s but no handler is registered for "
                "action_type %r; not counted as fired",
                trigger.trigger_id,
                projected.event_id,
                trigger.action_type,
            )
            return None
        try:
            await handler(trigger, projected)
        except Exception as exc:
            logger.exception("Trigger %s action failed", trigger.trigger_id)
            failures.append((trigger, exc))
            return None
        trigger.fire_count += 1
        trigger.last_fired = time.time()
        return trigger

    async def emit(self, event: Event | LegacyEventProjector) -> list[Trigger]:
        """Deliver ``event``; return only the triggers whose handlers completed.

        A trigger is counted as fired (``fire_count`` / ``last_fired`` / the
        returned list) only when a handler is registered for its
        ``action_type`` **and** that handler completed without raising (#836):

        - a matched trigger with no registered handler is skipped with a
          warning — an unhandled ``action_type`` must not manufacture firing
          evidence or start the cooldown;
        - a raising handler is logged and collected; after the whole event has
          been delivered, :class:`TriggerActionFailure` is raised carrying the
          original exceptions, so handler failure is explicit and cannot
          advance the success cooldown/counters as if the action ran.
        """
        projected = _project_legacy_event(event)
        await self._notify_before_handlers(projected)

        self._history.append(projected)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history :]

        fired: list[Trigger] = []
        failures: list[tuple[Trigger, Exception]] = []
        for trigger in self._triggers:
            fired_trigger = await self._fire_if_matched(trigger, projected, failures)
            if fired_trigger is not None:
                fired.append(fired_trigger)

        subscriber_failures = await self._notify_after_handlers(projected)

        if fired:
            logger.info(
                "Event %s/%s fired %d triggers",
                projected.category,
                projected.event_type,
                len(fired),
            )

        if failures:
            failure = TriggerActionFailure(failures)
            if subscriber_failures:
                # Preserve the established trigger exception type while making
                # a post-handler subscriber failure inspectable as well.
                failure.subscriber_failures = subscriber_failures
            raise failure from failures[0][1]
        if subscriber_failures:
            raise EventSubscriberFailure(subscriber_failures) from subscriber_failures[0][1]

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
