"""Tests for the idempotent event processing loop (SPEC-070226-b234, #1060).

Covers trigger fan-out, the claim/begin/settle dispatch protocol, the
classification table for post-effect crash windows, the receipt-reading
HTTPHandlerCaller, and the durable fake-receiver fault-injection phases.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from maistro.events.durable_log import InMemoryEventLog, LoggedEvent
from maistro.events.invocations import (
    MAX_ATTEMPTS,
    DeliveryAttemptLimitReached,
    DeliveryDisposition,
    DeliveryIdentity,
    HandlerCallOutcome,
    InMemoryInvocationStore,
    InvocationStatus,
    ReplaySafety,
    request_digest_v1,
)
from maistro.events.processing import (
    HANDLER_FAILED_EVENT,
    HTTPHandlerCaller,
    process_events,
    process_events_batch,
)
from maistro.events.trigger_store import (
    InMemoryTriggerStore,
    TriggerDefinition,
)

SAFE_TRIGGER_KWARGS = {
    "handler_url": "http://handlers.local/x",
    "replay_safety": ReplaySafety.IDEMPOTENT,
    "contract_ref": "contract-v1",
}


class RecordingCaller:
    """Handler caller that records calls and fails on command.

    Returns ``None`` (acknowledgment) unless scripted otherwise; scripted
    failures are explicit trusted evidence, as an injected caller may be.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []
        self.fail_keys: set[tuple[str, int]] = set()
        self.fail_times: dict[tuple[str, int], int] = {}
        self.raising_keys: set[tuple[str, int]] = set()

    async def __call__(
        self, trigger: TriggerDefinition, event: LoggedEvent
    ) -> HandlerCallOutcome | None:
        key = (trigger.trigger_id, event.id)
        self.calls.append(key)
        if key in self.fail_keys:
            return HandlerCallOutcome(
                DeliveryDisposition.NOT_APPLIED, "permanent_pre_commit_refusal"
            )
        if key in self.raising_keys:
            raise RuntimeError("connection lost after possible remote commit")
        remaining = self.fail_times.get(key, 0)
        if remaining > 0:
            self.fail_times[key] = remaining - 1
            return HandlerCallOutcome(DeliveryDisposition.NOT_APPLIED, "pre_commit_refusal")
        return None


class FakeReceiver:
    """A durable recipient: atomically binds delivery key + digest to commit.

    The #1060 §6 oracle shape: repeated POSTs carrying the same key are one
    logical committed effect; the binding is atomic (a single lock guards the
    read-decide-write), as an idempotent V1 recipient's commit must be.
    """

    def __init__(self) -> None:
        self.received: list[tuple[str, str]] = []
        self.committed: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def receive(self, key: str, digest: str) -> None:
        async with self._lock:
            self.received.append((key, digest))
            self.committed.setdefault(key, digest)

    @property
    def logical_effects(self) -> int:
        return len(self.committed)


@pytest.fixture
def stores() -> tuple[InMemoryEventLog, InMemoryTriggerStore, InMemoryInvocationStore]:
    return InMemoryEventLog(), InMemoryTriggerStore(), InMemoryInvocationStore()


@pytest.mark.ac("SPEC-070226-b234/AC-3")
async def test_matching_trigger_invoked_once(
    stores: tuple[InMemoryEventLog, InMemoryTriggerStore, InMemoryInvocationStore],
) -> None:
    log, triggers, invocations = stores
    t = TriggerDefinition(name="agents", event_pattern="agent.*", **SAFE_TRIGGER_KWARGS)
    await triggers.add(t)
    e = await log.append("agent.created")
    await log.append("task.created")  # no matching trigger
    caller = RecordingCaller()

    cursor = await process_events(log, triggers, invocations, caller)

    assert caller.calls == [(t.trigger_id, e.id)]
    inv = await invocations.get(t.trigger_id, e.id)
    assert inv is not None and inv.is_successful_delivery
    assert inv.attempts == 1
    assert inv.delivery_key is not None
    assert cursor == 2

    # Second tick from the cursor: nothing to do.
    cursor2 = await process_events(log, triggers, invocations, caller, after_id=cursor)
    assert cursor2 == cursor
    assert len(caller.calls) == 1


async def test_multiple_triggers_fan_out(
    stores: tuple[InMemoryEventLog, InMemoryTriggerStore, InMemoryInvocationStore],
) -> None:
    log, triggers, invocations = stores
    t1 = TriggerDefinition(name="a", event_pattern="agent.*", **SAFE_TRIGGER_KWARGS)
    t2 = TriggerDefinition(name="b", event_pattern="agent.created", **SAFE_TRIGGER_KWARGS)
    await triggers.add(t1)
    await triggers.add(t2)
    e = await log.append("agent.created")
    caller = RecordingCaller()

    await process_events(log, triggers, invocations, caller)

    assert sorted(caller.calls) == sorted([(t1.trigger_id, e.id), (t2.trigger_id, e.id)])
    # Each trigger's receipt has its own allocated delivery key.
    r1 = await invocations.get(t1.trigger_id, e.id)
    r2 = await invocations.get(t2.trigger_id, e.id)
    assert r1 is not None and r2 is not None
    assert r1.delivery_key != r2.delivery_key


@pytest.mark.ac("SPEC-070226-b234/AC-4")
async def test_retry_up_to_three_attempts_then_failed(
    stores: tuple[InMemoryEventLog, InMemoryTriggerStore, InMemoryInvocationStore],
) -> None:
    log, triggers, invocations = stores
    t = TriggerDefinition(name="always-fails", event_pattern="task.failed", **SAFE_TRIGGER_KWARGS)
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
        assert inv.last_error_code == "permanent_pre_commit_refusal"

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
    t = TriggerDefinition(name="flaky", event_pattern="x.y", **SAFE_TRIGGER_KWARGS)
    await triggers.add(t)
    e = await log.append("x.y")
    caller = RecordingCaller()
    caller.fail_times[(t.trigger_id, e.id)] = 2  # fail twice, then succeed

    cursor = 0
    for _ in range(3):
        cursor = await process_events(log, triggers, invocations, caller, after_id=cursor)
    inv = await invocations.get(t.trigger_id, e.id)
    assert inv is not None
    assert inv.is_successful_delivery
    assert inv.attempts == 3
    assert cursor == e.id


async def test_cursor_holds_back_on_unsettled_event(
    stores: tuple[InMemoryEventLog, InMemoryTriggerStore, InMemoryInvocationStore],
) -> None:
    log, triggers, invocations = stores
    t = TriggerDefinition(name="flaky", event_pattern="a.*", **SAFE_TRIGGER_KWARGS)
    await triggers.add(t)
    e1 = await log.append("a.one")
    await log.append("a.two")
    caller = RecordingCaller()
    caller.fail_times[(t.trigger_id, e1.id)] = 1

    cursor = await process_events(log, triggers, invocations, caller)
    # First event is retrying: cursor must not advance past it.
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
    each (trigger, event) pair has exactly one settled receipt."""
    log, triggers, invocations = stores
    ok = TriggerDefinition(name="ok", event_pattern="agent.*", **SAFE_TRIGGER_KWARGS)
    crashy = TriggerDefinition(name="crashy", event_pattern="agent.*", **SAFE_TRIGGER_KWARGS)
    await triggers.add(ok)
    await triggers.add(crashy)
    e = await log.append("agent.delegated")

    caller = RecordingCaller()
    caller.fail_times[(crashy.trigger_id, e.id)] = 1  # crash on first attempt

    # First pass: 'ok' succeeds, 'crashy' fails mid-processing.
    await process_events(log, triggers, invocations, caller)
    inv_ok = await invocations.get(ok.trigger_id, e.id)
    inv_crashy = await invocations.get(crashy.trigger_id, e.id)
    assert inv_ok is not None and inv_ok.is_successful_delivery
    assert inv_crashy is not None and inv_crashy.status is InvocationStatus.RETRYING

    # "Restart": replay everything from cursor 0.
    await process_events(log, triggers, invocations, caller, after_id=0)
    await process_events(log, triggers, invocations, caller, after_id=0)

    # 'ok' was called exactly once ever; 'crashy' twice (fail + success).
    assert caller.calls.count((ok.trigger_id, e.id)) == 1
    assert caller.calls.count((crashy.trigger_id, e.id)) == 2
    inv_crashy = await invocations.get(crashy.trigger_id, e.id)
    assert inv_crashy is not None and inv_crashy.is_successful_delivery

    # Exactly one receipt per (trigger, event) — no duplicates.
    rows = await invocations.list_for_event(e.id)
    assert len(rows) == 2
    assert all(r.is_successful_delivery for r in rows)


async def test_disabled_trigger_not_invoked(
    stores: tuple[InMemoryEventLog, InMemoryTriggerStore, InMemoryInvocationStore],
) -> None:
    log, triggers, invocations = stores
    t = TriggerDefinition(name="off", event_pattern="agent.*", enabled=False, **SAFE_TRIGGER_KWARGS)
    await triggers.add(t)
    await log.append("agent.created")
    caller = RecordingCaller()
    await process_events(log, triggers, invocations, caller)
    assert caller.calls == []


async def test_limit_batches(
    stores: tuple[InMemoryEventLog, InMemoryTriggerStore, InMemoryInvocationStore],
) -> None:
    log, triggers, invocations = stores
    t = TriggerDefinition(name="all", event_pattern="e.*", **SAFE_TRIGGER_KWARGS)
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
    """The receipt-reading caller: no receipt, no key, no send."""

    async def _prepared_receipt(
        self, invocations: InMemoryInvocationStore
    ) -> tuple[TriggerDefinition, LoggedEvent, str]:
        trigger = TriggerDefinition(trigger_id="t-call", **SAFE_TRIGGER_KWARGS)
        event = LoggedEvent(id=7, event_type="agent.created", payload={"a": 1})
        identity = DeliveryIdentity(
            handler_url=trigger.handler_url,
            request_digest=request_digest_v1(trigger.handler_url, event),
            replay_safety=trigger.effective_replay_safety,
            contract_ref=trigger.contract_ref,
        )
        claimed = await invocations.claim(trigger.trigger_id, event.id, delivery=identity)
        assert claimed is not None
        begun = await invocations.begin_dispatch(
            trigger.trigger_id,
            event.id,
            claim_token=claimed.claim_token,
            expected_revision=claimed.revision,
            delivery=identity,
        )
        assert begun is not None
        return trigger, event, claimed.delivery_key or ""

    async def test_posts_event_json_with_the_persisted_delivery_key(self) -> None:
        seen: dict[str, object] = {}

        def handle(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["body"] = request.read()
            seen["headers"] = dict(request.headers)
            return httpx.Response(200)

        invocations = InMemoryInvocationStore()
        transport = httpx.MockTransport(handle)
        async with httpx.AsyncClient(transport=transport) as client:
            caller = HTTPHandlerCaller(invocations, client=client)
            trigger, event, key = await self._prepared_receipt(invocations)
            outcome = await caller(trigger, event)

        assert outcome is None  # acknowledged
        assert seen["url"] == SAFE_TRIGGER_KWARGS["handler_url"]
        assert b'"agent.created"' in seen["body"]  # type: ignore[operator]
        assert seen["headers"]["idempotency-key"] == key

    async def test_a_5xx_is_indeterminate_never_not_applied(self) -> None:
        invocations = InMemoryInvocationStore()
        transport = httpx.MockTransport(lambda _: httpx.Response(500, text="nope"))
        async with httpx.AsyncClient(transport=transport) as client:
            caller = HTTPHandlerCaller(invocations, client=client)
            trigger, event, _ = await self._prepared_receipt(invocations)
            outcome = await caller(trigger, event)
        assert outcome is not None
        assert outcome.disposition is DeliveryDisposition.INDETERMINATE
        assert outcome.reason_code == "http_server_error"

    async def test_a_transport_error_is_indeterminate(self) -> None:
        def handle(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        invocations = InMemoryInvocationStore()
        transport = httpx.MockTransport(handle)
        async with httpx.AsyncClient(transport=transport) as client:
            caller = HTTPHandlerCaller(invocations, client=client)
            trigger, event, _ = await self._prepared_receipt(invocations)
            outcome = await caller(trigger, event)
        assert outcome is not None
        assert outcome.disposition is DeliveryDisposition.INDETERMINATE
        assert outcome.reason_code == "transport_error"

    async def test_refuses_an_absent_receipt_without_sending(self) -> None:
        calls: list[httpx.Request] = []

        def handle(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200)

        invocations = InMemoryInvocationStore()
        transport = httpx.MockTransport(handle)
        async with httpx.AsyncClient(transport=transport) as client:
            caller = HTTPHandlerCaller(invocations, client=client)
            trigger = TriggerDefinition(trigger_id="never-claimed", **SAFE_TRIGGER_KWARGS)
            event = LoggedEvent(id=1, event_type="a.b")
            outcome = await caller(trigger, event)
        assert outcome is not None
        assert outcome.disposition is DeliveryDisposition.NOT_APPLIED
        assert outcome.reason_code == "receipt_absent"
        assert calls == []

    async def test_refuses_a_receipt_not_in_dispatch(self) -> None:
        invocations = InMemoryInvocationStore()
        transport = httpx.MockTransport(lambda _: httpx.Response(200))
        async with httpx.AsyncClient(transport=transport) as client:
            caller = HTTPHandlerCaller(invocations, client=client)
            trigger = TriggerDefinition(trigger_id="t-idle", **SAFE_TRIGGER_KWARGS)
            event = LoggedEvent(id=1, event_type="a.b")
            identity = DeliveryIdentity(
                handler_url=trigger.handler_url,
                request_digest=request_digest_v1(trigger.handler_url, event),
                replay_safety=trigger.effective_replay_safety,
                contract_ref=trigger.contract_ref,
            )
            claimed = await invocations.claim(trigger.trigger_id, event.id, delivery=identity)
            assert claimed is not None  # claimed but begin_dispatch never ran
            outcome = await caller(trigger, event)
        assert outcome is not None
        assert outcome.disposition is DeliveryDisposition.NOT_APPLIED
        assert outcome.reason_code == "receipt_not_in_dispatch"

    async def test_refuses_when_the_event_body_drifted_from_the_frozen_digest(self) -> None:
        invocations = InMemoryInvocationStore()
        trigger, event, _ = await self._prepared_receipt(invocations)
        # The Event body changes after the receipt froze its digest (e.g. an
        # upstream rewrite): the send must refuse rather than re-key.
        mutated = LoggedEvent(
            id=event.id, event_type=event.event_type, payload={"a": 1, "extra": True}
        )
        transport = httpx.MockTransport(lambda _: httpx.Response(200))
        async with httpx.AsyncClient(transport=transport) as client:
            caller = HTTPHandlerCaller(invocations, client=client)
            outcome = await caller(trigger, mutated)
        assert outcome is not None
        assert outcome.disposition is DeliveryDisposition.NOT_APPLIED
        assert outcome.reason_code == "request_digest_mismatch"

    async def test_never_allocates_a_fallback_key(self) -> None:
        """A receipt that somehow lost its key is refused, never re-keyed."""
        invocations = InMemoryInvocationStore()
        trigger, event, _ = await self._prepared_receipt(invocations)
        receipt = await invocations.get(trigger.trigger_id, event.id)
        assert receipt is not None
        keyless = type(receipt)(**{**receipt.__dict__, "delivery_key": None})
        await invocations.save(keyless)
        transport = httpx.MockTransport(lambda _: httpx.Response(200))
        async with httpx.AsyncClient(transport=transport) as client:
            caller = HTTPHandlerCaller(invocations, client=client)
            outcome = await caller(trigger, event)
        assert outcome is not None
        assert outcome.disposition is DeliveryDisposition.NOT_APPLIED
        assert outcome.reason_code == "delivery_key_missing"


class TestClassificationTable:
    """The #1060 §4 classification table, one row at a time."""

    async def test_acknowledged_is_success(self) -> None:
        log, triggers, invocations = (
            InMemoryEventLog(),
            InMemoryTriggerStore(),
            InMemoryInvocationStore(),
        )
        t = TriggerDefinition(trigger_id="t-ack", event_pattern="a.b", **SAFE_TRIGGER_KWARGS)
        await triggers.add(t)
        await log.append("a.b")

        async def caller(tr, ev):
            return HandlerCallOutcome(DeliveryDisposition.ACKNOWLEDGED, "committed")

        cursor = await process_events(log, triggers, invocations, caller)
        receipt = await invocations.get("t-ack", 1)
        assert receipt is not None
        assert receipt.is_successful_delivery
        assert receipt.last_outcome is DeliveryDisposition.ACKNOWLEDGED
        assert cursor == 1

    async def test_proven_not_applied_retries_then_fails_at_the_cap(self) -> None:
        log, triggers, invocations = (
            InMemoryEventLog(),
            InMemoryTriggerStore(),
            InMemoryInvocationStore(),
        )
        t = TriggerDefinition(trigger_id="t-na", event_pattern="a.b", **SAFE_TRIGGER_KWARGS)
        await triggers.add(t)
        await log.append("a.b")

        async def caller(tr, ev):
            return HandlerCallOutcome(DeliveryDisposition.NOT_APPLIED, "pre_send_refusal")

        for expected in (InvocationStatus.RETRYING, InvocationStatus.RETRYING):
            await process_events(log, triggers, invocations, caller)
            receipt = await invocations.get("t-na", 1)
            assert receipt is not None and receipt.status is expected
        await process_events(log, triggers, invocations, caller)
        receipt = await invocations.get("t-na", 1)
        assert receipt is not None and receipt.status is InvocationStatus.FAILED
        assert not receipt.uncertain_prior_dispatch

    async def test_indeterminate_retries_only_under_a_safe_contract(self) -> None:
        # Safe contract: RETRYING while budget remains.
        log, triggers, invocations = (
            InMemoryEventLog(),
            InMemoryTriggerStore(),
            InMemoryInvocationStore(),
        )
        t = TriggerDefinition(trigger_id="t-ind-safe", event_pattern="a.b", **SAFE_TRIGGER_KWARGS)
        await triggers.add(t)
        await log.append("a.b")

        async def indeterminate(tr, ev):
            return HandlerCallOutcome(DeliveryDisposition.INDETERMINATE, "conn_lost")

        await process_events(log, triggers, invocations, indeterminate)
        receipt = await invocations.get("t-ind-safe", 1)
        assert receipt is not None
        assert receipt.status is InvocationStatus.RETRYING
        assert receipt.uncertain_prior_dispatch  # cumulative uncertainty recorded

    async def test_indeterminate_on_an_unproven_recipient_is_unknown_after_one_shot(self) -> None:
        log, triggers, invocations = (
            InMemoryEventLog(),
            InMemoryTriggerStore(),
            InMemoryInvocationStore(),
        )
        t = TriggerDefinition(
            trigger_id="t-ind-unsafe", event_pattern="a.b", handler_url="http://h"
        )
        await triggers.add(t)
        await log.append("a.b")
        calls: list[int] = []

        async def indeterminate(tr, ev):
            calls.append(ev.id)
            return HandlerCallOutcome(DeliveryDisposition.INDETERMINATE, "conn_lost")

        cursor = await process_events(log, triggers, invocations, indeterminate)
        receipt = await invocations.get("t-ind-unsafe", 1)
        assert receipt is not None
        assert receipt.status is InvocationStatus.UNKNOWN
        assert receipt.settled_for_cursor
        assert cursor == 1  # UNKNOWN is cursor-settled and visible
        assert receipt.uncertain_prior_dispatch

        # No automatic replay of UNKNOWN, ever.
        await process_events(log, triggers, invocations, indeterminate, after_id=0)
        assert calls == [1]

    async def test_unproven_recipient_still_gets_its_one_shot_attempt(self) -> None:
        log, triggers, invocations = (
            InMemoryEventLog(),
            InMemoryTriggerStore(),
            InMemoryInvocationStore(),
        )
        t = TriggerDefinition(trigger_id="t-one-shot", event_pattern="a.b", handler_url="http://h")
        await triggers.add(t)
        await log.append("a.b")
        caller = RecordingCaller()

        cursor = await process_events(log, triggers, invocations, caller)
        receipt = await invocations.get("t-one-shot", 1)
        assert receipt is not None
        assert receipt.is_successful_delivery
        assert cursor == 1
        assert caller.calls == [("t-one-shot", 1)]

    async def test_an_arbitrary_exception_is_indeterminate_evidence(self) -> None:
        log, triggers, invocations = (
            InMemoryEventLog(),
            InMemoryTriggerStore(),
            InMemoryInvocationStore(),
        )
        t = TriggerDefinition(trigger_id="t-exc", event_pattern="a.b", handler_url="http://h")
        await triggers.add(t)
        await log.append("a.b")

        async def exploding(tr, ev):
            raise RuntimeError("bug in the handler client")

        await process_events(log, triggers, invocations, exploding)
        receipt = await invocations.get("t-exc", 1)
        assert receipt is not None
        assert receipt.status is InvocationStatus.UNKNOWN
        assert receipt.last_error_code == "handler_exception"

    async def test_prior_indeterminate_plus_current_not_applied_stays_unknown_on_exhaustion(
        self,
    ) -> None:
        """The §6 oracle: an earlier possibly-applied call is never erased by a
        later proven not-applied one once the budget is gone."""
        log, triggers, invocations = (
            InMemoryEventLog(),
            InMemoryTriggerStore(),
            InMemoryInvocationStore(),
        )
        t = TriggerDefinition(trigger_id="t-unc", event_pattern="a.b", **SAFE_TRIGGER_KWARGS)
        await triggers.add(t)
        await log.append("a.b")
        outcomes = iter(
            [
                HandlerCallOutcome(DeliveryDisposition.INDETERMINATE, "conn_lost"),
                HandlerCallOutcome(DeliveryDisposition.NOT_APPLIED, "proven_absent"),
            ]
        )

        async def caller(tr, ev):
            return next(outcomes)

        await process_events(log, triggers, invocations, caller)  # attempt 1: indeterminate
        receipt = await invocations.get("t-unc", 1)
        assert receipt is not None and receipt.status is InvocationStatus.RETRYING
        await process_events(log, triggers, invocations, caller)  # attempt 2: not applied
        receipt = await invocations.get("t-unc", 1)
        assert receipt is not None and receipt.status is InvocationStatus.RETRYING
        assert receipt.uncertain_prior_dispatch

        # Attempt 3 also proven absent: budget exhausted with inherited
        # uncertainty -> UNKNOWN, never FAILED.
        async def not_applied(tr, ev):
            return HandlerCallOutcome(DeliveryDisposition.NOT_APPLIED, "proven_absent")

        cursor = await process_events(log, triggers, invocations, not_applied)
        receipt = await invocations.get("t-unc", 1)
        assert receipt is not None
        assert receipt.status is InvocationStatus.UNKNOWN
        assert receipt.uncertain_prior_dispatch
        assert receipt.last_error_code == "proven_absent"
        assert cursor == 1

    async def test_changed_target_refuses_to_send_and_settles_visibly(self) -> None:
        log, triggers, invocations = (
            InMemoryEventLog(),
            InMemoryTriggerStore(),
            InMemoryInvocationStore(),
        )
        t = TriggerDefinition(trigger_id="t-move", event_pattern="a.b", **SAFE_TRIGGER_KWARGS)
        await triggers.add(t)
        await log.append("a.b")
        caller = RecordingCaller()

        # First tick holds the receipt in RETRYING with its frozen identity.
        caller.fail_keys.add(("t-move", 1))
        await process_events(log, triggers, invocations, caller)
        receipt = await invocations.get("t-move", 1)
        assert receipt is not None and receipt.status is InvocationStatus.RETRYING

        # The operator repoints the handler: the frozen receipt disagrees.
        moved = TriggerDefinition(
            trigger_id="t-move",
            event_pattern="a.b",
            handler_url="http://handlers.local/other",
            replay_safety=ReplaySafety.IDEMPOTENT,
            contract_ref="contract-v1",
        )
        await triggers.add(moved)
        cursor = await process_events(log, triggers, invocations, caller, after_id=0)

        receipt = await invocations.get("t-move", 1)
        assert receipt is not None
        assert receipt.status is InvocationStatus.FAILED
        assert receipt.last_error_code == "delivery_identity_changed"
        assert cursor == 1  # settled for cursor: refused, visible, not replayed
        assert caller.calls == [("t-move", 1)]  # the repointed URL was never called

    async def test_changed_target_with_prior_uncertainty_is_unknown_not_failed(self) -> None:
        log, triggers, invocations = (
            InMemoryEventLog(),
            InMemoryTriggerStore(),
            InMemoryInvocationStore(),
        )
        t = TriggerDefinition(trigger_id="t-move2", event_pattern="a.b", **SAFE_TRIGGER_KWARGS)
        await triggers.add(t)
        await log.append("a.b")

        async def indeterminate(tr, ev):
            return HandlerCallOutcome(DeliveryDisposition.INDETERMINATE, "conn_lost")

        await process_events(log, triggers, invocations, indeterminate)
        receipt = await invocations.get("t-move2", 1)
        assert receipt is not None and receipt.uncertain_prior_dispatch

        moved = TriggerDefinition(
            trigger_id="t-move2", event_pattern="a.b", handler_url="http://other", contract_ref="c"
        )
        await triggers.add(moved)
        caller = RecordingCaller()
        cursor = await process_events(log, triggers, invocations, caller, after_id=0)
        receipt = await invocations.get("t-move2", 1)
        assert receipt is not None
        assert receipt.status is InvocationStatus.UNKNOWN
        assert cursor == 1

    async def test_missing_handler_url_is_a_pre_send_refusal(self) -> None:
        log, triggers, invocations = (
            InMemoryEventLog(),
            InMemoryTriggerStore(),
            InMemoryInvocationStore(),
        )
        t = TriggerDefinition(
            trigger_id="t-nourl",
            event_pattern="a.b",
            replay_safety=ReplaySafety.IDEMPOTENT,
            contract_ref="c",
        )
        await triggers.add(t)
        await log.append("a.b")
        caller = RecordingCaller()

        cursor = await process_events(log, triggers, invocations, caller)
        receipt = await invocations.get("t-nourl", 1)
        assert receipt is not None
        assert receipt.status is InvocationStatus.FAILED
        assert receipt.last_error_code == "handler_url_missing"
        assert caller.calls == []
        assert cursor == 1

    async def test_idempotent_declaration_without_a_contract_ref_acts_unproven(self) -> None:
        log, triggers, invocations = (
            InMemoryEventLog(),
            InMemoryTriggerStore(),
            InMemoryInvocationStore(),
        )
        t = TriggerDefinition(
            trigger_id="t-noref",
            event_pattern="a.b",
            handler_url="http://h",
            replay_safety=ReplaySafety.IDEMPOTENT,
            contract_ref="",  # invalid enrollment
        )
        await triggers.add(t)
        await log.append("a.b")

        async def indeterminate(tr, ev):
            return HandlerCallOutcome(DeliveryDisposition.INDETERMINATE, "conn_lost")

        await process_events(log, triggers, invocations, indeterminate)
        receipt = await invocations.get("t-noref", 1)
        assert receipt is not None
        assert receipt.status is InvocationStatus.UNKNOWN  # not auto-retried
        assert receipt.replay_safety is ReplaySafety.UNPROVEN


class TestCrashPhases:
    """§6 fault injection: kill the worker at every boundary, prove the
    post-effect window cannot double-apply under the supported contract."""

    @staticmethod
    def _stack():
        log = InMemoryEventLog()
        trig_store = InMemoryTriggerStore()
        invocations = InMemoryInvocationStore()
        trigger = TriggerDefinition(
            trigger_id="t-crash",
            event_pattern="task.created",
            handler_url="http://receiver.local/handler",
            replay_safety=ReplaySafety.IDEMPOTENT,
            contract_ref="contract-v1",
        )
        return log, trig_store, invocations, trigger

    @staticmethod
    def _delivery(trigger: TriggerDefinition, event: LoggedEvent) -> DeliveryIdentity:
        return DeliveryIdentity(
            handler_url=trigger.handler_url,
            request_digest=request_digest_v1(trigger.handler_url, event),
            replay_safety=trigger.effective_replay_safety,
            contract_ref=trigger.contract_ref,
        )

    async def test_death_before_begin_leaves_no_uncertainty(self) -> None:
        """Claimed, then the worker dies before consuming a send: the takeover
        finds no dispatch marker, so nothing possibly applied."""
        log, trig_store, invocations, trigger = self._stack()
        await trig_store.add(trigger)
        event = await log.append("task.created")
        delivery = self._delivery(trigger, event)
        # Worker A claims and dies (lease lapses).
        await invocations.claim(trigger.trigger_id, event.id, delivery=delivery, lease_seconds=-1.0)

        receiver = FakeReceiver()
        cursor = await process_events(
            log, trig_store, invocations, self._receiver_caller(receiver, invocations)
        )
        receipt = await invocations.get(trigger.trigger_id, event.id)
        assert receipt is not None
        assert receipt.is_successful_delivery
        assert not receipt.uncertain_prior_dispatch
        assert receiver.logical_effects == 1
        assert cursor == event.id

    async def test_death_after_begin_before_http_folds_uncertainty(self) -> None:
        """begin_dispatch consumed the send and set the marker, then death:
        takeover must fold the marker into cumulative uncertainty."""
        log, trig_store, invocations, trigger = self._stack()
        await trig_store.add(trigger)
        event = await log.append("task.created")
        delivery = self._delivery(trigger, event)
        claimed = await invocations.claim(trigger.trigger_id, event.id, delivery=delivery)
        assert claimed is not None
        begun = await invocations.begin_dispatch(
            trigger.trigger_id,
            event.id,
            claim_token=claimed.claim_token,
            expected_revision=claimed.revision,
            delivery=delivery,
        )
        assert begun is not None and begun.attempts == 1

        # The lease lapses (hard death); the next claim takes over and folds
        # the in-flight marker into cumulative uncertainty.
        raw = await invocations.get(trigger.trigger_id, event.id)
        assert raw is not None
        expired = raw.__class__(**{**raw.__dict__, "lease_expires_at": 0.0})
        await invocations.save(expired)
        reclaimed = await invocations.claim(trigger.trigger_id, event.id, delivery=delivery)
        assert reclaimed is not None
        assert reclaimed.uncertain_prior_dispatch
        assert reclaimed.dispatch_started_at is None
        # The send budget was consumed by the dead worker and is not refunded.
        assert reclaimed.attempts == 1

    async def test_death_after_begin_before_http_redelivers_once_under_safe_contract(self) -> None:
        log, trig_store, invocations, trigger = self._stack()
        await trig_store.add(trigger)
        event = await log.append("task.created")
        delivery = self._delivery(trigger, event)
        claimed = await invocations.claim(trigger.trigger_id, event.id, delivery=delivery)
        assert claimed is not None
        begun = await invocations.begin_dispatch(
            trigger.trigger_id,
            event.id,
            claim_token=claimed.claim_token,
            expected_revision=claimed.revision,
            delivery=delivery,
        )
        assert begun is not None
        # Hard death: the lease lapses with the marker in flight.
        raw = await invocations.get(trigger.trigger_id, event.id)
        assert raw is not None
        expired = raw.__class__(**{**raw.__dict__, "lease_expires_at": 0.0})
        await invocations.save(expired)

        receiver = FakeReceiver()
        cursor = await process_events(
            log, trig_store, invocations, self._receiver_caller(receiver, invocations)
        )
        receipt = await invocations.get(trigger.trigger_id, event.id)
        assert receipt is not None
        assert receipt.is_successful_delivery
        assert receipt.uncertain_prior_dispatch  # the dead attempt stays uncertain
        assert receiver.logical_effects == 1  # the receiver's dedupe held
        assert len(receiver.received) == 1
        assert cursor == event.id

    async def test_remote_commit_before_success_save_is_one_logical_effect_on_replay(self):
        """The original crash window: the receiver commits, the response is
        lost, and the worker dies before settling. Redelivery under the same
        persisted key commits exactly one logical effect."""
        log, trig_store, invocations, trigger = self._stack()
        await trig_store.add(trigger)
        event = await log.append("task.created")
        receiver = FakeReceiver()
        deliveries: list[str] = []

        async def crash_after_commit(tr, ev):
            # The receiver commits the effect, then the worker dies before
            # recording anything: the response never arrives.
            key = (await invocations.get(tr.trigger_id, ev.id)).delivery_key
            assert key is not None
            deliveries.append(key)
            await receiver.receive(key, "digest")
            raise RuntimeError("worker died after remote commit")

        with pytest.raises(RuntimeError, match="worker died"):
            # The classification settles the receipt, but a *hard* death is
            # simulated by the store refusing the settle: patch it out by
            # crashing the settle itself.
            crashing_store = _CrashBeforeSettleStore(invocations)
            await process_events(log, trig_store, crashing_store, crash_after_commit)

        # A restarted worker replays from cursor 0 under the same key.
        receipt = await invocations.get(trigger.trigger_id, event.id)
        assert receipt is not None and receipt.dispatch_started_at is not None

        async def receiver_caller(tr, ev):
            key = (await invocations.get(tr.trigger_id, ev.id)).delivery_key
            assert key is not None
            deliveries.append(key)
            await receiver.receive(key, "digest")
            return None

        # Simulate lease lapse so the replay can take over.
        raw = await invocations.get(trigger.trigger_id, event.id)
        expired = raw.__class__(**{**raw.__dict__, "lease_expires_at": 0.0})
        await invocations.save(expired)
        cursor = await process_events(log, trig_store, invocations, receiver_caller, after_id=0)

        assert cursor == event.id
        assert len(deliveries) == 2  # the POST physically repeated...
        assert receiver.logical_effects == 1  # ...but committed one logical effect
        saved = await invocations.get(trigger.trigger_id, event.id)
        assert saved is not None and saved.is_successful_delivery

    async def test_after_success_before_cursor_save_replay_does_not_resend(self) -> None:
        log, trig_store, invocations, trigger = self._stack()
        await trig_store.add(trigger)
        event = await log.append("task.created")
        receiver = FakeReceiver()
        cursor = await process_events(
            log, trig_store, invocations, self._receiver_caller(receiver, invocations)
        )
        assert cursor == event.id

        # The cursor save is lost: the next tick replays from 0 and must not
        # re-send — the settled receipt refuses the claim.
        cursor2 = await process_events(
            log,
            trig_store,
            invocations,
            self._receiver_caller(receiver, invocations),
            after_id=0,
        )
        assert cursor2 == event.id
        assert len(receiver.received) == 1
        assert receiver.logical_effects == 1

    @staticmethod
    def _receiver_caller(receiver: FakeReceiver, invocations: InMemoryInvocationStore):
        async def caller(trigger: TriggerDefinition, event: LoggedEvent) -> None:
            receipt = await invocations.get(trigger.trigger_id, event.id)
            assert receipt is not None
            assert receipt.delivery_key is not None
            await receiver.receive(receipt.delivery_key, receipt.request_digest)
            return None

        return caller

    async def test_unknown_receipts_stay_inspectable_while_later_events_advance(self) -> None:
        log, trig_store, invocations, trigger = self._stack()
        await trig_store.add(trigger)
        await log.append("task.created")

        async def indeterminate(tr, ev):
            return HandlerCallOutcome(DeliveryDisposition.INDETERMINATE, "conn_lost")

        # Event 1 lands UNKNOWN (budget consumed across three uncertain sends).
        for _ in range(MAX_ATTEMPTS):
            await process_events(log, trig_store, invocations, indeterminate, after_id=0)
        first = await invocations.get(trigger.trigger_id, 1)
        assert first is not None and first.status is InvocationStatus.UNKNOWN

        # Later events keep flowing past the visible UNKNOWN receipt.
        await log.append("task.created")
        cursor = await process_events(log, trig_store, invocations, RecordingCaller(), after_id=0)
        assert cursor == 2
        still_unknown = await invocations.get(trigger.trigger_id, 1)
        assert still_unknown is not None
        assert still_unknown.status is InvocationStatus.UNKNOWN
        assert still_unknown.last_error_code == "conn_lost"


class _CrashBeforeSettleStore:
    """Proxy that simulates hard death at the settle boundary (#1060 §6).

    Delegates every read to the real store but dies on the first settle, so
    the receipt keeps its in-flight dispatch marker exactly as a process
    killed between the remote commit and the local SUCCESS write would.
    """

    def __init__(self, inner: InMemoryInvocationStore) -> None:
        self._inner = inner
        self.crash_armed = True

    def __getattr__(self, name: str):  # pragma: no cover - simple delegation
        return getattr(self._inner, name)

    async def settle(self, *args, **kwargs):
        if self.crash_armed:
            self.crash_armed = False
            raise RuntimeError("worker died before SUCCESS persistence")
        return await self._inner.settle(*args, **kwargs)


class YieldingCaller(RecordingCaller):
    """A handler that actually suspends, so the workers genuinely interleave.

    `RecordingCaller.__call__` is `async def` with no `await` in it, so it never
    yields — and `asyncio.gather` over coroutines that never yield runs them one
    after another to completion. Suspending inside the handler is what puts a
    second worker at `claim` while the first is mid-dispatch.
    """

    async def __call__(self, trigger: TriggerDefinition, event: LoggedEvent) -> None:
        self.calls.append((trigger.trigger_id, event.id))
        for _ in range(4):
            await asyncio.sleep(0)


class TestConcurrentWorkersDispatchOnce:
    """Two workers, one event, one handler call (#181, retained)."""

    @staticmethod
    async def _one_event_two_workers(caller, workers: int = 8):
        event_log = InMemoryEventLog()
        trigger_store = InMemoryTriggerStore()
        invocations = InMemoryInvocationStore()
        await trigger_store.add(
            TriggerDefinition(
                trigger_id="t1", name="t1", event_pattern="task.created", **SAFE_TRIGGER_KWARGS
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
        caller = YieldingCaller()
        invocations = await self._one_event_two_workers(caller)
        invocation = await invocations.get("t1", 1)
        assert invocation is not None
        assert invocation.is_successful_delivery

    async def test_a_worker_that_skips_does_not_advance_past_an_unsettled_event(self):
        event_log = InMemoryEventLog()
        trigger_store = InMemoryTriggerStore()
        invocations = InMemoryInvocationStore()
        trigger = TriggerDefinition(
            trigger_id="t1", name="t1", event_pattern="task.created", **SAFE_TRIGGER_KWARGS
        )
        await trigger_store.add(trigger)
        event = await event_log.append("task.created")

        # Another worker holds a live claim and has not finished.
        held = await invocations.claim(
            trigger.trigger_id,
            event.id,
            delivery=DeliveryIdentity("http://handlers.local/x", "v1:digest"),
        )
        assert held is not None

        caller = RecordingCaller()
        cursor = await process_events(event_log, trigger_store, invocations, caller)

        assert caller.calls == []
        assert cursor == 0, "the cursor advanced past an event still being handled"


class HidingLog:
    """An event log whose reads skip chosen ids: PostgreSQL between allocation
    and commit, where a `BIGSERIAL` id exists but its row is not yet visible."""

    def __init__(self, inner: InMemoryEventLog, hidden: set[int]) -> None:
        self._inner = inner
        self.hidden = hidden

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)

    async def query(self, **kwargs: object) -> list[LoggedEvent]:
        return [e for e in await self._inner.query(**kwargs) if e.id not in self.hidden]  # type: ignore[arg-type]


class TestTheBatchReportsWhatTheLogSkipped:
    """#1163 review: a durable cursor must be able to see an id the log has
    handed out but not committed, or it persists past the event for good."""

    async def test_contiguous_ids_report_no_holes(
        self, stores: tuple[InMemoryEventLog, InMemoryTriggerStore, InMemoryInvocationStore]
    ) -> None:
        log, triggers, invocations = stores
        await triggers.add(
            TriggerDefinition(name="agents", event_pattern="agent.*", **SAFE_TRIGGER_KWARGS)
        )
        await log.append("agent.created")
        await log.append("agent.created")

        batch = await process_events_batch(log, triggers, invocations, RecordingCaller())

        assert batch.cursor == 2
        assert batch.holes == ()

    async def test_every_gap_is_reported_by_its_first_missing_id(
        self, stores: tuple[InMemoryEventLog, InMemoryTriggerStore, InMemoryInvocationStore]
    ) -> None:
        inner, triggers, invocations = stores
        await triggers.add(
            TriggerDefinition(name="agents", event_pattern="agent.*", **SAFE_TRIGGER_KWARGS)
        )
        for _ in range(6):
            await inner.append("agent.created")
        log = HidingLog(inner, hidden={2, 4, 5})
        caller = RecordingCaller()

        batch = await process_events_batch(log, triggers, invocations, caller)  # type: ignore[arg-type]

        assert [event_id for _, event_id in caller.calls] == [1, 3, 6]
        assert batch.cursor == 6
        assert batch.holes == (2, 4)

    async def test_a_hole_at_the_very_start_is_reported_too(
        self, stores: tuple[InMemoryEventLog, InMemoryTriggerStore, InMemoryInvocationStore]
    ) -> None:
        inner, triggers, invocations = stores
        await triggers.add(
            TriggerDefinition(name="agents", event_pattern="agent.*", **SAFE_TRIGGER_KWARGS)
        )
        await inner.append("agent.created")
        await inner.append("agent.created")
        log = HidingLog(inner, hidden={1})

        batch = await process_events_batch(log, triggers, invocations, RecordingCaller())  # type: ignore[arg-type]

        assert batch.cursor == 2
        assert batch.holes == (1,)

    async def test_holes_are_only_counted_below_the_settled_cursor(
        self, stores: tuple[InMemoryEventLog, InMemoryTriggerStore, InMemoryInvocationStore]
    ) -> None:
        inner, triggers, invocations = stores
        t = TriggerDefinition(name="agents", event_pattern="agent.*", **SAFE_TRIGGER_KWARGS)
        await triggers.add(t)
        for _ in range(4):
            await inner.append("agent.created")
        log = HidingLog(inner, hidden={3})
        caller = RecordingCaller()
        caller.fail_times[(t.trigger_id, 2)] = 1

        batch = await process_events_batch(log, triggers, invocations, caller)  # type: ignore[arg-type]

        assert batch.cursor == 1
        assert batch.holes == ()

    async def test_process_events_returns_the_batch_cursor(
        self, stores: tuple[InMemoryEventLog, InMemoryTriggerStore, InMemoryInvocationStore]
    ) -> None:
        inner, triggers, invocations = stores
        await triggers.add(
            TriggerDefinition(name="agents", event_pattern="agent.*", **SAFE_TRIGGER_KWARGS)
        )
        for _ in range(3):
            await inner.append("agent.created")
        log = HidingLog(inner, hidden={2})

        cursor = await process_events(log, triggers, invocations, RecordingCaller())  # type: ignore[arg-type]

        assert cursor == 3


class TestAttemptBudgetCannotBeEvaded:
    """Kill loops: repeated death/reclaim never buys a fourth send."""

    async def test_repeated_death_and_reclaim_stops_at_the_cap(self) -> None:
        log = InMemoryEventLog()
        trig_store = InMemoryTriggerStore()
        invocations = InMemoryInvocationStore()
        trigger = TriggerDefinition(trigger_id="t-kill", event_pattern="a.b", **SAFE_TRIGGER_KWARGS)
        await trig_store.add(trigger)
        event = await log.append("a.b")
        delivery = DeliveryIdentity(
            handler_url=trigger.handler_url,
            request_digest=request_digest_v1(trigger.handler_url, event),
            replay_safety=trigger.effective_replay_safety,
            contract_ref=trigger.contract_ref,
        )
        # Worker dies after begin each round: three send permissions total.
        for expected_attempts in (1, 2, 3):
            claimed = await invocations.claim(trigger.trigger_id, event.id, delivery=delivery)
            assert claimed is not None
            begun = await invocations.begin_dispatch(
                trigger.trigger_id,
                event.id,
                claim_token=claimed.claim_token,
                expected_revision=claimed.revision,
                delivery=delivery,
            )
            assert begun is not None
            assert begun.attempts == expected_attempts
            # Hard death: the lease lapses with the marker in flight.
            raw = await invocations.get(trigger.trigger_id, event.id)
            assert raw is not None
            expired = raw.__class__(**{**raw.__dict__, "lease_expires_at": 0.0})
            await invocations.save(expired)

        # A fourth begin is refused even after another takeover.
        fourth_claim = await invocations.claim(
            trigger.trigger_id, event.id, delivery=delivery, lease_seconds=-1.0
        )
        assert fourth_claim is not None  # claim may settle an exhausted receipt...
        with pytest.raises(DeliveryAttemptLimitReached):
            await invocations.begin_dispatch(
                trigger.trigger_id,
                event.id,
                claim_token=fourth_claim.claim_token,
                expected_revision=fourth_claim.revision,
                delivery=delivery,
            )
