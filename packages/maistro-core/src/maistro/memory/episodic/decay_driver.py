"""Periodic episodic-memory decay driver (SPEC-080126-9e42).

`README.md` promises episodic memory "decays without reinforcement" and CLAUDE.md
decision #5 is "Memory must forget". Until this module existed, both were false at
runtime: `tiers.decay()` / `tiers.tick_decay()` shipped correct and tested but had
no production caller (#344). This gives them one.

This is a **process-lifetime cadence**, not a user-created schedule. It needs no
persisted schedule record — a background task started from the app lifespan
restarts with the process, which is exactly the lifetime the cadence should have.
It therefore deliberately does *not* build on `/v1/schedules` or
`maistro.scheduling`.

Curve constants (`DEFAULT_DECAY_RATE`, boost/drop rates, tier floors) belong to
ADR-080 and are not this module's business: it drives the shipped curve, it does
not reshape it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from maistro.types.memory import DecaySweep

if TYPE_CHECKING:
    from maistro.protocols.memory import DecayableEpisodicStore

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_DECAY_INTERVAL_S",
    "DecayTick",
    "EpisodicDecayDriver",
    "supports_decay",
]

DEFAULT_DECAY_INTERVAL_S: float = 3600.0
"""Hourly — cheap to run over an in-process store, frequent enough that weights
track the curve closely."""


@dataclass(frozen=True)
class DecayTick:
    """One completed sweep — the observability record for "did decay run?"."""

    at: datetime
    sweep: DecaySweep

    def as_dict(self) -> dict[str, object]:
        return {
            "at": self.at.isoformat(),
            "scanned": self.sweep.scanned,
            "decayed": self.sweep.decayed,
            "at_floor": self.sweep.at_floor,
        }


def supports_decay(store: object) -> bool:
    """True when `store` can be swept by this driver."""
    return callable(getattr(store, "apply_decay", None))


class EpisodicDecayDriver:
    """Runs `EpisodicStore.apply_decay` on a cadence for the life of the process.

    `interval_s <= 0` disables the driver. Disabling is a **degraded mode**, not a
    quiet preference: `start()` logs a warning naming the knob, returns False, and
    `status()` reports `enabled: False` so a health endpoint can surface it. A
    silent no-op here is indistinguishable from the bug this module exists to fix.
    """

    def __init__(
        self,
        store: DecayableEpisodicStore | None,
        *,
        interval_s: float = DEFAULT_DECAY_INTERVAL_S,
        setting_name: str = "MEMORY_DECAY_INTERVAL_S",
    ) -> None:
        self._store = store
        self._interval_s = float(interval_s)
        self._setting_name = setting_name
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._ticks = 0
        self._last_tick: DecayTick | None = None

    @property
    def enabled(self) -> bool:
        return self._interval_s > 0

    @property
    def interval_s(self) -> float:
        return self._interval_s

    @property
    def ticks(self) -> int:
        return self._ticks

    @property
    def last_tick(self) -> DecayTick | None:
        return self._last_tick

    @property
    def running(self) -> bool:
        return self._running

    def state(self) -> str:
        """`disabled` | `no_store` | `running` | `stopped` — one word for /health."""
        if not self.enabled:
            return "disabled"
        if not supports_decay(self._store):
            return "no_store"
        return "running" if self._running else "stopped"

    def status(self) -> dict[str, object]:
        """Observable state: is it on, is it wired, and what did the last tick touch?"""
        return {
            "enabled": self.enabled,
            "state": self.state(),
            "interval_s": self._interval_s,
            "ticks": self._ticks,
            "last_tick": self._last_tick.as_dict() if self._last_tick else None,
        }

    async def run_once(self, *, now: datetime | None = None) -> DecayTick | None:
        """Sweep once. Returns None (and logs why) when disabled or unwired."""
        if not self.enabled:
            logger.warning(
                "episodic_decay_skipped reason=disabled setting=%s — memory is NOT "
                "forgetting; README's 'decays without reinforcement' does not hold "
                "in this configuration",
                self._setting_name,
            )
            return None
        store = self._store
        if not supports_decay(store):
            logger.warning(
                "episodic_decay_skipped reason=no_decayable_store store=%s — "
                "memory is NOT forgetting",
                type(store).__name__,
            )
            return None

        at = now or datetime.now(UTC)
        sweep = await store.apply_decay(now=at)  # type: ignore[union-attr]
        tick = DecayTick(at=at, sweep=sweep)
        self._ticks += 1
        self._last_tick = tick
        logger.info(
            "episodic_decay_tick scanned=%d decayed=%d at_floor=%d",
            sweep.scanned,
            sweep.decayed,
            sweep.at_floor,
        )
        return tick

    async def start(self) -> bool:
        """Start the background cadence. False when disabled (loudly) or already up."""
        if not self.enabled:
            logger.warning(
                "episodic_decay_disabled setting=%s=%s — DEGRADED: episodic memory "
                "will not decay and stale entries keep their salience forever. Set a "
                "positive interval to restore the documented behaviour.",
                self._setting_name,
                self._interval_s,
            )
            return False
        if not supports_decay(self._store):
            logger.warning(
                "episodic_decay_unwired store=%s — DEGRADED: no decayable episodic "
                "store, nothing to decay.",
                type(self._store).__name__,
            )
            return False
        if self._running:
            return False
        self._running = True
        self._task = asyncio.ensure_future(self._loop())
        logger.info("episodic_decay_started interval_s=%s", self._interval_s)
        return True

    async def stop(self) -> None:
        self._running = False
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            # Shutdown must never raise, whatever the loop was doing.
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    async def _loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self._interval_s)
            except asyncio.CancelledError:
                return
            if not self._running:
                return
            try:
                await self.run_once()
            except Exception as exc:  # a bad sweep must not kill the cadence
                logger.warning("episodic_decay_tick_failed: %s", exc, exc_info=True)
