"""The graph LLM concurrency bound.

Graph execution fans out twice and the two multiply — roles per cycle
(`run.py`) times `beam_width` per role (`node.py`) — and neither had a cap.
The bound sits at the leaf LLM call, which is the only choke point both paths
share, so it holds whatever shape the fan-out above it takes.
"""

from __future__ import annotations

import asyncio

import pytest

from maistro.graph.concurrency import (
    configure_graph_concurrency,
    get_graph_gate,
    llm_call_permit,
)
from maistro.tasks.lanes import Lane


@pytest.fixture(autouse=True)
def _fresh_gate():
    # Reconfiguration replaces the process-wide gate, so tests do not need a
    # production reset hook that exists only to satisfy test isolation.
    configure_graph_concurrency()
    yield
    configure_graph_concurrency()


class TestBound:
    async def test_concurrent_calls_never_exceed_the_limit(self):
        configure_graph_concurrency(max_concurrent_llm_calls=4, live_reserved=1)
        live = 0
        peak = 0

        async def call():
            nonlocal live, peak
            async with llm_call_permit():
                live += 1
                peak = max(peak, live)
                await asyncio.sleep(0.01)
                live -= 1

        await asyncio.gather(*[call() for _ in range(50)])
        assert peak <= 4, f"peak concurrency {peak} exceeded the bound"

    async def test_all_work_still_completes(self):
        """A bound must delay work, never drop it."""
        configure_graph_concurrency(max_concurrent_llm_calls=3, live_reserved=1)
        done = 0

        async def call():
            nonlocal done
            async with llm_call_permit():
                await asyncio.sleep(0.005)
                done += 1

        await asyncio.gather(*[call() for _ in range(40)])
        assert done == 40

    async def test_permit_is_released_when_the_call_raises(self):
        configure_graph_concurrency(max_concurrent_llm_calls=1, live_reserved=0)
        with pytest.raises(RuntimeError):
            async with llm_call_permit():
                raise RuntimeError("provider exploded")
        # Capacity must be reusable, not merely counted as free.
        async with asyncio.timeout(0.5):
            async with llm_call_permit():
                pass

    async def test_permit_is_released_on_cancellation(self):
        configure_graph_concurrency(max_concurrent_llm_calls=1, live_reserved=0)

        async def hangs():
            async with llm_call_permit():
                await asyncio.sleep(10)

        t = asyncio.create_task(hangs())
        await asyncio.sleep(0.02)
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t
        await asyncio.sleep(0.01)
        assert get_graph_gate().held(Lane.BACKGROUND) == 0


class TestLiveIsProtected:
    async def test_an_interactive_node_is_not_starved_by_a_batch_sweep(self):
        """The reason this is a LaneGate and not a semaphore: graph work is
        BACKGROUND, and a wide sweep must not crowd out an interactive re-run."""
        configure_graph_concurrency(max_concurrent_llm_calls=6, live_reserved=2)
        CALL = 0.05
        release = asyncio.Event()

        async def batch():
            async with llm_call_permit(Lane.BACKGROUND, "P5"):
                await release.wait()

        batch_tasks = [asyncio.create_task(batch()) for _ in range(30)]
        await asyncio.sleep(CALL)  # let the sweep saturate what it may take

        try:
            async with asyncio.timeout(0.5):
                async with llm_call_permit(Lane.LIVE, "P0"):
                    pass
        finally:
            release.set()
            await asyncio.gather(*batch_tasks, return_exceptions=True)


class TestDefaults:
    def test_gate_is_created_lazily(self):
        gate = get_graph_gate()
        assert gate.total > 0
        assert get_graph_gate() is gate

    def test_defaults_leave_both_lanes_admissible(self):
        configure_graph_concurrency()
        stats = get_graph_gate().stats()
        assert stats["live_reserved"] > 0
        assert stats["shared_free"] > 0

    @pytest.mark.parametrize("total", [1, 2, 3, 4, 8, 32])
    def test_small_totals_still_build_a_usable_gate(self, total: int):
        """`LaneGate` refuses a lane that could never be admitted, so the
        floors have to be clamped rather than passed through."""
        configure_graph_concurrency(max_concurrent_llm_calls=total)
        stats = get_graph_gate().stats()
        for lane in ("live", "background"):
            assert stats[f"{lane}_reserved"] > 0 or stats["shared_free"] > 0
