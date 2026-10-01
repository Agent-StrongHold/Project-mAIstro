"""Sync-loop boundary tests for the Turing bridge (#397).

The old synchronous bridge answered calls made on an event-loop thread by
blocking on an unbounded ``Future.result()`` — a stuck provider froze every
coroutine on that loop. These tests pin the replacement contract:

- success, exception, timeout, cancellation, reentrancy, and concurrent calls
  on the dedicated thread/loop boundary (:class:`SyncLoopRunner`);
- the bridge's sync ``complete`` is bounded and cancellable;
- async call paths (chat session, producers) await the async seam so the
  owning event loop keeps ticking while a model call is in flight.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pytest

from maistro_turing.bridge import PoolConfig, TuringProviderBridge
from maistro_turing.producers import BlogProducer
from maistro_turing.runtime import TuringChatSession
from maistro_turing.self_model import Mood
from maistro_turing.sync_runner import (
    DEFAULT_SYNC_TIMEOUT_SECONDS,
    ReentrantSyncCallError,
    SyncLoopClosedError,
    SyncLoopRunner,
)

# ------------------------------------------------------------------ fakes ----


class FakeLLMClient:
    """LLMClient double: controllable result, delay, failure, cancellation."""

    def __init__(
        self,
        reply: str = "ok",
        *,
        delay: float = 0.0,
        raises: Exception | None = None,
    ) -> None:
        self._reply = reply
        self._delay = delay
        self._raises = raises
        self.calls: list[dict[str, Any]] = []
        self.cancelled = 0
        self.completed = 0

    async def complete(
        self,
        messages: list[dict[str, Any]],
        model: str = "",
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        self.calls.append({"messages": messages, "model": model, "max_tokens": max_tokens})
        try:
            await asyncio.sleep(self._delay)
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        if self._raises is not None:
            raise self._raises
        self.completed += 1
        return {"choices": [{"message": {"content": self._reply}}]}


def _pool() -> PoolConfig:
    return PoolConfig(
        pool_name="main",
        model="test-model",
        window_kind="daily",
        window_duration_seconds=86400,
        tokens_allowed=1000,
    )


def _mood(valence: float = 1.0) -> Mood:
    return Mood(
        self_id="self-1",
        valence=valence,
        arousal=0.0,
        focus=0.0,
        last_tick_at=datetime.now(UTC),
    )


class _FakeMemory:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def store_episode(self, *, content: str, tier: str, **kwargs: Any) -> str:
        self.calls.append({"content": content, "tier": tier, **kwargs})
        return "mem-id"


class _FakeSecurity:
    async def scan_user_input(
        self, content: str, *, context: Sequence[Any] | None = None
    ) -> dict[str, Any]:
        return {"verdict": "allowed", "flags": []}

    async def scan_self_write(self, content: str, *, kind: str = "") -> dict[str, Any]:
        return {"verdict": "allowed", "flags": []}

    async def scan_tool_result(self, content: str, *, tool_name: str = "") -> dict[str, Any]:
        return {"verdict": "allowed", "flags": []}


class _FakeClassifier:
    async def classify_message(
        self, message: str, *, task_types: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return {"task_type": "general", "complexity": 0.5, "priority": "normal"}


class _ChatProviderDelay:
    """Chat provider double whose async seam stalls, exposing loop stalls."""

    def __init__(self, reply: str = "ok", delay: float = 0.2) -> None:
        self._reply = reply
        self._delay = delay

    async def acomplete(self, prompt: str, *, max_tokens: int | None = None, pool: str = "") -> str:
        await asyncio.sleep(self._delay)
        return self._reply


# ------------------------------------------------------------ runner tests ---


class TestSyncLoopRunner:
    def test_run_returns_the_coroutine_result(self) -> None:
        runner = SyncLoopRunner()

        async def work() -> int:
            await asyncio.sleep(0)
            return 42

        assert runner.run(work()) == 42
        runner.close()

    def test_run_propagates_the_coroutine_exception(self) -> None:
        runner = SyncLoopRunner()

        async def boom() -> None:
            await asyncio.sleep(0)
            raise ValueError("provider exploded")

        with pytest.raises(ValueError, match="provider exploded"):
            runner.run(boom())
        runner.close()

    def test_run_times_out_and_cancels_the_underlying_work(self) -> None:
        runner = SyncLoopRunner()
        observed: list[BaseException] = []

        async def stuck() -> None:
            try:
                await asyncio.sleep(30)
            except BaseException as exc:
                observed.append(exc)
                raise

        started = time.monotonic()
        with pytest.raises(TimeoutError, match="outstanding work cancelled"):
            runner.run(stuck(), timeout=0.05)
        elapsed = time.monotonic() - started
        # The bounded wait, not the 30s coroutine, decides the duration.
        assert elapsed < 5.0
        # Cancellation propagated into the coroutine on the dedicated loop.
        deadline = time.monotonic() + 5.0
        while not observed and time.monotonic() < deadline:
            time.sleep(0.005)
        assert observed and isinstance(observed[0], asyncio.CancelledError)
        # The outstanding registry drained with the cancelled call (read
        # through the same internal map close()/drain consume; there is no
        # production reader of this bookkeeping, so no public accessor exists).
        assert runner._outstanding == {}
        runner.close()

    def test_run_rejects_a_reentrant_call_from_the_same_loop(self) -> None:
        runner = SyncLoopRunner()
        caught: list[BaseException] = []

        async def reenter() -> None:
            # Running ON the dedicated loop: the wait could never finish.
            try:
                runner.run(asyncio.sleep(0))
            except ReentrantSyncCallError as exc:
                caught.append(exc)

        runner.run(reenter(), timeout=5.0)
        assert len(caught) == 1
        assert "reentered its own dedicated event loop" in str(caught[0])
        runner.close()

    def test_run_rejects_calls_after_close(self) -> None:
        runner = SyncLoopRunner()
        runner.close()

        async def work() -> None:
            await asyncio.sleep(0)

        with pytest.raises(SyncLoopClosedError):
            runner.run(work())

    def test_close_cancels_outstanding_work_and_joins_the_thread(self) -> None:
        runner = SyncLoopRunner()
        observed: list[BaseException] = []
        caller_result: list[BaseException] = []
        entered = threading.Event()

        async def stuck() -> None:
            entered.set()
            try:
                await asyncio.sleep(60)
            except BaseException as exc:
                observed.append(exc)
                raise

        def caller() -> None:
            try:
                runner.run(stuck(), timeout=30.0)
            except BaseException as exc:
                caller_result.append(exc)

        thread = threading.Thread(target=caller)
        thread.start()
        assert entered.wait(timeout=5.0)
        runner.close()
        thread.join(timeout=5.0)

        assert not thread.is_alive()
        assert observed and isinstance(observed[0], asyncio.CancelledError)
        # The blocked caller stops waiting when the work is cancelled.
        assert caller_result and isinstance(caller_result[0], asyncio.CancelledError)

    def test_close_is_idempotent_and_never_started_runner_is_a_noop(self) -> None:
        runner = SyncLoopRunner()
        runner.close()
        runner.close()

        async def work() -> None:
            await asyncio.sleep(0)

        with pytest.raises(SyncLoopClosedError):
            runner.run(work())
        runner.close()

    def test_concurrent_calls_share_one_dedicated_loop_thread(self) -> None:
        runner = SyncLoopRunner()
        loop_idents: list[int] = []
        lock = threading.Lock()
        started = threading.Barrier(8)

        async def work(i: int) -> int:
            with lock:
                loop_idents.append(threading.get_ident())
            await asyncio.sleep(0.01)
            return i * 2

        def caller(i: int) -> int:
            started.wait(timeout=5.0)
            return runner.run(work(i), timeout=10.0)

        # The callers are ordinary threads; the runner owns the only loop.
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(caller, i) for i in range(8)]
            results = [f.result(timeout=15.0) for f in futures]

        assert results == [i * 2 for i in range(8)]
        # All work ran on exactly one dedicated thread, never the callers'.
        caller_idents = {threading.get_ident()}
        assert len(set(loop_idents)) == 1
        assert not (set(loop_idents) & caller_idents)
        runner.close()

    def test_constructor_rejects_nonpositive_timeout(self) -> None:
        with pytest.raises(ValueError, match="timeout must be positive"):
            SyncLoopRunner(timeout=0)
        with pytest.raises(ValueError, match="timeout must be positive"):
            SyncLoopRunner(timeout=-1.0)


# ------------------------------------------------------------- bridge tests --


class TestTuringProviderBridgeSyncBoundary:
    def test_complete_returns_through_the_dedicated_boundary(self) -> None:
        client = FakeLLMClient(reply="hello #397")
        bridge = TuringProviderBridge(llm_client=client, pools=[_pool()])
        try:
            assert bridge.complete("hi") == "hello #397"
            assert client.calls[0]["model"] == "test-model"
        finally:
            bridge.close()

    def test_complete_propagates_provider_exceptions(self) -> None:
        bridge = TuringProviderBridge(
            llm_client=FakeLLMClient(raises=RuntimeError("boom")),
            pools=[_pool()],
        )
        with pytest.raises(RuntimeError, match="boom"):
            bridge.complete("hi")
        bridge.close()

    def test_complete_is_bounded_and_cancels_a_stuck_provider(self) -> None:
        client = FakeLLMClient(delay=30.0)
        bridge = TuringProviderBridge(llm_client=client, pools=[_pool()], sync_timeout_seconds=0.05)
        try:
            with pytest.raises(TimeoutError):
                bridge.complete("hi")
        finally:
            bridge.close()
        # Cancellation reached the stuck provider instead of stranding it.
        assert client.cancelled == 1
        assert client.completed == 0

    def test_default_sync_timeout_is_bounded(self) -> None:
        assert DEFAULT_SYNC_TIMEOUT_SECONDS > 0
        bridge = TuringProviderBridge(llm_client=FakeLLMClient(), pools=[_pool()])
        try:
            # The bridge wires its runner with the bounded default, never an
            # unbounded wait.
            assert bridge._sync_runner._default_timeout == DEFAULT_SYNC_TIMEOUT_SECONDS
        finally:
            bridge.close()

    async def test_complete_from_a_worker_thread_spares_the_caller_loop(self) -> None:
        """A sync call made while a loop is running offloads to the dedicated
        boundary; a stuck provider surfaces as TimeoutError, not a deadlock."""
        client = FakeLLMClient(delay=30.0)
        bridge = TuringProviderBridge(llm_client=client, pools=[_pool()], sync_timeout_seconds=0.05)
        try:
            with pytest.raises(TimeoutError):
                await asyncio.to_thread(bridge.complete, "hi")
        finally:
            bridge.close()

    def test_close_cancels_outstanding_bridge_work(self) -> None:
        client = FakeLLMClient(delay=30.0)
        bridge = TuringProviderBridge(llm_client=client, pools=[_pool()])
        caller_result: list[BaseException] = []
        entered = threading.Event()

        def caller() -> None:
            entered.set()
            try:
                bridge.complete("hi")
            except BaseException as exc:
                caller_result.append(exc)

        thread = threading.Thread(target=caller)
        thread.start()
        assert entered.wait(timeout=5.0)
        bridge.close()
        thread.join(timeout=5.0)

        assert not thread.is_alive()
        assert client.cancelled == 1
        assert caller_result and isinstance(caller_result[0], asyncio.CancelledError)


# ------------------------------------------------- async-seam regression -----


class TestAsyncSeamDoesNotBlockTheLoop:
    async def test_chat_session_keeps_the_loop_ticking_during_model_call(self) -> None:
        """Regression for the #397 freeze: ``handle_message`` used to block
        the loop on an unbounded future for the whole provider call; it now
        awaits the async seam and unrelated work keeps progressing."""
        provider = _ChatProviderDelay(delay=0.2)
        session = TuringChatSession(
            memory=_FakeMemory(),  # type: ignore[arg-type]
            provider=provider,  # type: ignore[arg-type]
            classifier=_FakeClassifier(),  # type: ignore[arg-type]
            security=_FakeSecurity(),  # type: ignore[arg-type]
            self_id="self-1",
        )

        ticks = 0
        stop = asyncio.Event()

        async def heartbeat() -> None:
            nonlocal ticks
            while not stop.is_set():
                await asyncio.sleep(0.01)
                ticks += 1

        heartbeat_task = asyncio.create_task(heartbeat())
        await asyncio.sleep(0.01)
        ticks_before = ticks
        reply = await session.handle_message("hello")
        stop.set()
        await heartbeat_task

        assert reply == "ok"
        # The loop processed heartbeats throughout the 0.2s model call; the
        # old blocking path would have stalled them completely.
        assert ticks - ticks_before >= 10

    async def test_blog_producer_uses_the_async_seam(self) -> None:
        """A provider exposing only the async seam works: producers must not
        depend on the blocking sync bridge path from async code."""

        class AsyncOnlyProvider:
            def __init__(self) -> None:
                self.prompts: list[str] = []

            async def acomplete(
                self, prompt: str, *, max_tokens: int | None = None, pool: str = ""
            ) -> str:
                self.prompts.append(prompt)
                return "TITLE: Async Seam\nBody line."

        provider = AsyncOnlyProvider()
        producer = BlogProducer(
            memory=_FakeMemory(),  # type: ignore[arg-type]
            provider=provider,  # type: ignore[arg-type]
            security=_FakeSecurity(),  # type: ignore[arg-type]
            self_id="self-1",
            facet_scores={"creativity": 5.0},
        )
        result = await producer.produce(_mood())
        assert result == "# Async Seam\n\nBody line."
        assert len(provider.prompts) == 1
