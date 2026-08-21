"""Tests for the periodic decay driver (SPEC-080126-9e42).

`tiers.tick_decay` was correct and tested from the day it landed — and never ran,
because nothing called it. `test_decay.py` calls it directly, which is exactly the
coverage shape that let the gap ship. These tests therefore go through the driver
and, for the cadence test, through the real background loop.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from datetime import UTC, datetime, timedelta

import pytest

from maistro.memory.episodic.decay_driver import (
    DEFAULT_DECAY_INTERVAL_S,
    EpisodicDecayDriver,
    supports_decay,
)
from maistro.memory.episodic.store import InMemoryEpisodicStore
from maistro.memory.types import EpisodicMemory, MemoryScope, MemoryTier
from maistro.types.memory import DEFAULT_DECAY_RATE


def _mem(
    memory_id: str = "m1",
    tier: MemoryTier = MemoryTier.OBSERVATION,
    weight: float = 0.3,
    decay_rate: float = DEFAULT_DECAY_RATE,
    last_accessed_at: datetime | None = None,
) -> EpisodicMemory:
    return EpisodicMemory(
        memory_id=memory_id,
        tier=tier,
        weight=weight,
        content="some content",
        org_id="org-1",
        agent_id="agent-1",
        scope=MemoryScope.AGENT,
        decay_rate=decay_rate,
        last_accessed_at=last_accessed_at or datetime.now(UTC),
    )


async def _store_with(*memories: EpisodicMemory) -> InMemoryEpisodicStore:
    store = InMemoryEpisodicStore()
    for mem in memories:
        await store.store(mem)
    return store


async def _weight_of(store: InMemoryEpisodicStore, memory_id: str) -> float:
    found = [m for m in store._memories if m.memory_id == memory_id]
    assert found, f"{memory_id} missing from store"
    return found[0].weight


class TestSupportsDecay:
    def test_in_memory_store_is_decayable(self) -> None:
        assert supports_decay(InMemoryEpisodicStore()) is True

    def test_arbitrary_object_is_not(self) -> None:
        assert supports_decay(object()) is False
        assert supports_decay(None) is False


class TestDriverSweep:
    @pytest.mark.asyncio
    async def test_run_once_decays_weight_in_the_store(self) -> None:
        """The end the gap was at: a weight in a real store actually moves."""
        store = await _store_with(
            _mem(tier=MemoryTier.LESSON, weight=0.8, last_accessed_at=_hours_ago(10))
        )
        driver = EpisodicDecayDriver(store)

        tick = await driver.run_once()

        assert tick is not None
        assert await _weight_of(store, "m1") < 0.8

    @pytest.mark.asyncio
    async def test_tick_reports_entries_touched(self) -> None:
        """Observability: an operator can answer "did decay run, and on what?"."""
        store = await _store_with(
            _mem("a", tier=MemoryTier.LESSON, weight=0.8, last_accessed_at=_hours_ago(5)),
            _mem("b", tier=MemoryTier.OPINION, weight=0.7, last_accessed_at=_hours_ago(5)),
            _mem("c", tier=MemoryTier.WISDOM, weight=0.9, last_accessed_at=_hours_ago(5)),
        )
        driver = EpisodicDecayDriver(store)

        tick = await driver.run_once()

        assert tick is not None
        assert tick.sweep.scanned == 3
        assert tick.sweep.decayed == 2  # 'c' is pinned at the WISDOM floor
        assert tick.sweep.at_floor == 1
        assert tick.as_dict()["scanned"] == 3

    @pytest.mark.asyncio
    async def test_tick_is_logged_with_counts(self, caplog: pytest.LogCaptureFixture) -> None:
        store = await _store_with(_mem(last_accessed_at=_hours_ago(3)))
        driver = EpisodicDecayDriver(store)

        with caplog.at_level(logging.INFO, logger="maistro.memory.episodic.decay_driver"):
            await driver.run_once()

        assert "episodic_decay_tick" in caplog.text
        assert "scanned=1" in caplog.text

    @pytest.mark.asyncio
    async def test_deleted_entries_are_not_swept(self) -> None:
        store = await _store_with(_mem(last_accessed_at=_hours_ago(10)))
        store._memories[0] = dataclasses.replace(store._memories[0], deleted=True)
        driver = EpisodicDecayDriver(store)

        tick = await driver.run_once()

        assert tick is not None
        assert tick.sweep.scanned == 0


class TestFloorsHold:
    """CLAUDE.md decision #5's second half: "weight floors for wisdom/regrets"."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("tier", "floor"),
        [(MemoryTier.WISDOM, 0.9), (MemoryTier.REGRET, 0.6), (MemoryTier.AFFIRMATION, 0.6)],
    )
    async def test_entry_at_floor_never_drops_below_it_across_many_ticks(
        self, tier: MemoryTier, floor: float
    ) -> None:
        store = await _store_with(
            _mem(tier=tier, weight=floor, decay_rate=1.0, last_accessed_at=_hours_ago(1))
        )
        driver = EpisodicDecayDriver(store)

        now = datetime.now(UTC)
        for i in range(1, 51):
            await driver.run_once(now=now + timedelta(hours=i))
            assert await _weight_of(store, "m1") >= floor

        assert await _weight_of(store, "m1") == pytest.approx(floor)

    @pytest.mark.asyncio
    async def test_entry_above_floor_converges_to_it_and_stops(self) -> None:
        """Decay reaches the floor and then holds — forgetting is bounded, not total."""
        store = await _store_with(
            _mem(tier=MemoryTier.WISDOM, weight=1.0, decay_rate=1.0, last_accessed_at=_hours_ago(1))
        )
        driver = EpisodicDecayDriver(store)

        now = datetime.now(UTC)
        for i in range(1, 31):
            await driver.run_once(now=now + timedelta(hours=i))

        assert await _weight_of(store, "m1") == pytest.approx(0.9)


class TestReinforcementOffsetsDecay:
    """The README says memory decays *without reinforcement*. That qualifier must hold."""

    @pytest.mark.asyncio
    async def test_reinforced_entry_ends_heavier_than_neglected_twin(self) -> None:
        store = await _store_with(
            _mem("kept", tier=MemoryTier.LESSON, weight=0.6, last_accessed_at=_hours_ago(1)),
            _mem("neglected", tier=MemoryTier.LESSON, weight=0.6, last_accessed_at=_hours_ago(1)),
        )
        driver = EpisodicDecayDriver(store)

        now = datetime.now(UTC)
        for i in range(1, 11):
            await driver.run_once(now=now + timedelta(hours=i))
            await store.reinforce("kept", delta=0.05)

        kept = await _weight_of(store, "kept")
        neglected = await _weight_of(store, "neglected")
        assert kept > neglected
        assert neglected < 0.6  # the neglected one really did lose ground

    @pytest.mark.asyncio
    async def test_reinforcement_can_fully_offset_the_per_tick_loss(self) -> None:
        """A per-tick loss of 0.01 against a +0.05 reinforcement nets upward."""
        store = await _store_with(
            _mem("kept", tier=MemoryTier.LESSON, weight=0.6, last_accessed_at=_hours_ago(1))
        )
        driver = EpisodicDecayDriver(store)

        now = datetime.now(UTC)
        for i in range(1, 6):
            await driver.run_once(now=now + timedelta(hours=i))
            await store.reinforce("kept", delta=0.05)

        assert await _weight_of(store, "kept") > 0.6


class TestDisabledIsLoudAndInert:
    """F3 precedent (#302): a degraded mode that looks like the bug is the defect."""

    @pytest.mark.asyncio
    async def test_disabled_driver_performs_no_mutation(self) -> None:
        store = await _store_with(
            _mem(tier=MemoryTier.LESSON, weight=0.8, last_accessed_at=_hours_ago(50))
        )
        driver = EpisodicDecayDriver(store, interval_s=0)

        assert driver.enabled is False
        assert await driver.run_once() is None
        assert await _weight_of(store, "m1") == pytest.approx(0.8)

    @pytest.mark.asyncio
    async def test_disabled_start_returns_false_and_warns_naming_the_knob(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        driver = EpisodicDecayDriver(await _store_with(_mem()), interval_s=0)

        with caplog.at_level(logging.WARNING, logger="maistro.memory.episodic.decay_driver"):
            started = await driver.start()

        assert started is False
        assert "episodic_decay_disabled" in caplog.text
        assert "MEMORY_DECAY_INTERVAL_S" in caplog.text  # names how to turn it back on
        assert "DEGRADED" in caplog.text

    @pytest.mark.asyncio
    async def test_disabled_status_reports_degraded_state(self) -> None:
        driver = EpisodicDecayDriver(await _store_with(_mem()), interval_s=0)

        status = driver.status()

        assert status["enabled"] is False
        assert status["state"] == "disabled"

    @pytest.mark.asyncio
    async def test_unwired_store_is_reported_not_swallowed(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Enabled but with nothing to drive is its own degraded state, not silence."""
        driver = EpisodicDecayDriver(None)

        with caplog.at_level(logging.WARNING, logger="maistro.memory.episodic.decay_driver"):
            started = await driver.start()

        assert started is False
        assert driver.state() == "no_store"
        assert "episodic_decay_unwired" in caplog.text


class TestCadenceIsConfigurable:
    def test_default_interval_is_hourly(self) -> None:
        assert EpisodicDecayDriver(None).interval_s == DEFAULT_DECAY_INTERVAL_S

    def test_interval_is_settable(self) -> None:
        assert EpisodicDecayDriver(None, interval_s=120).interval_s == 120

    @pytest.mark.parametrize("interval", [0, -1, -3600])
    def test_non_positive_interval_disables(self, interval: float) -> None:
        assert EpisodicDecayDriver(None, interval_s=interval).enabled is False


class TestRealSchedulingPath:
    """The coverage that was missing. Not `run_once`, not `tick_decay` — the loop.

    The gap survived because every existing test called `tick_decay` directly, so
    "nothing ever calls it" was invisible. These start the driver and wait for its
    background task to fire on its own.
    """

    @pytest.mark.asyncio
    async def test_background_cadence_decays_the_store_without_being_poked(self) -> None:
        store = await _store_with(
            _mem(tier=MemoryTier.LESSON, weight=0.8, decay_rate=1.0, last_accessed_at=_hours_ago(1))
        )
        driver = EpisodicDecayDriver(store, interval_s=0.02)

        started = await driver.start()
        assert started is True
        try:
            await _wait_until(lambda: driver.ticks >= 1)
        finally:
            await driver.stop()

        assert await _weight_of(store, "m1") < 0.8
        assert driver.last_tick is not None
        assert driver.last_tick.sweep.scanned == 1

    @pytest.mark.asyncio
    async def test_cadence_keeps_firing(self) -> None:
        store = await _store_with(_mem(last_accessed_at=_hours_ago(1)))
        driver = EpisodicDecayDriver(store, interval_s=0.01)

        await driver.start()
        try:
            await _wait_until(lambda: driver.ticks >= 3)
        finally:
            await driver.stop()

        assert driver.ticks >= 3

    @pytest.mark.asyncio
    async def test_stop_halts_the_cadence(self) -> None:
        store = await _store_with(_mem(last_accessed_at=_hours_ago(1)))
        driver = EpisodicDecayDriver(store, interval_s=0.01)

        await driver.start()
        await _wait_until(lambda: driver.ticks >= 1)
        await driver.stop()
        settled = driver.ticks

        await asyncio.sleep(0.05)

        assert driver.ticks == settled
        assert driver.running is False

    @pytest.mark.asyncio
    async def test_running_driver_reports_running_state(self) -> None:
        driver = EpisodicDecayDriver(await _store_with(_mem()), interval_s=0.01)

        await driver.start()
        try:
            assert driver.state() == "running"
            assert driver.status()["enabled"] is True
        finally:
            await driver.stop()

    @pytest.mark.asyncio
    async def test_a_failing_sweep_does_not_kill_the_cadence(self) -> None:
        """One bad tick must not silently end decay for the rest of the process."""

        class _FlakyStore:
            def __init__(self) -> None:
                self.calls = 0

            async def apply_decay(self, *, now: datetime | None = None) -> object:
                self.calls += 1
                raise RuntimeError("boom")

        store = _FlakyStore()
        driver = EpisodicDecayDriver(store, interval_s=0.01)  # type: ignore[arg-type]

        await driver.start()
        try:
            await _wait_until(lambda: store.calls >= 3)
        finally:
            await driver.stop()

        assert store.calls >= 3


def _hours_ago(hours: float) -> datetime:
    return datetime.now(UTC) - timedelta(hours=hours)


async def _wait_until(predicate, timeout: float = 5.0) -> None:
    """Poll until `predicate()` holds, so cadence tests never sleep on a fixed guess."""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("timed out waiting for the decay cadence to fire")
