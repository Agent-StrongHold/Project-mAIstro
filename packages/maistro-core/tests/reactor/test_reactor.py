"""SPEC-013: 1kHz Reactor Loop — event-driven runtime.

These tests define the contract for the reactor event loop that replaces
the heartbeat system. All tests should FAIL until the reactor module
is implemented.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import pytest


class TestReactorWakeLatency:
    """AC: Reactor loop wakes within 5ms p95 of an event becoming ready."""

    @pytest.mark.asyncio()
    async def test_event_delivery_latency(self) -> None:
        import statistics

        from maistro.reactor import Reactor

        reactor = Reactor()
        latencies: list[float] = []
        received: asyncio.Queue[float] = asyncio.Queue()

        async def timed_handler(event: Any) -> None:
            await received.put(time.monotonic())

        reactor.register_source("test-tick", timed_handler)

        await reactor.start()
        try:
            for _ in range(100):
                emit_time = time.monotonic()
                await reactor.emit("test-tick", {"n": _})
                recv_time = await asyncio.wait_for(received.get(), timeout=1.0)
                latencies.append((recv_time - emit_time) * 1000)

            p95 = statistics.quantiles(latencies, n=20)[18]
            assert p95 < 5.0, f"p95 latency {p95:.1f}ms exceeds 5ms target"
        finally:
            await reactor.stop()


class TestHeartbeatCompatibility:
    """AC: All existing heartbeat behavior works as wall-clock-tick:30m event."""

    @pytest.mark.asyncio()
    async def test_wall_clock_tick_source(self) -> None:
        from maistro.reactor import Reactor

        reactor = Reactor()
        ticks: list[float] = []

        async def on_tick(event: Any) -> None:
            ticks.append(time.monotonic())

        reactor.register_source("wall-clock-tick:30m", on_tick)
        await reactor.start()

        try:
            reactor.inject_interval("wall-clock-tick:30m", interval=0.1)
            await asyncio.sleep(0.5)
            assert len(ticks) >= 3
        finally:
            await reactor.stop()


class TestQuiescentCPU:
    """AC: Quiescent CPU usage < 1% on typical desktop."""

    @pytest.mark.asyncio()
    async def test_idle_cpu_low(self) -> None:

        from maistro.reactor import Reactor

        reactor = Reactor()
        await reactor.start()

        try:
            await asyncio.sleep(1.0)
            usage = reactor.cpu_usage_fraction()
            assert usage < 0.01, f"CPU usage {usage:.2%} exceeds 1% when idle"
        finally:
            await reactor.stop()


class TestConcurrentEventSources:
    """AC: Multiple event sources can fire concurrently without race conditions."""

    @pytest.mark.asyncio()
    async def test_concurrent_sources(self) -> None:
        import asyncio

        from maistro.reactor import Reactor

        reactor = Reactor()
        results: dict[str, int] = {"a": 0, "b": 0}
        lock = asyncio.Lock()

        async def handler_a(event: Any) -> None:
            async with lock:
                results["a"] += 1

        async def handler_b(event: Any) -> None:
            async with lock:
                results["b"] += 1

        reactor.register_source("source-a", handler_a)
        reactor.register_source("source-b", handler_b)

        await reactor.start()
        try:
            for _ in range(50):
                await reactor.emit("source-a", {})
                await reactor.emit("source-b", {})
            await asyncio.sleep(0.5)

            assert results["a"] == 50
            assert results["b"] == 50
        finally:
            await reactor.stop()


class TestBouncerOnEveryEvent:
    """AC: No event source bypasses the Bouncer."""

    @pytest.mark.asyncio()
    async def test_bouncer_screens_all_events(self) -> None:
        from maistro.reactor import Reactor

        reactor = Reactor()
        screened: list[dict[str, Any]] = []

        async def bouncer_mock(event: Any) -> bool:
            screened.append(event if isinstance(event, dict) else {"name": str(event)})
            return True

        reactor.set_bouncer(bouncer_mock)

        async def handler(event: Any) -> None:
            pass

        reactor.register_source("test-source", handler)
        await reactor.start()
        try:
            await reactor.emit("test-source", {"payload": "data"})
            await asyncio.sleep(0.1)

            assert len(screened) >= 1
        finally:
            await reactor.stop()

    @pytest.mark.asyncio()
    async def test_bouncer_block_drops_event(self) -> None:
        from maistro.reactor import Reactor

        reactor = Reactor()
        handled: list[Any] = []

        async def blocking_bouncer(event: Any) -> bool:
            return False

        async def handler(event: Any) -> None:
            handled.append(event)

        reactor.set_bouncer(blocking_bouncer)
        reactor.register_source("blocked-source", handler)

        await reactor.start()
        try:
            await reactor.emit("blocked-source", {"should": "drop"})
            await asyncio.sleep(0.1)

            assert len(handled) == 0
        finally:
            await reactor.stop()


class TestStateSubmitIntegration:
    """AC: All state mutations from handlers go through state.submit()."""

    @pytest.mark.asyncio()
    async def test_handler_uses_state_submit(self, tmp_path: Path) -> None:
        from maistro.reactor import Reactor

        db_path = tmp_path / "state.db"
        reactor = Reactor(state_db_path=str(db_path))

        async def handler(event: Any) -> None:
            reactor.state_submit(
                lambda conn: conn.execute(
                    "INSERT INTO reactor_log (event_name) VALUES (?)",
                    (event.get("name", "unknown"),),
                )
            )

        reactor.register_source("log-event", handler)
        await reactor.start()
        try:
            await reactor.emit("log-event", {"name": "test-event"})
            await asyncio.sleep(0.2)

            rows = reactor.state_query("SELECT * FROM reactor_log")
            assert any("test-event" in str(r) for r in rows)
        finally:
            await reactor.stop()


class TestHandlerTimeout:
    """AC: Handler return must be <=5ms p95; long work offloaded to worker pool."""

    @pytest.mark.asyncio()
    async def test_slow_handler_does_not_block_loop(self) -> None:
        from maistro.reactor import Reactor

        reactor = Reactor(handler_timeout_ms=50)
        fast_events: list[float] = []

        async def slow_handler(event: Any) -> None:
            await asyncio.sleep(0.2)

        async def fast_handler(event: Any) -> None:
            fast_events.append(time.monotonic())

        reactor.register_source("slow", slow_handler)
        reactor.register_source("fast", fast_handler)

        await reactor.start()
        try:
            await reactor.emit("slow", {})
            await asyncio.sleep(0.05)
            t0 = time.monotonic()
            await reactor.emit("fast", {})
            await asyncio.sleep(0.1)

            assert len(fast_events) >= 1
            assert (fast_events[0] - t0) < 0.1
        finally:
            await reactor.stop()


class TestFailingHandlerDoesNotCrash:
    """AC: Failing handler does not crash the reactor."""

    @pytest.mark.asyncio()
    async def test_exception_in_handler_continues(self) -> None:
        from maistro.reactor import Reactor

        reactor = Reactor()
        call_count = {"n": 0}

        async def bad_handler(event: Any) -> None:
            raise RuntimeError("boom")

        async def good_handler(event: Any) -> None:
            call_count["n"] += 1

        reactor.register_source("bad", bad_handler)
        reactor.register_source("good", good_handler)

        await reactor.start()
        try:
            await reactor.emit("bad", {})
            await asyncio.sleep(0.05)
            await reactor.emit("good", {})
            await asyncio.sleep(0.05)

            assert call_count["n"] == 1
            assert reactor.is_running
        finally:
            await reactor.stop()


class TestSIGTERMShutdown:
    """AC: Reactor stops accepting, drains in-flight, cancels remaining, WAL checkpoint."""

    @pytest.mark.asyncio()
    async def test_graceful_shutdown_drains_handlers(self) -> None:
        from maistro.reactor import Reactor

        reactor = Reactor(grace_period_seconds=2)
        results: list[str] = []

        async def slow_handler(event: Any) -> None:
            await asyncio.sleep(0.3)
            results.append("completed")

        reactor.register_source("drain-test", slow_handler)

        await reactor.start()
        await reactor.emit("drain-test", {})
        await asyncio.sleep(0.05)

        await reactor.stop()

        assert "completed" in results

    @pytest.mark.asyncio()
    async def test_shutdown_cancels_past_grace(self) -> None:
        from maistro.reactor import Reactor

        reactor = Reactor(grace_period_seconds=0.1)
        results: list[str] = []

        async def very_slow_handler(event: Any) -> None:
            try:
                await asyncio.sleep(10)
                results.append("should_not_reach")
            except asyncio.CancelledError:
                results.append("cancelled")

        reactor.register_source("cancel-test", very_slow_handler)

        await reactor.start()
        await reactor.emit("cancel-test", {})
        await asyncio.sleep(0.05)

        await reactor.stop()

        assert "cancelled" in results
        assert "should_not_reach" not in results


class TestBackpressure:
    """AC: Queue depth > limit -> reactor pauses highest-volume sources."""

    @pytest.mark.asyncio()
    async def test_backpressure_on_overload(self) -> None:
        from maistro.reactor import Reactor

        reactor = Reactor(max_queue_depth=10)

        block_event = asyncio.Event()
        processed: list[int] = []

        async def blocking_handler(event: Any) -> None:
            await block_event.wait()
            processed.append(event.get("n", 0))

        reactor.register_source("high-volume", blocking_handler)

        await reactor.start()
        try:
            for i in range(20):
                await reactor.emit("high-volume", {"n": i})

            alerts = reactor.alerts()
            assert any("REACTOR_BACKPRESSURE" in str(a) for a in alerts)

            block_event.set()
            await asyncio.sleep(0.5)
        finally:
            await reactor.stop()
