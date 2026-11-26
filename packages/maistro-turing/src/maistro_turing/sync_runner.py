"""Dedicated thread/loop boundary for synchronous callers of async work (#397).

Issue #397: Turing's synchronous bridge used to answer calls made on an
event-loop thread by submitting ``asyncio.run`` to a throwaway thread pool and
blocking on an **unbounded** ``Future.result()``. A pending or stuck future
froze every coroutine on the calling loop — including any work the submitted
coroutine itself needed to finish — and shutdown had no way to reclaim the
stranded work.

This module gives synchronous callers a boundary with exactly one shape:

- the coroutine never runs on the calling thread. Work executes on one
  dedicated asyncio loop owned by one daemon thread, independent of any
  caller's loop;
- ``run()`` waits a **bounded** time on the completion future;
- a timed-out call is cancelled on the dedicated loop, so cancellation
  propagates into the coroutine instead of leaking stuck work;
- a call made from the runner's own loop thread is rejected immediately —
  that reentrancy would deadlock the loop against itself;
- ``close()`` cancels outstanding work, drains the loop, and joins the
  thread, so shutdown never strands a stuck integration.

Event-loop callers should prefer the async seam of the subsystem they are
bridging to (``await bridge.acomplete(...)``); a sync call from a loop thread
still works here, but it occupies that loop for at most the bounded timeout,
which is why production async paths must not use it.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import itertools
import threading
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")

DEFAULT_SYNC_TIMEOUT_SECONDS: float = 120.0

# Grace period that lets the dedicated loop begin a submitted task before a
# timing-out caller reclaims the never-started inner coroutine.
_START_GRACE_SECONDS: float = 0.05


class ReentrantSyncCallError(RuntimeError):
    """A synchronous bridge call reentered its own dedicated event loop.

    Running the wait inside the loop that must complete the work deadlocks
    the loop against itself, so the call is rejected instead of hanging.
    """


class SyncLoopClosedError(RuntimeError):
    """A synchronous bridge call was attempted after the runner shut down."""


class SyncLoopRunner:
    """One daemon thread owning one asyncio loop for synchronous callers.

    Contract (issue #397):

    - bounded wait: ``run()`` raises :class:`TimeoutError` after ``timeout``
      seconds instead of blocking its caller forever;
    - cancellation propagation: a timed-out or shut-down call cancels the
      underlying task on the dedicated loop, so a stuck integration cannot
      accumulate unbounded stranded work;
    - reentrancy rejection: a call made from the runner's own loop thread
      raises :class:`ReentrantSyncCallError` immediately;
    - clean shutdown: ``close()`` cancels outstanding work, drains the loop,
      and joins the thread. It is idempotent.

    The loop thread starts lazily on the first ``run()``, so constructing a
    runner (or a bridge holding one) never spawns a thread.
    """

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_SYNC_TIMEOUT_SECONDS,
        name: str = "maistro-sync-loop",
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self._default_timeout = timeout
        self._name = name
        self._lock = threading.Lock()
        self._started = threading.Event()
        self._closed = False
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._outstanding: dict[int, asyncio.Task[Any]] = {}
        self._call_ids = itertools.count()

    # ------------------------------------------------------------- public --

    def run(self, coro: Coroutine[Any, Any, T], *, timeout: float | None = None) -> T:
        """Run ``coro`` on the dedicated loop and block at most ``timeout``.

        Returns the coroutine's result. ``TimeoutError`` after the bounded
        wait, with the coroutine cancelled on the dedicated loop; exceptions
        raised by the coroutine propagate unchanged.
        """
        wait = self._default_timeout if timeout is None else timeout
        if wait <= 0:
            coro.close()
            raise ValueError("timeout must be positive")

        if self._is_own_loop_thread():
            coro.close()
            raise ReentrantSyncCallError(
                "sync bridge call reentered its own dedicated event loop; "
                "await the async seam (e.g. acomplete) inside async code instead"
            )

        with self._lock:
            if self._closed:
                coro.close()
                raise SyncLoopClosedError("sync loop runner is closed; no further calls accepted")
            loop = self._ensure_started_locked()

        inner_started = threading.Event()
        call_id = next(self._call_ids)

        async def _tracked() -> T:
            # Register before anything can block, so a timeout always finds
            # the task to cancel; the flag releases a timing-out caller from
            # having to reclaim the inner coroutine.
            task = asyncio.current_task()
            if task is not None:
                self._outstanding[call_id] = task
            inner_started.set()
            try:
                return await coro
            finally:
                self._outstanding.pop(call_id, None)

        future = asyncio.run_coroutine_threadsafe(_tracked(), loop)
        try:
            return future.result(wait)
        except concurrent.futures.CancelledError:
            # close() cancelled the outstanding task; surface the standard
            # cancellation signal rather than the concurrent-bridging error
            # (the same class on Pythons where the two are aliased).
            raise asyncio.CancelledError from None
        except concurrent.futures.TimeoutError:
            self._cancel_timed_out(coro, future, inner_started)
            raise TimeoutError(
                f"sync bridge call did not finish within {wait}s; outstanding work cancelled"
            ) from None

    def close(self, *, timeout: float = 5.0) -> None:
        """Cancel outstanding work, drain the dedicated loop, join the thread.

        Idempotent: closing twice (or closing a never-started runner) is a
        no-op. If a cancelled task refuses to finish within ``timeout`` the
        daemon thread is left to the process reaper and further ``run()``
        calls keep failing with :class:`SyncLoopClosedError`.
        """
        with self._lock:
            if self._closed:
                return
            self._closed = True
            thread, loop = self._thread, self._loop
        if thread is None or loop is None:
            return
        if loop.is_running():
            loop.call_soon_threadsafe(self._drain_and_stop)
        thread.join(timeout)
        if thread.is_alive():
            # A task ignored cancellation; leave the daemon thread alone
            # rather than closing a live loop underneath it.
            return
        if not loop.is_closed():
            loop.close()

    # --------------------------------------------------------- internal --

    def _is_own_loop_thread(self) -> bool:
        thread = self._thread
        return thread is not None and threading.current_thread() is thread

    def _ensure_started_locked(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            thread = threading.Thread(
                target=self._thread_main,
                name=self._name,
                daemon=True,
            )
            self._thread = thread
            thread.start()
            if not self._started.wait(timeout=10.0):
                raise RuntimeError("sync loop thread failed to start")
        assert self._loop is not None
        return self._loop

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            self._loop = loop
            self._started.set()
            loop.run_forever()
        finally:
            asyncio.set_event_loop(None)
            with contextlib.suppress(RuntimeError):  # loop still running
                loop.close()

    def _drain_and_stop(self) -> None:
        """Runs on the dedicated loop thread: cancel outstanding, then stop."""
        loop = self._loop

        async def _drain() -> None:
            tasks = [t for t in list(self._outstanding.values()) if not t.done()]
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            assert loop is not None
            loop.stop()

        if loop is not None:
            loop.create_task(_drain())

    def _cancel_timed_out(
        self,
        coro: Coroutine[Any, Any, T],
        future: concurrent.futures.Future[T],
        inner_started: threading.Event,
    ) -> None:
        # Cancelling the concurrent future chains cancellation into the task
        # on the dedicated loop, whether it is queued or already running.
        future.cancel()
        if not inner_started.wait(_START_GRACE_SECONDS):
            # The wrapper never began, so nothing on the loop owns the inner
            # coroutine; reclaim it here to avoid a spurious "never awaited"
            # warning at garbage collection. If it started inside the grace
            # window the chain-cancel above already reached the task.
            with contextlib.suppress(RuntimeError):  # started within the race window
                coro.close()
