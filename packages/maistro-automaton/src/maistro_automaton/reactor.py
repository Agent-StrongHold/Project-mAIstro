"""Reactor: the tick loop every automaton hangs off.

Extracted from the Turing research branch's reactor (``cognition/reactor.py``),
generalized to a Protocol + one deterministic implementation. The contract is
deliberately tiny: handlers registered against a monotonic tick count,
interval triggers named and idempotent-registerable, ``spawn`` for
synchronous-completion futures. Producers and the arbiter are tick-driven —
nothing in an automaton runs on wall-clock timers or wall-clock callbacks,
because a tick stream is replayable and a wall clock is not.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Reactor(Protocol):
    """The pulse. Handlers see a monotonic tick count; nothing else."""

    tick_count: int

    def register(self, handler: Callable[[int], None]) -> None: ...

    def spawn(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future[Any]: ...


@dataclass
class IntervalTrigger:
    name: str
    interval: timedelta
    handler: Callable[[], None]
    first_fire_at: Any | None = None
    fire_count: int = 0


class TickReactor:
    """Deterministic Reactor driven by explicit ``tick()`` calls.

    The host decides what advances time — a loop, a test, a scheduler. Under
    explicit ticks the actor is fully replayable: same ticks, same state
    transitions, same verdicts. This is what makes automata cageable where
    wall-clock daemons are not.
    """

    def __init__(self) -> None:
        self.tick_count: int = 0
        self._handlers: list[Callable[[int], None]] = []
        self._interval_triggers: dict[str, IntervalTrigger] = {}

    def register(self, handler: Callable[[int], None]) -> None:
        self._handlers.append(handler)

    def register_interval_trigger(
        self,
        name: str,
        interval: timedelta,
        handler: Callable[[], None],
        first_fire_at: Any | None = None,
        idempotent: bool = False,
    ) -> IntervalTrigger:
        if idempotent and name in self._interval_triggers:
            return self._interval_triggers[name]
        trigger = IntervalTrigger(
            name=name,
            interval=interval,
            handler=handler,
            first_fire_at=first_fire_at,
        )
        self._interval_triggers[name] = trigger
        return trigger

    def unregister_trigger(self, name: str) -> None:
        self._interval_triggers.pop(name, None)

    def fire_trigger(self, name: str) -> None:
        trigger = self._interval_triggers.get(name)
        if trigger is not None:
            trigger.handler()
            trigger.fire_count += 1

    @property
    def triggers(self) -> dict[str, IntervalTrigger]:
        return dict(self._interval_triggers)

    def tick(self, n: int = 1) -> None:
        for _ in range(n):
            self.tick_count += 1
            for handler in list(self._handlers):
                handler(self.tick_count)

    def spawn(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future[Any]:
        future: Future[Any] = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as exc:
            future.set_exception(exc)
        return future
