---
inventory-delta:
  packages/maistro-turing/tests: +20
---
# Issue 397 — the Turing sync bridge stops blocking the event loop

## What changed

Turing's synchronous provider bridge answered calls made on an event-loop
thread by submitting `asyncio.run` to a throwaway `ThreadPoolExecutor` and
blocking on an **unbounded** `Future.result()`. A pending or stuck provider
future therefore froze every coroutine on the calling loop — including any
work the submitted coroutine itself needed to finish — and nothing could
reclaim the stranded work at shutdown.

The fix (`packages/maistro-turing/src/maistro_turing/sync_runner.py`, new)
gives sync callers one dedicated thread owning one dedicated loop
(`SyncLoopRunner`): a bounded `Future.result(timeout)` wait, cancellation
propagation into the coroutine on timeout or shutdown, immediate rejection of
reentrant calls from the runner's own loop, and a `close()` that cancels
outstanding work, drains the loop, and joins the thread.
`TuringProviderBridge.complete` now runs through that boundary (bounded by
`sync_timeout_seconds`, default 120s) and gained a `close()`; the per-call
thread pool and the unbounded wait are gone.

The production async call paths no longer touch the blocking seam at all:
`TuringChatSession.handle_message` and the four producers now
`await provider.acomplete(...)`, so the owning loop keeps ticking while a
model call is in flight. Backend chat-route tests that pinned the sync seam
(`complete` monkeypatches) were moved to the async seam, which is the
contract under test since the sync path must never run on the loop.

## Inventory delta

`packages/maistro-turing/tests` gains 20 node IDs in
`test_sync_runner.py`: the `SyncLoopRunner` matrix (success, exception,
timeout-with-cancellation, reentrancy rejection, post-close rejection,
shutdown cancelling outstanding work and joining the thread, close
idempotence, eight concurrent callers sharing one dedicated thread,
non-positive-timeout rejection), the bridge boundary (bounded stuck-provider
timeout with cancellation observed in the provider, exception propagation,
worker-thread offload while a loop runs, `close()` cancelling in-flight
work, bounded default), and the two freeze regressions: the chat session's
loop keeps taking heartbeats throughout a 0.2s model call, and a producer
works against a provider exposing only the async seam.

CI-repair round (+3): the diff-coverage gate showed the timeout branch
matrix left real arcs unexercised — a non-positive per-call `run()` wait is
rejected (and its coroutine closed, not leaked), a caller timing out before
the wrapper began on the dedicated loop reclaims the never-started inner
coroutine, and `close()` leaves the daemon thread to the process reaper when
a cancelled task refuses to finish inside the join budget.

`packages/maistro-turing/backend/tests` is unchanged in count: the chat
tests were re-pointed from `complete` to `acomplete` without renaming.

## Ephemeral counts

maistro-turing tests: 190 → 210 (+20). Backend: 90 (unchanged).
