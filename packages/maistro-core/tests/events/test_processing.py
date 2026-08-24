"""Tests for the idempotent event processing loop (SPEC-070226-b234).

Covers trigger fan-out, retry-with-cap, cursor semantics, the crash-replay
idempotency scenario, and the HTTPHandlerCaller.
"""

from __future__ import annotations

import httpx
import pytest

from maistro.events.durable_log import InMemoryEventLog, LoggedEvent
from maistro.events.invocations import (
    MAX_ATTEMPTS,
    InMemoryInvocationStore,
    InvocationStatus,
)
from maistro.events.processing import (
    HANDLER_FAILED_EVENT,
    HandlerCallError,
    HTTPHandlerCaller,
    process_events,
)
from maistro.events.trigger_store import InMemoryTriggerStore, TriggerDefinition


class RecordingCaller:
    """Handler caller that records calls and fails on command."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []
        self.fail_keys: set[tuple[str, int]] = set()
        self.fail_times: dict[tuple[str, int], int] = {}

    async def __call__(self, trigger: TriggerDefinition, event: LoggedEvent) -> None:
        key = (trigger.trigger_id, event.id)
        self.calls.append(key)
        if key in self.fail_keys:
            raise HandlerCallError("permanent failure")
        remaining = self.fail_times.get(key, 0)
        if remaining > 0:
            self.fail_times[key] = remaining - 1
            raise HandlerCallError("transient failure")


@pytest.fixture
def stores() -> tuple[InMemoryEventLog, InMemoryTriggerStore, InMemoryInvocationStore]:
    return InMemoryEventLog(), InMemoryTriggerStore(), InMemoryInvocationStore()


@pytest.mark.ac("SPEC-070226-b234/AC-3")
async def test_matching_trigger_invoked_once(
    stores: tuple[InMemoryEventLog, InMemoryTriggerStore, InMemoryInvocationStore],
) -> None:
    log, triggers, invocations = stores
    t = TriggerDefinition(name="agents", event_pattern="agent.*")
    await triggers.add(t)
    e = await log.append("agent.created")
    await log.append("task.created")  # no matching trigger
    caller = RecordingCaller()

    cursor = await process_events(log, triggers, invocations, caller)

    assert caller.calls == [(t.trigger_id, e.id)]
    inv = await invocations.get(t.trigger_id, e.id)
    assert inv is not None and inv.status is InvocationStatus.SUCCESS
    assert cursor == 2

    # Second tick from the cursor: nothing to do.
    cursor2 = await process_events(log, triggers, invocations, caller, after_id=cursor)
    assert cursor2 == cursor
    assert len(caller.calls) == 1


async def test_multiple_triggers_fan_out(
    stores: tuple[InMemoryEventLog, InMemoryTriggerStore, InMemoryInvocationStore],
) -> None:
    log, triggers, invocations = stores
    t1 = TriggerDefinition(name="a", event_pattern="agent.*")
    t2 = TriggerDefinition(name="b", event_pattern="agent.created")
    await triggers.add(t1)
    await triggers.add(t2)
    e = await log.append("agent.created")
    caller = RecordingCaller()

    await process_events(log, triggers, invocations, caller)

    assert sorted(caller.calls) == sorted([(t1.trigger_id, e.id), (t2.trigger_id, e.id)])


@pytest.mark.ac("SPEC-070226-b234/AC-4")
async def test_retry_up_to_three_attempts_then_failed(
    stores: tuple[InMemoryEventLog, InMemoryTriggerStore, InMemoryInvocationStore],
) -> None:
    log, triggers, invocations = stores
    t = TriggerDefinition(name="always-fails", event_pattern="task.failed")
    await triggers.add(t)
    e = await log.append("task.failed")
    caller = RecordingCaller()
    caller.fail_keys.add((t.trigger_id, e.id))

    cursor = 0
    for expected_attempts, expected_status in [
        (1, InvocationStatus.RETRYING),
        (2, InvocationStatus.RETRYING),
        (3, InvocationStatus.FAILED),
    ]:
        cursor = await process_events(log, triggers, invocations, caller, after_id=cursor)
        inv = await invocations.get(t.trigger_id, e.id)
        assert inv is not None
        assert inv.attempts == expected_attempts
        assert inv.status is expected_status
        assert "failure" in inv.last_error

    # Exactly MAX_ATTEMPTS calls, never more, even on further ticks.
    await process_events(log, triggers, invocations, caller, after_id=cursor)
    assert len(caller.calls) == MAX_ATTEMPTS

    # A handler.failed event was appended to the log.
    failed_events = await log.query(event_type=HANDLER_FAILED_EVENT)
    assert len(failed_events) == 1
    assert failed_events[0].payload["event_id"] == e.id
    assert failed_events[0].source == "reactor"


@pytest.mark.ac("SPEC-070226-b234/AC-4")
async def test_transient_failure_recovers(
    stores: tuple[InMemoryEventLog, InMemoryTriggerStore, InMemoryInvocationStore],
) -> None:
    log, triggers, invocations = stores
    t = TriggerDefinition(name="flaky", event_pattern="x.y")
    await triggers.add(t)
    e = await log.append("x.y")
    caller = RecordingCaller()
    caller.fail_times[(t.trigger_id, e.id)] = 2  # fail twice, then succeed

    cursor = 0
    for _ in range(3):
        cursor = await process_events(log, triggers, invocations, caller, after_id=cursor)
    inv = await invocations.get(t.trigger_id, e.id)
    assert inv is not None
    assert inv.status is InvocationStatus.SUCCESS
    assert inv.attempts == 3
    assert inv.last_error == ""
    assert cursor == e.id


async def test_cursor_holds_back_on_unsettled_event(
    stores: tuple[InMemoryEventLog, InMemoryTriggerStore, InMemoryInvocationStore],
) -> None:
    log, triggers, invocations = stores
    t = TriggerDefinition(name="flaky", event_pattern="a.*")
    await triggers.add(t)
    e1 = await log.append("a.one")
    await log.append("a.two")
    caller = RecordingCaller()
    caller.fail_times[(t.trigger_id, e1.id)] = 1

    cursor = await process_events(log, triggers, invocations, caller)
    # First event is retrying: cursor must not advance past it.
    assert cursor < e1.id or cursor == 0
    assert cursor == 0

    cursor = await process_events(log, triggers, invocations, caller, after_id=cursor)
    assert cursor == 2  # both settled now


@pytest.mark.ac("SPEC-070226-b234/AC-3")
async def test_crash_replay_no_duplicate_successful_invocations(
    stores: tuple[InMemoryEventLog, InMemoryTriggerStore, InMemoryInvocationStore],
) -> None:
    """Idempotency crash-replay: handler A succeeds, handler B crashes
    mid-processing; the whole batch is reprocessed from cursor 0 (simulating
    reactor restart with lost cursor); A is NOT re-invoked, B completes, and
    each (trigger, event) pair has exactly one successful invocation."""
    log, triggers, invocations = stores
    ok = TriggerDefinition(name="ok", event_pattern="agent.*")
    crashy = TriggerDefinition(name="crashy", event_pattern="agent.*")
    await triggers.add(ok)
    await triggers.add(crashy)
    e = await log.append("agent.delegated")

    caller = RecordingCaller()
    caller.fail_times[(crashy.trigger_id, e.id)] = 1  # crash on first attempt

    # First pass: 'ok' succeeds, 'crashy' fails mid-processing.
    await process_events(log, triggers, invocations, caller)
    inv_ok = await invocations.get(ok.trigger_id, e.id)
    inv_crashy = await invocations.get(crashy.trigger_id, e.id)
    assert inv_ok is not None and inv_ok.status is InvocationStatus.SUCCESS
    assert inv_crashy is not None and inv_crashy.status is InvocationStatus.RETRYING

    # "Restart": replay everything from cursor 0.
    await process_events(log, triggers, invocations, caller, after_id=0)
    await process_events(log, triggers, invocations, caller, after_id=0)

    # 'ok' was called exactly once ever; 'crashy' twice (fail + success).
    assert caller.calls.count((ok.trigger_id, e.id)) == 1
    assert caller.calls.count((crashy.trigger_id, e.id)) == 2
    inv_crashy = await invocations.get(crashy.trigger_id, e.id)
    assert inv_crashy is not None and inv_crashy.status is InvocationStatus.SUCCESS

    # Exactly one invocation row per (trigger, event) — no duplicates.
    rows = await invocations.list_for_event(e.id)
    assert len(rows) == 2
    assert all(r.status is InvocationStatus.SUCCESS for r in rows)


async def test_disabled_trigger_not_invoked(
    stores: tuple[InMemoryEventLog, InMemoryTriggerStore, InMemoryInvocationStore],
) -> None:
    log, triggers, invocations = stores
    t = TriggerDefinition(name="off", event_pattern="agent.*", enabled=False)
    await triggers.add(t)
    await log.append("agent.created")
    caller = RecordingCaller()
    await process_events(log, triggers, invocations, caller)
    assert caller.calls == []


async def test_limit_batches(
    stores: tuple[InMemoryEventLog, InMemoryTriggerStore, InMemoryInvocationStore],
) -> None:
    log, triggers, invocations = stores
    t = TriggerDefinition(name="all", event_pattern="e.*")
    await triggers.add(t)
    for _ in range(5):
        await log.append("e.n")
    caller = RecordingCaller()
    cursor = await process_events(log, triggers, invocations, caller, limit=2)
    assert cursor == 2
    cursor = await process_events(log, triggers, invocations, caller, after_id=cursor, limit=10)
    assert cursor == 5
    assert len(caller.calls) == 5


class TestHTTPHandlerCaller:
    async def test_posts_event_json(self) -> None:
        seen: dict[str, object] = {}

        def handle(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["body"] = request.read()
            return httpx.Response(200)

        transport = httpx.MockTransport(handle)
        async with httpx.AsyncClient(transport=transport) as client:
            caller = HTTPHandlerCaller(client=client)
            trigger = TriggerDefinition(handler_url="http://handlers.local/log")
            event = LoggedEvent(id=7, event_type="agent.created", payload={"a": 1})
            await caller(trigger, event)

        assert seen["url"] == "http://handlers.local/log"
        assert b'"agent.created"' in seen["body"]  # type: ignore[operator]

    async def test_raises_on_error_status(self) -> None:
        transport = httpx.MockTransport(lambda _: httpx.Response(500, text="nope"))
        async with httpx.AsyncClient(transport=transport) as client:
            caller = HTTPHandlerCaller(client=client)
            trigger = TriggerDefinition(handler_url="http://handlers.local/x")
            event = LoggedEvent(id=1, event_type="a.b")
            with pytest.raises(HandlerCallError, match="500"):
                await caller(trigger, event)

    async def test_raises_on_transport_error(self) -> None:
        def handle(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        transport = httpx.MockTransport(handle)
        async with httpx.AsyncClient(transport=transport) as client:
            caller = HTTPHandlerCaller(client=client)
            trigger = TriggerDefinition(handler_url="http://handlers.local/x")
            event = LoggedEvent(id=1, event_type="a.b")
            with pytest.raises(HandlerCallError, match="transport error"):
                await caller(trigger, event)


class YieldingCaller(RecordingCaller):
    """A handler that actually suspends, so the workers genuinely interleave.

    `RecordingCaller.__call__` is `async def` with no `await` in it, so it never
    yields — and `asyncio.gather` over coroutines that never yield runs them one
    after another to completion. Every worker after the first then finds the
    invocation already terminal and skips, and a test built on it passes against
    the *unfixed* dispatch loop: worker 2 never overlaps worker 1, so there is
    no race to lose. Verified by reverting `process_events` to `get_or_create`
    and watching the test still pass.

    Suspending inside the handler is what puts a second worker at `claim` while
    the first is mid-dispatch, which is the only arrangement in which the bug
    exists.
    """

    async def __call__(self, trigger: TriggerDefinition, event: LoggedEvent) -> None:
        import asyncio

        self.calls.append((trigger.trigger_id, event.id))
        for _ in range(4):
            await asyncio.sleep(0)


class TestConcurrentWorkersDispatchOnce:
    """Two workers, one event, one handler call (Codex review, #181).

    The store's composite key made racing workers converge on one invocation
    *row*, and `process_events` read any non-terminal row as permission to
    dispatch — so both workers called the handler and the bookkeeping showed a
    single tidy invocation either way. ADR-086 says a handler is invoked "at
    most once successfully per event"; one row and two calls is not that.

    These run at the `process_events` level rather than the store level on
    purpose: `test_durable_store_conformance.py` proves `claim` is atomic, and
    this proves the dispatch loop actually goes through it. The store being
    correct while the caller ignores it is exactly the shape of the original
    bug.
    """

    @staticmethod
    async def _one_event_two_workers(caller, workers: int = 8):
        import asyncio

        event_log = InMemoryEventLog()
        trigger_store = InMemoryTriggerStore()
        invocations = InMemoryInvocationStore()
        await trigger_store.add(
            TriggerDefinition(
                trigger_id="t1",
                name="t1",
                event_pattern="task.created",
                handler_url="http://handler.invalid",
            )
        )
        await event_log.append("task.created")

        await asyncio.gather(
            *(process_events(event_log, trigger_store, invocations, caller) for _ in range(workers))
        )
        return invocations

    async def test_only_one_worker_calls_the_handler(self):
        caller = YieldingCaller()
        invocations = await self._one_event_two_workers(caller)

        assert caller.calls == [("t1", 1)], f"the handler fired {len(caller.calls)} times"
        assert len(await invocations.list_for_event(1)) == 1

    async def test_the_surviving_invocation_records_the_success(self):
        """A worker that skipped dispatch must not leave the invocation looking
        unhandled — the cursor would then never advance past the event."""
        caller = YieldingCaller()
        invocations = await self._one_event_two_workers(caller)

        invocation = await invocations.get("t1", 1)
        assert invocation is not None
        assert invocation.status is InvocationStatus.SUCCESS

    async def test_a_worker_that_skips_does_not_advance_past_an_unsettled_event(self):
        """The other half: skipping is not the same as settled. A worker that
        finds the event owned by someone still running it must hold its cursor,
        or the event is dropped from every later batch."""
        event_log = InMemoryEventLog()
        trigger_store = InMemoryTriggerStore()
        invocations = InMemoryInvocationStore()
        await trigger_store.add(
            TriggerDefinition(
                trigger_id="t1",
                name="t1",
                event_pattern="task.created",
                handler_url="http://handler.invalid",
            )
        )
        event = await event_log.append("task.created")

        # Another worker holds a live lease and has not finished.
        held = await invocations.claim("t1", event.id)
        assert held is not None

        caller = RecordingCaller()
        cursor = await process_events(event_log, trigger_store, invocations, caller)

        assert caller.calls == []
        assert cursor == 0, "the cursor advanced past an event still being handled"
