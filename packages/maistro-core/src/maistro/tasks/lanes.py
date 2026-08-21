"""Lane-aware, tier-ordered admission control (ADR-010 + ADR-070426-b5e9).

Two axes, deliberately not merged — the ADRs are explicit that they answer
different questions:

* **Lane** (ADR-010) is *where* work runs: ``LIVE`` gets reserved capacity,
  ``BACKGROUND`` uses what is left.
* **Tier** (ADR-070426-b5e9, ``P0``-``P5``) is *how much* the platform should
  spend once it is running, and here decides queue order among waiters.

Why reservation and not just priority
-------------------------------------
Priority alone decides *who gets the next free slot*. It cannot take a slot
back, because an in-flight LLM call cannot be preempted — ADR-010 says exactly
this and puts preemption out of scope ("not safe to implement without
cooperative yield points"). So under saturation, a P0 request behind a full set
of running P5 work waits a whole agent-run no matter how high its priority.

Measured on a 300-node DAG competing with 20 interactive requests, 2s calls:

    shared budget, no admission control    chat p50  4.06s
    global cap (max_connections=25)        chat p50 24.14s   <- worst
    priority ordering, no reservation      chat p50  3.51s
    priority + reserved floor for LIVE     chat p50  2.03s   <- the bare call

The global cap is the trap: it throttles *everything*, so interactive requests
queue behind batch work in the same line. A reserved floor is the only one of
the four that gives a latency guarantee, because it is the only one that
guarantees a slot exists.

Both lanes get a floor
----------------------
``BACKGROUND`` gets a reserved floor too, which pure priority does not give it.
Without one, sustained ``LIVE`` traffic starves batch work indefinitely — the
classic priority-inversion-by-starvation failure. Symmetric reservation bounds
both directions and is far easier to reason about than an aging heuristic.

    total = live_reserved + background_reserved + shared

``LIVE`` may use its own floor plus the shared pool; ``BACKGROUND`` may use its
floor plus the shared pool; neither can touch the other's floor. Waiters for the
shared pool are ordered by tier, then FIFO within a tier.
"""

from __future__ import annotations

import asyncio
import heapq
import itertools
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

# The canonical scheduling lane, already defined by ADR-004's agent-spec
# envelope with the serialized values `live-chat` / `background-task`. It is
# re-exported here rather than redefined: a second `Lane` with different
# values would fail validation the moment an `AgentSpec.lane` was propagated
# into a `TaskCreate.lane`, and would put two incompatible spellings of the
# same axis on the public API.
from maistro.agents.spec.agent_spec import Lane

# Lower number sorts first. Mirrors Stronghold's orchestrator/engine.py
# `_TIER_PRIORITY`, which is the one place this scheme is already wired to a
# real queue; keeping the mapping identical means the two can be compared.
TIER_PRIORITY: dict[str, int] = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4, "P5": 5}

_DEFAULT_TIER = "P2"

__all__ = ["TIER_PRIORITY", "Lane", "LaneGate"]


class LaneGate:
    """Bounded admission with a reserved floor per lane and tier-ordered waiting.

    Not a semaphore subclass on purpose: ``asyncio.Semaphore`` has one counter
    and FIFO wakeups, and cannot express "these N permits are only for LIVE".

    Args:
        total: permits in total.
        live_reserved: permits only ``LIVE`` may hold.
        background_reserved: permits only ``BACKGROUND`` may hold. Non-zero by
            default so live traffic cannot starve batch work forever.

    Sizing: a reserved floor should be about the concurrency that lane actually
    needs, which is its arrival rate times its latency (Little's Law). Five
    interactive requests per second against 2s calls needs ~10.
    """

    def __init__(
        self,
        total: int,
        *,
        live_reserved: int = 2,
        background_reserved: int = 1,
    ) -> None:
        if total < 1:
            raise ValueError(f"total must be >= 1, got {total}")
        if live_reserved < 0 or background_reserved < 0:
            raise ValueError("reserved floors cannot be negative")
        if live_reserved + background_reserved > total:
            raise ValueError(
                f"reserved floors ({live_reserved} live + {background_reserved} background) "
                f"exceed total ({total}). Every lane could then be blocked while permits "
                "sit unusable — the misconfiguration is refused rather than silently clamped."
            )
        shared = total - live_reserved - background_reserved
        # A lane with no floor and no shared pool can never be admitted, even
        # on a completely idle gate. That is not a throttle, it is a deadlock:
        # the caller waits forever and, if it is a dispatcher, takes every
        # later task down with it. Refuse the configuration.
        for name, reserved in (("live", live_reserved), ("background", background_reserved)):
            if reserved == 0 and shared == 0:
                raise ValueError(
                    f"lane {name!r} has no reserved floor and the shared pool is empty "
                    f"(total={total}, live={live_reserved}, background={background_reserved}), "
                    "so it could never be admitted even when idle. Leave at least one "
                    "shared permit, or give the lane a floor."
                )
        self._total = total
        self._reserved = {Lane.LIVE: live_reserved, Lane.BACKGROUND: background_reserved}
        self._shared = total - live_reserved - background_reserved
        self._held: dict[Lane, int] = {Lane.LIVE: 0, Lane.BACKGROUND: 0}
        # (tier_rank, seq, lane, future) — seq keeps FIFO within a tier and
        # stops heapq comparing futures when ranks tie.
        self._waiters: list[tuple[int, int, Lane, asyncio.Future[None]]] = []
        self._seq = itertools.count()

    # -- introspection ----------------------------------------------------

    @property
    def total(self) -> int:
        return self._total

    def held(self, lane: Lane) -> int:
        return self._held[lane]

    def stats(self) -> dict[str, int]:
        return {
            "total": self._total,
            "live_held": self._held[Lane.LIVE],
            "background_held": self._held[Lane.BACKGROUND],
            "live_reserved": self._reserved[Lane.LIVE],
            "background_reserved": self._reserved[Lane.BACKGROUND],
            "shared_free": self._shared_free(),
            "waiting": len(self._waiters),
        }

    # -- core -------------------------------------------------------------

    def _shared_free(self) -> int:
        """Shared permits not currently borrowed by either lane."""
        borrowed = sum(
            max(0, self._held[lane] - self._reserved[lane]) for lane in (Lane.LIVE, Lane.BACKGROUND)
        )
        return self._shared - borrowed

    def _can_admit(self, lane: Lane) -> bool:
        # Own floor first, then the shared pool. Checking the floor first is
        # what makes the guarantee hold: a lane below its floor is admitted
        # even when every shared permit is taken by the other lane.
        if self._held[lane] < self._reserved[lane]:
            return True
        return self._shared_free() > 0

    async def acquire(self, lane: Lane = Lane.BACKGROUND, tier: str = _DEFAULT_TIER) -> None:
        """Take a permit, waiting if none is available for ``lane``.

        Unknown tiers fall back to ``P2`` rather than raising: an admission gate
        that rejects work over a typo'd label is worse than one that schedules
        it at normal priority.
        """
        if self._can_admit(lane):
            self._held[lane] += 1
            return
        fut: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        rank = TIER_PRIORITY.get(tier, TIER_PRIORITY[_DEFAULT_TIER])
        heapq.heappush(self._waiters, (rank, next(self._seq), lane, fut))
        try:
            await fut
        except asyncio.CancelledError:
            # A cancelled waiter may already have been handed a permit by
            # `_wake_one`, which increments `_held` *before* resolving the
            # future. That permit is therefore already counted — releasing is
            # enough, and incrementing first would leave it held forever.
            # Without this branch the gate silently loses capacity on every
            # such cancellation, which is cumulative and eventually total.
            if fut.done() and not fut.cancelled():
                self.release(lane)
            raise

    def release(self, lane: Lane = Lane.BACKGROUND) -> None:
        """Return a permit and wake the best eligible waiter, if any."""
        if self._held[lane] <= 0:
            raise RuntimeError(
                f"release({lane.value}) called with no permit held for that lane — "
                "acquire/release are unbalanced; prefer the `hold()` context manager."
            )
        self._held[lane] -= 1
        self._wake_one()

    def _wake_one(self) -> None:
        """Hand the freed permit to the highest-priority admissible waiter.

        Scans past waiters that cannot be admitted (a BACKGROUND waiter when
        only a LIVE floor slot opened) instead of stopping at the head, so a
        blocked high-priority waiter in the wrong lane cannot deadlock the
        queue behind it.
        """
        deferred: list[tuple[int, int, Lane, asyncio.Future[None]]] = []
        try:
            while self._waiters:
                entry = heapq.heappop(self._waiters)
                _rank, _seq, lane, fut = entry
                if fut.done():  # cancelled or already resolved
                    continue
                if self._can_admit(lane):
                    self._held[lane] += 1
                    fut.set_result(None)
                    return
                deferred.append(entry)
        finally:
            for entry in deferred:
                heapq.heappush(self._waiters, entry)

    @asynccontextmanager
    async def hold(
        self, lane: Lane = Lane.BACKGROUND, tier: str = _DEFAULT_TIER
    ) -> AsyncIterator[None]:
        """``async with gate.hold(Lane.LIVE, "P0"): ...`` — the preferred API.

        Releases on any exit path including cancellation, which hand-written
        acquire/release pairs routinely get wrong.
        """
        await self.acquire(lane, tier)
        try:
            yield
        finally:
            self.release(lane)
