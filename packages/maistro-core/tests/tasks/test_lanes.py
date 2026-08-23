"""LaneGate: reserved floors, tier ordering, and the failure modes that matter.

The tests that carry weight here are the guarantees, not the happy path:

* a LIVE request is admitted even when BACKGROUND has taken every shared permit
  (this is the whole reason reservation exists rather than plain priority);
* BACKGROUND cannot be starved by sustained LIVE traffic;
* a cancelled waiter does not leak a permit — capacity loss of that kind is
  silent and cumulative, and is the standard bug in hand-rolled gates.
"""

from __future__ import annotations

import asyncio

import pytest

from maistro.tasks.lanes import TIER_PRIORITY, Lane, LaneGate


class TestConfiguration:
    def test_floors_may_not_exceed_total(self):
        """Refused rather than clamped: silently shrinking a floor would make
        the guarantee the caller asked for quietly untrue."""
        with pytest.raises(ValueError, match="exceed total"):
            LaneGate(4, live_reserved=3, background_reserved=2)

    def test_total_must_be_positive(self):
        with pytest.raises(ValueError, match="total must be"):
            LaneGate(0)

    def test_floors_may_consume_the_whole_budget(self):
        gate = LaneGate(4, live_reserved=2, background_reserved=2)
        assert gate.stats()["shared_free"] == 0

    def test_tier_table_matches_stronghold(self):
        """Identical to Stronghold's orchestrator `_TIER_PRIORITY` so the two
        schedulers order work the same way and can be compared."""
        assert TIER_PRIORITY == {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4, "P5": 5}


class TestReservation:
    async def test_live_is_admitted_when_background_holds_every_shared_permit(self):
        """The core guarantee, and the thing plain priority cannot provide."""
        gate = LaneGate(10, live_reserved=2, background_reserved=1)
        # BACKGROUND takes its floor (1) plus all shared (7) = 8.
        for _ in range(8):
            await gate.acquire(Lane.BACKGROUND)
        assert gate.stats()["shared_free"] == 0

        # LIVE still gets in immediately, twice — its floor is untouchable.
        await asyncio.wait_for(gate.acquire(Lane.LIVE, "P0"), timeout=0.5)
        await asyncio.wait_for(gate.acquire(Lane.LIVE, "P0"), timeout=0.5)
        assert gate.held(Lane.LIVE) == 2

    async def test_live_blocks_once_its_floor_and_shared_are_gone(self):
        gate = LaneGate(4, live_reserved=1, background_reserved=1)
        await gate.acquire(Lane.LIVE)  # floor
        await gate.acquire(Lane.LIVE)  # shared
        await gate.acquire(Lane.BACKGROUND)  # floor
        await gate.acquire(Lane.BACKGROUND)  # shared -> full
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(gate.acquire(Lane.LIVE), timeout=0.05)

    async def test_background_cannot_be_starved_by_sustained_live_load(self):
        """Pure priority starves the low lane forever; a floor bounds it."""
        gate = LaneGate(6, live_reserved=2, background_reserved=2)
        for _ in range(4):  # LIVE floor 2 + both shared
            await gate.acquire(Lane.LIVE, "P0")
        # BACKGROUND's floor is still available despite LIVE saturating the rest.
        await asyncio.wait_for(gate.acquire(Lane.BACKGROUND, "P5"), timeout=0.5)
        await asyncio.wait_for(gate.acquire(Lane.BACKGROUND, "P5"), timeout=0.5)
        assert gate.held(Lane.BACKGROUND) == 2

    async def test_neither_lane_can_exceed_the_total(self):
        gate = LaneGate(3, live_reserved=1, background_reserved=1)
        await gate.acquire(Lane.LIVE)
        await gate.acquire(Lane.BACKGROUND)
        await gate.acquire(Lane.LIVE)
        assert gate.held(Lane.LIVE) + gate.held(Lane.BACKGROUND) == 3
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(gate.acquire(Lane.BACKGROUND), timeout=0.05)


class TestTierOrdering:
    async def test_higher_tier_waiter_is_served_first(self):
        gate = LaneGate(1, live_reserved=0, background_reserved=0)
        await gate.acquire(Lane.BACKGROUND, "P2")  # occupy the only permit
        order: list[str] = []

        async def waiter(tier: str):
            await gate.acquire(Lane.BACKGROUND, tier)
            order.append(tier)

        tasks = [asyncio.create_task(waiter(t)) for t in ("P5", "P3", "P0", "P4")]
        await asyncio.sleep(0.05)  # let them all queue
        for _ in range(4):
            gate.release(Lane.BACKGROUND)
            await asyncio.sleep(0.01)
        await asyncio.gather(*tasks)
        assert order == ["P0", "P3", "P4", "P5"]

    async def test_same_tier_is_fifo(self):
        gate = LaneGate(1, live_reserved=0, background_reserved=0)
        await gate.acquire(Lane.BACKGROUND, "P2")
        order: list[int] = []

        async def waiter(n: int):
            await gate.acquire(Lane.BACKGROUND, "P2")
            order.append(n)

        tasks = []
        for n in range(4):
            tasks.append(asyncio.create_task(waiter(n)))
            await asyncio.sleep(0.01)  # establish arrival order
        for _ in range(4):
            gate.release(Lane.BACKGROUND)
            await asyncio.sleep(0.01)
        await asyncio.gather(*tasks)
        assert order == [0, 1, 2, 3]

    async def test_unknown_tier_defaults_to_p2_rather_than_raising(self):
        """A gate that rejects work over a typo'd label is worse than one that
        schedules it at normal priority."""
        gate = LaneGate(1, live_reserved=0, background_reserved=0)
        await asyncio.wait_for(gate.acquire(Lane.BACKGROUND, "not-a-tier"), timeout=0.5)
        assert gate.held(Lane.BACKGROUND) == 1


class TestCancellationSafety:
    async def test_cancelled_waiter_does_not_leak_a_permit(self):
        """Silent, cumulative capacity loss — the standard hand-rolled-gate bug."""
        gate = LaneGate(1, live_reserved=0, background_reserved=0)
        await gate.acquire(Lane.BACKGROUND)

        waiter = asyncio.create_task(gate.acquire(Lane.BACKGROUND))
        await asyncio.sleep(0.02)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter

        gate.release(Lane.BACKGROUND)
        await asyncio.sleep(0.02)
        # The permit must be reusable.
        await asyncio.wait_for(gate.acquire(Lane.BACKGROUND), timeout=0.5)
        assert gate.held(Lane.BACKGROUND) == 1

    async def test_many_cancellations_do_not_erode_capacity(self):
        gate = LaneGate(2, live_reserved=0, background_reserved=0)
        await gate.acquire(Lane.BACKGROUND)
        await gate.acquire(Lane.BACKGROUND)
        for _ in range(20):
            w = asyncio.create_task(gate.acquire(Lane.BACKGROUND))
            await asyncio.sleep(0)
            w.cancel()
            with pytest.raises(asyncio.CancelledError):
                await w
        gate.release(Lane.BACKGROUND)
        gate.release(Lane.BACKGROUND)
        await asyncio.sleep(0.02)
        assert gate.stats()["live_held"] == 0
        assert gate.held(Lane.BACKGROUND) == 0
        for _ in range(2):
            await asyncio.wait_for(gate.acquire(Lane.BACKGROUND), timeout=0.5)

    async def test_hold_releases_on_exception(self):
        gate = LaneGate(1, live_reserved=0, background_reserved=0)
        with pytest.raises(RuntimeError, match="boom"):
            async with gate.hold(Lane.BACKGROUND):
                raise RuntimeError("boom")
        assert gate.held(Lane.BACKGROUND) == 0

    async def test_unbalanced_release_raises(self):
        gate = LaneGate(6)
        with pytest.raises(RuntimeError, match="no permit held"):
            gate.release(Lane.LIVE)


class TestWakeupCorrectness:
    async def test_ineligible_head_waiter_does_not_block_the_queue(self):
        """A freed LIVE floor slot must not be blocked behind a higher-priority
        BACKGROUND waiter that cannot use it."""
        gate = LaneGate(3, live_reserved=1, background_reserved=1)
        await gate.acquire(Lane.LIVE)  # LIVE floor
        await gate.acquire(Lane.BACKGROUND)  # BG floor
        await gate.acquire(Lane.BACKGROUND)  # the shared permit -> full

        bg = asyncio.create_task(gate.acquire(Lane.BACKGROUND, "P0"))  # high tier, blocked
        await asyncio.sleep(0.02)
        live = asyncio.create_task(gate.acquire(Lane.LIVE, "P5"))  # low tier, needs the floor
        await asyncio.sleep(0.02)

        gate.release(Lane.LIVE)  # frees the LIVE floor only
        await asyncio.wait_for(live, timeout=0.5)  # LIVE gets it despite lower tier
        assert not bg.done()

        gate.release(Lane.BACKGROUND)
        await asyncio.wait_for(bg, timeout=0.5)


class TestEndToEnd:
    #: Interactive requests in the flood scenario. Four fit the LIVE floor
    #: immediately; the rest must be served on the first release round, which is
    #: the property under test.
    INTERACTIVE = 8

    async def test_batch_flood_serves_interactive_before_queued_batch(self):
        """The measured scenario, in miniature: a wide batch fan-out plus
        interactive requests.

        Asserted on **acquisition order**, not on wall-clock latency, because
        the guarantee is about priority and the clock is about the scheduler.
        The previous version asserted `max(latency) < CALL * 2.5`, which flaked
        roughly 1 run in 18 under CPU contention (#184): four latencies landed a
        whole `CALL` late, tightly clustered rather than scattered, because the
        waiting requests missed one release round. Whether they catch that round
        is decided by sub-millisecond ordering between the `gather` starting
        these coroutines and the batch `sleep` callbacks firing — so the old
        threshold measured scheduler luck and reported it as a fairness result.
        CI runners are contended, which is exactly where that luck runs out.

        What `_wake_one` actually promises is that a P0 `LIVE` waiter is served
        ahead of the P5 `BACKGROUND` waiters queued behind it. That is what this
        checks, and it holds at any CPU speed.
        """
        CALL = 0.05
        ARRIVED = "interactive-arrived"
        gate = LaneGate(12, live_reserved=4, background_reserved=2)
        # Appended at the moment a permit is granted, so this is the order the
        # gate handed permits out in — the thing the guarantee is about.
        granted: list[str] = []

        async def batch_node():
            async with gate.hold(Lane.BACKGROUND, "P5"):
                granted.append("batch")
                await asyncio.sleep(CALL)

        async def interactive():
            async with gate.hold(Lane.LIVE, "P0"):
                granted.append("live")
                await asyncio.sleep(CALL)

        batch = [asyncio.create_task(batch_node()) for _ in range(120)]
        await asyncio.sleep(CALL / 2)  # let batch saturate first
        granted.append(ARRIVED)
        await asyncio.gather(*[interactive() for _ in range(self.INTERACTIVE)])
        await asyncio.gather(*batch)

        # Every interactive request is granted before any batch request that was
        # still queued when they arrived: 112 batch tasks are waiting at P5 with
        # nothing but priority keeping them behind.
        arrival = granted.index(ARRIVED)
        served_next = granted[arrival + 1 : arrival + 1 + self.INTERACTIVE]
        assert served_next == ["live"] * self.INTERACTIVE, granted[arrival : arrival + 20]

    async def test_batch_flood_does_not_stall_interactive_work(self):
        """A loose wall-clock net, deliberately far from the edge.

        Kept because an ordering assertion alone would pass a gate that serves
        interactive work first and then takes a minute to do it. The bound is
        an order of magnitude above the expected time rather than 2.5x, so it
        catches a stall without re-introducing the round-alignment race.
        """
        CALL = 0.05
        gate = LaneGate(12, live_reserved=4, background_reserved=2)
        live_latencies: list[float] = []

        async def batch_node():
            async with gate.hold(Lane.BACKGROUND, "P5"):
                await asyncio.sleep(CALL)

        async def interactive():
            loop = asyncio.get_running_loop()
            t0 = loop.time()
            async with gate.hold(Lane.LIVE, "P0"):
                await asyncio.sleep(CALL)
            live_latencies.append(loop.time() - t0)

        batch = [asyncio.create_task(batch_node()) for _ in range(120)]
        await asyncio.sleep(CALL / 2)
        await asyncio.gather(*[interactive() for _ in range(self.INTERACTIVE)])
        await asyncio.gather(*batch)

        assert max(live_latencies) < CALL * 20, live_latencies


class TestRegressions:
    """Each of these reproduces a defect that shipped in the first version of
    this gate and was caught in review. They are written as the failure, not
    as the fix."""

    async def test_cancel_after_handoff_does_not_permanently_hold_the_permit(self):
        """`_wake_one` increments `_held` *before* resolving the future, so a
        waiter cancelled in that window already owns a counted permit. The
        original handler incremented again and released once, leaving one
        permit held forever — silent, cumulative, and eventually total."""
        gate = LaneGate(1, live_reserved=0, background_reserved=0)
        await gate.acquire(Lane.BACKGROUND)

        waiter = asyncio.create_task(gate.acquire(Lane.BACKGROUND))
        await asyncio.sleep(0.02)  # waiter is queued
        gate.release(Lane.BACKGROUND)  # hands the permit to waiter
        waiter.cancel()  # cancel before it resumes
        with pytest.raises(asyncio.CancelledError):
            await waiter
        await asyncio.sleep(0.02)

        assert gate.held(Lane.BACKGROUND) == 0
        # And the capacity is genuinely reusable, not just counted as free.
        await asyncio.wait_for(gate.acquire(Lane.BACKGROUND), timeout=0.5)

    async def test_repeated_cancel_after_handoff_does_not_erode_capacity(self):
        """Cancelling right after a hand-off races by nature: the waiter may
        already have resumed. Either outcome is legal — what must hold is that
        the permit count reflects reality afterwards, every time."""
        gate = LaneGate(2, live_reserved=0, background_reserved=0)
        for _ in range(15):
            await gate.acquire(Lane.BACKGROUND)  # held = 1
            w = asyncio.create_task(gate.acquire(Lane.BACKGROUND))
            await asyncio.sleep(0.01)
            gate.release(Lane.BACKGROUND)  # hands off; held = 1 (the waiter's)
            w.cancel()
            try:
                await w
                acquired = True  # cancel lost the race; waiter holds a permit
            except asyncio.CancelledError:
                acquired = False  # cancel won; the permit must have gone back
            await asyncio.sleep(0)
            assert gate.held(Lane.BACKGROUND) == (1 if acquired else 0)
            if acquired:
                gate.release(Lane.BACKGROUND)

        assert gate.held(Lane.BACKGROUND) == 0
        # Full capacity is genuinely reusable, not merely counted as free.
        for _ in range(2):
            await asyncio.wait_for(gate.acquire(Lane.BACKGROUND), timeout=0.5)

    def test_a_lane_that_could_never_be_admitted_is_refused(self):
        """floors=0 with an empty shared pool is a deadlock, not a throttle:
        the lane can never be admitted even on a completely idle gate."""
        with pytest.raises(ValueError, match="could never be admitted"):
            LaneGate(1, live_reserved=0, background_reserved=1)
        with pytest.raises(ValueError, match="could never be admitted"):
            LaneGate(2, live_reserved=2, background_reserved=0)

    async def test_both_lanes_are_admissible_on_an_idle_gate(self):
        for total in range(1, 9):
            live = min(2, max(0, total - 1))
            background = min(1, max(0, total - 1 - live))
            gate = LaneGate(total, live_reserved=live, background_reserved=background)
            for lane in (Lane.LIVE, Lane.BACKGROUND):
                fresh = LaneGate(total, live_reserved=live, background_reserved=background)
                await asyncio.wait_for(fresh.acquire(lane), timeout=0.5), (total, lane)
            del gate

    def test_lane_is_the_canonical_enum_not_a_second_one(self):
        """A divergent copy would fail validation the moment an AgentSpec lane
        was propagated into a TaskCreate."""
        from maistro.agents.spec.agent_spec import Lane as CanonicalLane

        assert Lane is CanonicalLane
        assert Lane.LIVE.value == "live-chat"
        assert Lane.BACKGROUND.value == "background-task"
