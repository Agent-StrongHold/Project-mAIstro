"""Event processing loop: durable log -> triggers -> idempotent handler calls.

Pure async function (`process_events`) with injected stores and handler
caller, designed to be ticked by the reactor loop (SPEC-013). All delivery
semantics from ADR-086 live here:

- at-least-once delivery: the cursor only advances past an event once every
  matching trigger's receipt is settled-for-cursor (success/failed/unknown),
  so a crash replays it;
- dispatch deduplication: (trigger_id, event_id) receipts, claim leases and
  revision fencing ensure one active MAIstro dispatcher — they do not prove an
  external effect was applied;
- external-effect idempotency: automatic redelivery after an uncertain send
  happens only for triggers whose recipient is enrolled as idempotent or
  read_only through the authorized trigger store (#1060 §2);
- truthful ambiguity: a transport loss, 5xx or arbitrary exception after a
  possibly-committed remote effect is indeterminate evidence. It becomes
  RETRYING only under a currently valid safe contract, and otherwise UNKNOWN —
  visible, cursor-settled, and never automatically replayed;
- retry: a proven not-applied call is retried up to ``MAX_ATTEMPTS`` total
  physical sends, then marked failed with a ``handler.failed`` event appended.

The old `_dispatch` ignored caller return values and retried every exception;
the typed outcome classifier, the receipt-reading HTTP caller and the
Container wiring activate together (#1060 §4).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import httpx

from maistro.events.envelope import EventEnvelope
from maistro.events.invocations import (
    MAX_ATTEMPTS,
    DeliveryAlreadyStarted,
    DeliveryAttemptLimitReached,
    DeliveryDisposition,
    DeliveryIdentity,
    DeliveryIdentityMismatch,
    HandlerCallOutcome,
    InvocationStatus,
    ReplaySafety,
    identity_matches,
    request_digest_v1,
    validated_outcome,
)
from maistro.http import shared_client
from maistro.sqlite_schema import execute_schema_script

if TYPE_CHECKING:
    import aiosqlite

    from maistro.events.durable_log import EventLogStore, LoggedEvent
    from maistro.events.invocations import HandlerInvocation, InvocationStore
    from maistro.events.trigger_store import TriggerDefinition, TriggerStore

logger = logging.getLogger("maistro.events.processing")

HANDLER_FAILED_EVENT = "handler.failed"

_SAFE_REPLAY_SAFETIES = (ReplaySafety.IDEMPOTENT, ReplaySafety.READ_ONLY)

#: Bound for the shielded settlement attempt when the dispatch task itself is
#: cancelled: settlement must not hang forever, but re-raising the
#: cancellation must not skip the attempt entirely (#1060 §4).
_CANCELLED_SETTLE_TIMEOUT_S = 2.0


@runtime_checkable
class HandlerCaller(Protocol):
    """Injected async callable that delivers an event to a trigger's handler.

    Returns ``None`` (the established injected-caller acknowledgment) or a
    :class:`HandlerCallOutcome` describing the current call's evidence. A
    ``NOT_APPLIED`` outcome is a trusted caller's explicit proof that nothing
    was applied; a generic HTTP status, transport error or arbitrary exception
    never proves it. Raising is permitted and classified indeterminate.
    """

    async def __call__(
        self, trigger: TriggerDefinition, event: LoggedEvent
    ) -> HandlerCallOutcome | None: ...


class HTTPHandlerCaller:
    """POST an event to the handler its prepared receipt names, keyed by it.

    Reads the receipt the Container-selected invocation store prepared for
    ``(trigger, event)``, refuses absent/mismatched/not-in-dispatch receipts,
    snapshots target and body before any await, validates the request digest,
    and sends the receipt's persisted ``delivery_key`` as the
    ``Idempotency-Key``. It never allocates keys, claims ownership, writes
    receipts or creates a private store: the key's recipient-side dedupe is
    what makes redelivery safe, and this caller only ever relays it.

    The reread is a refusal gate, not a fence: a sender that already passed
    ``begin_dispatch`` and stalled is not physically stopped by it — the
    receipt's revision fencing and the recipient's dedupe cover that window.
    """

    def __init__(
        self,
        invocation_store: InvocationStore,
        *,
        timeout: float = 5.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._store = invocation_store
        self._timeout = timeout
        self._client = client

    async def __call__(
        self, trigger: TriggerDefinition, event: LoggedEvent
    ) -> HandlerCallOutcome | None:
        receipt = await self._store.get(trigger.trigger_id, event.id)
        if receipt is None:
            return HandlerCallOutcome(
                DeliveryDisposition.NOT_APPLIED,
                "receipt_absent",
                f"no prepared receipt for ({trigger.trigger_id}, {event.id})",
            )
        if receipt.dispatch_started_at is None:
            return HandlerCallOutcome(
                DeliveryDisposition.NOT_APPLIED,
                "receipt_not_in_dispatch",
                "receipt has no in-flight dispatch marker for this claim",
            )
        if receipt.delivery_key is None:
            return HandlerCallOutcome(
                DeliveryDisposition.NOT_APPLIED,
                "delivery_key_missing",
                "receipt was never keyed; no fallback key is ever allocated",
            )
        if receipt.handler_url != trigger.handler_url:
            return HandlerCallOutcome(
                DeliveryDisposition.NOT_APPLIED,
                "handler_url_mismatch",
                "receipt destination differs from the trigger's current handler_url",
            )
        # Snapshot the exact target and body before the first await, so a
        # concurrent trigger edit cannot change what this send contains.
        url = receipt.handler_url
        body = event.to_dict()
        if request_digest_v1(url, event) != receipt.request_digest:
            return HandlerCallOutcome(
                DeliveryDisposition.NOT_APPLIED,
                "request_digest_mismatch",
                "event body no longer matches the receipt's frozen digest",
            )
        headers = {
            "Idempotency-Key": receipt.delivery_key,
            "X-MAIstro-Trigger-Id": trigger.trigger_id,
            "X-MAIstro-Event-Id": str(event.id),
        }
        try:
            if self._client is not None:
                response = await self._client.post(
                    url, json=body, headers=headers, timeout=self._timeout
                )
            else:
                async with shared_client(timeout=self._timeout) as client:
                    response = await client.post(url, json=body, headers=headers)
        except httpx.HTTPError as exc:
            # The remote may have committed before the connection was lost:
            # a transport error is never proof of absence.
            return HandlerCallOutcome(
                DeliveryDisposition.INDETERMINATE, "transport_error", str(exc)
            )
        if response.status_code >= 500:
            return HandlerCallOutcome(
                DeliveryDisposition.INDETERMINATE,
                "http_server_error",
                f"{response.status_code}: {response.text}"[:2048],
            )
        if response.status_code >= 400:
            # A status line alone proves nothing about the remote commit.
            return HandlerCallOutcome(
                DeliveryDisposition.INDETERMINATE,
                "http_error_status",
                f"{response.status_code}: {response.text}"[:2048],
            )
        return None


def _classify_outcome(
    *, attempts_used: int, prior_uncertainty: bool, safe_contract: bool, outcome: HandlerCallOutcome
) -> InvocationStatus:
    """Map current-call evidence + inherited uncertainty to a target status.

    The reviewed classification table (#1060 §4): acknowledged is SUCCESS; a
    proven not-applied call retries while budget remains (FAILED when
    exhausted, or immediately when the refusal is terminal); indeterminate or
    inherited uncertainty retries only under a currently valid matching
    idempotent/read_only contract, and is otherwise UNKNOWN.
    """
    budget_remains = attempts_used < MAX_ATTEMPTS
    if outcome.disposition is DeliveryDisposition.ACKNOWLEDGED:
        return InvocationStatus.SUCCESS
    if outcome.disposition is DeliveryDisposition.NOT_APPLIED:
        if prior_uncertainty:
            if safe_contract and budget_remains:
                return InvocationStatus.RETRYING
            return InvocationStatus.UNKNOWN
        return InvocationStatus.RETRYING if budget_remains else InvocationStatus.FAILED
    # Indeterminate current call.
    if safe_contract and budget_remains:
        return InvocationStatus.RETRYING
    return InvocationStatus.UNKNOWN


async def _settle_and_report(
    invocation_store: InvocationStore,
    trigger_id: str,
    event_id: int,
    *,
    claim_token: str,
    expected_revision: int,
    status: InvocationStatus,
    outcome: HandlerCallOutcome,
) -> bool:
    """Settle under fencing; report the reread truth if the claim was lost."""
    settled = await invocation_store.settle(
        trigger_id,
        event_id,
        claim_token=claim_token,
        expected_revision=expected_revision,
        status=status,
        outcome=outcome,
    )
    if settled is None:
        # An unverified stale settlement never advances the cursor by itself.
        current = await invocation_store.get(trigger_id, event_id)
        return current is not None and current.settled_for_cursor
    if settled.is_successful_delivery:
        logger.info(
            "Delivered event %d for trigger %s under delivery key %s",
            event_id,
            trigger_id,
            settled.delivery_key,
        )
    return settled.settled_for_cursor


def _unsendable_target_reason(handler_url: str) -> tuple[str, str] | None:
    """``(reason_code, detail)`` when the configured target can never be sent.

    A missing or syntactically malformed URL must be refused before
    ``begin_dispatch``: httpx raises ``InvalidURL`` outside its
    ``HTTPError`` hierarchy, so left to the caller a malformed target would
    surface as an indeterminate possibly-committed call and the trigger
    would settle UNKNOWN after consuming every attempt for a call that
    could never start.
    """
    if not handler_url:
        return "handler_url_missing", ""
    try:
        httpx.URL(handler_url)
    except httpx.InvalidURL as exc:
        return "handler_url_malformed", str(exc)
    return None


async def _settle_refusal(
    invocation_store: InvocationStore,
    claimed: HandlerInvocation,
    *,
    reason_code: str,
    detail: str = "",
) -> bool:
    """Visibly settle a pre-send refusal without any physical call.

    Local identity/config/refusal before this claim sent is FAILED only when
    no historical possibly-applied call exists; with inherited uncertainty it
    is UNKNOWN instead — never a retry.
    """
    status = (
        InvocationStatus.UNKNOWN if claimed.uncertain_prior_dispatch else InvocationStatus.FAILED
    )
    return await _settle_and_report(
        invocation_store,
        claimed.trigger_id,
        claimed.event_id,
        claim_token=claimed.claim_token,
        expected_revision=claimed.revision,
        status=status,
        outcome=HandlerCallOutcome(DeliveryDisposition.NOT_APPLIED, reason_code, detail),
    )


async def _settle_attempt_limit(
    event_log: EventLogStore,
    invocation_store: InvocationStore,
    trigger: TriggerDefinition,
    event: LoggedEvent,
    claimed: HandlerInvocation,
) -> bool:
    """Settle an exhausted receipt without another physical call.

    The cap is a pre-send fact about this claim, never proof an earlier send
    was absent: with inherited uncertainty the truthful state is UNKNOWN.
    """
    if claimed.uncertain_prior_dispatch:
        return await _settle_and_report(
            invocation_store,
            claimed.trigger_id,
            claimed.event_id,
            claim_token=claimed.claim_token,
            expected_revision=claimed.revision,
            status=InvocationStatus.UNKNOWN,
            outcome=HandlerCallOutcome(
                DeliveryDisposition.INDETERMINATE, "attempt_limit_with_uncertainty"
            ),
        )
    await _append_handler_failed(event_log, trigger, event, "attempt limit reached")
    return await _settle_and_report(
        invocation_store,
        claimed.trigger_id,
        claimed.event_id,
        claim_token=claimed.claim_token,
        expected_revision=claimed.revision,
        status=InvocationStatus.FAILED,
        outcome=HandlerCallOutcome(DeliveryDisposition.NOT_APPLIED, "attempt_limit_reached"),
    )


async def _reread_settled(
    invocation_store: InvocationStore, trigger_id: str, event_id: int
) -> bool:
    """Reread after losing a claim/CAS race without sending.

    The caller never sends on a lost race, and never reports the event
    settled unless the reread actually says so: only a receipt that is
    settled for cursor (success/failed/unknown) may hold the cursor.
    """
    current = await invocation_store.get(trigger_id, event_id)
    return current is not None and current.settled_for_cursor


async def _settle_pre_send_refusal(
    invocation_store: InvocationStore,
    claimed: HandlerInvocation,
    trigger: TriggerDefinition,
    event: LoggedEvent,
    delivery: DeliveryIdentity,
) -> bool | None:
    """Settle without HTTP when this claim cannot authorize a send.

    Three facts stop a dispatch before any socket is opened: the frozen
    receipt disagrees with the current authorized declaration; the target is
    structurally unsendable; or an earlier send may have applied while the
    recipient cannot deduplicate. Each settles visibly and reports. Returns
    the cursor settlement, or None when the send may proceed.
    """
    if not identity_matches(claimed, delivery):
        # Changed target/body/contract: the frozen receipt disagrees with the
        # current authorized declaration. Refuse visibly, without HTTP.
        return await _settle_refusal(
            invocation_store, claimed, reason_code="delivery_identity_changed"
        )

    unsendable = _unsendable_target_reason(trigger.handler_url)
    if unsendable is not None:
        reason_code, detail = unsendable
        return await _settle_refusal(
            invocation_store, claimed, reason_code=reason_code, detail=detail
        )

    if claimed.uncertain_prior_dispatch and delivery.replay_safety not in _SAFE_REPLAY_SAFETIES:
        # A possibly-applied earlier send + a recipient that cannot dedupe:
        # automatic redelivery is exactly what cannot be allowed.
        return await _settle_and_report(
            invocation_store,
            claimed.trigger_id,
            claimed.event_id,
            claim_token=claimed.claim_token,
            expected_revision=claimed.revision,
            status=InvocationStatus.UNKNOWN,
            outcome=HandlerCallOutcome(
                DeliveryDisposition.INDETERMINATE, "prior_uncertain_dispatch"
            ),
        )
    return None


async def _dispatch(
    event_log: EventLogStore,
    invocation_store: InvocationStore,
    caller: HandlerCaller,
    trigger: TriggerDefinition,
    event: LoggedEvent,
) -> bool:
    """Run one trigger against one event; return whether it settled for cursor.

    Claims the receipt, compares the frozen delivery context, classifies prior
    uncertainty, consumes budget exactly once per physical send via
    ``begin_dispatch``, and settles with the begin snapshot's revision. A lost
    claim never authorizes HTTP, and an unverified stale settlement never
    advances the cursor.
    """
    delivery = DeliveryIdentity(
        handler_url=trigger.handler_url,
        request_digest=request_digest_v1(trigger.handler_url, event),
        replay_safety=trigger.effective_replay_safety,
        contract_ref=trigger.contract_ref,
    )
    claimed = await invocation_store.claim(trigger.trigger_id, event.id, delivery=delivery)
    if claimed is None:
        # Someone else owns this dispatch, or it is already settled. Either
        # way this worker must not send — and must not report the event
        # settled unless the reread actually says so.
        return await _reread_settled(invocation_store, trigger.trigger_id, event.id)

    prior_uncertainty = claimed.uncertain_prior_dispatch
    safe_contract = delivery.replay_safety in _SAFE_REPLAY_SAFETIES
    refused = await _settle_pre_send_refusal(invocation_store, claimed, trigger, event, delivery)
    if refused is not None:
        return refused

    try:
        begun = await invocation_store.begin_dispatch(
            claimed.trigger_id,
            claimed.event_id,
            claim_token=claimed.claim_token,
            expected_revision=claimed.revision,
            delivery=delivery,
        )
    except DeliveryAttemptLimitReached:
        return await _settle_attempt_limit(event_log, invocation_store, trigger, event, claimed)
    except DeliveryIdentityMismatch:
        return await _settle_refusal(
            invocation_store, claimed, reason_code="delivery_identity_changed"
        )
    except DeliveryAlreadyStarted:
        # This claim's dispatch is already in flight in another coroutine;
        # the marker's owner will settle it.
        return False
    if begun is None:
        return await _reread_settled(invocation_store, trigger.trigger_id, event.id)

    outcome = await _call_with_cancellation_settlement(
        invocation_store,
        caller,
        trigger,
        event,
        begun=begun,
        prior_uncertainty=prior_uncertainty,
        safe_contract=safe_contract,
    )
    status = _classify_outcome(
        attempts_used=begun.attempts,
        prior_uncertainty=prior_uncertainty,
        safe_contract=safe_contract,
        outcome=outcome,
    )
    if status is InvocationStatus.FAILED:
        await _append_handler_failed(
            event_log, trigger, event, outcome.detail or outcome.reason_code
        )
    return await _settle_and_report(
        invocation_store,
        claimed.trigger_id,
        claimed.event_id,
        claim_token=claimed.claim_token,
        expected_revision=begun.revision,
        status=status,
        outcome=outcome,
    )


async def _append_handler_failed(
    event_log: EventLogStore, trigger: TriggerDefinition, event: LoggedEvent, error: str
) -> None:
    logger.error(
        "Handler for trigger %s failed permanently on event %d: %s",
        trigger.name or trigger.trigger_id,
        event.id,
        error,
    )
    await event_log.append(
        HANDLER_FAILED_EVENT,
        entity_type="trigger",
        entity_id=trigger.trigger_id,
        payload={"trigger": trigger.name, "event_id": event.id, "error": error},
        source="reactor",
    )


async def _call_with_cancellation_settlement(
    invocation_store: InvocationStore,
    caller: HandlerCaller,
    trigger: TriggerDefinition,
    event: LoggedEvent,
    *,
    begun: HandlerInvocation,
    prior_uncertainty: bool,
    safe_contract: bool,
) -> HandlerCallOutcome:
    """Run the physical call; classify exceptions and cancellation.

    Cancellation uses the same indeterminate classifier: a bounded shielded
    settlement attempt is made, then the cancellation is re-raised — the
    durable marker (or a takeover's uncertainty fold) carries the truth if the
    attempt loses the race.
    """
    try:
        returned = await caller(trigger, event)
    except asyncio.CancelledError:
        outcome = HandlerCallOutcome(DeliveryDisposition.INDETERMINATE, "handler_cancelled")
        status = _classify_outcome(
            attempts_used=begun.attempts,
            prior_uncertainty=prior_uncertainty,
            safe_contract=safe_contract,
            outcome=outcome,
        )
        settlement = invocation_store.settle(
            begun.trigger_id,
            begun.event_id,
            claim_token=begun.claim_token,
            expected_revision=begun.revision,
            status=status,
            outcome=outcome,
        )
        with contextlib.suppress(asyncio.CancelledError, TimeoutError):
            # bounded: the durable marker/takeover owns the truth if this loses
            await asyncio.wait_for(asyncio.shield(settlement), timeout=_CANCELLED_SETTLE_TIMEOUT_S)
        raise
    except Exception as exc:
        # An arbitrary exception never proves the effect did not apply.
        return HandlerCallOutcome(
            DeliveryDisposition.INDETERMINATE, "handler_exception", str(exc)[:2048]
        )
    return validated_outcome(returned)


@dataclass(frozen=True)
class ProcessedBatch:
    """What one `process_events_batch` tick settled, and what it could not see.

    `cursor` is the id of the last event whose matching triggers have ALL
    reached a settled-for-cursor status — the same value `process_events`
    returns.

    `holes` lists, in ascending order, **every** id in ``(after_id, cursor]``
    that the log did not return this tick; it is empty when the ids the log
    returned were contiguous from ``after_id + 1``. Every missing id, not just
    the first of each gap, is reported — the durable consumer below may cross
    an id only once the log has proven *that id* terminally absent (#2509), so
    a report that collapsed a run to its first id would let the cursor cross
    the rest of the run unproven. The field exists for the PostgreSQL backend:
    `BIGSERIAL` allocates ids at insert time, before commit, so an appender
    that is slow to commit (or that rolls back) leaves a lower id invisible
    while a higher one is already readable. Advancing a *durable* cursor past
    such a hole would exclude the slow event from every later ``id > cursor``
    read, restart included — the one case where a resume optimisation would
    lose an event. `process_events` itself keeps working on the events it can
    see; the caller decides what a hole means for the cursor it persists.
    """

    cursor: int
    holes: tuple[int, ...] = ()


async def process_events_batch(
    event_log: EventLogStore,
    trigger_store: TriggerStore,
    invocation_store: InvocationStore,
    caller: HandlerCaller,
    *,
    after_id: int = 0,
    limit: int = 100,
) -> ProcessedBatch:
    """`process_events`, also reporting the ids the log skipped over.

    Delivery semantics are unchanged (see `process_events`). The addition is
    the contiguity check: as events are settled in id order, every id the log
    skipped — the whole missing run, not just its first id — is reported
    alongside the cursor so a durable consumer can refuse to persist past any
    of them unproven (#2509).
    """
    events = await event_log.query(after_id=after_id, limit=limit)
    cursor = after_id
    holes: list[int] = []
    for event in events:
        settled = [
            await _dispatch(event_log, invocation_store, caller, trigger, event)
            for trigger in await trigger_store.get_matching(event.event_type)
        ]
        event_settled = all(settled)
        if not event_settled:
            # Hold the cursor: this event must be replayed next tick.
            break
        if event.id != cursor + 1:
            holes.extend(range(cursor + 1, event.id))
        cursor = event.id
    return ProcessedBatch(cursor=cursor, holes=tuple(holes))


async def process_events(
    event_log: EventLogStore,
    trigger_store: TriggerStore,
    invocation_store: InvocationStore,
    caller: HandlerCaller,
    *,
    after_id: int = 0,
    limit: int = 100,
) -> int:
    """Process up to ``limit`` events after cursor ``after_id``; return new cursor.

    The cursor advances only past settled receipts (success/failed/unknown).
    Restarting from an older cursor redelivers under the same persisted
    delivery key, and an idempotent/read_only recipient deduplicates that key
    at its own commit boundary; the receipt alone supplies only dispatch
    deduplication. UNKNOWN receipts stay visible while later events advance.

    Safe to run in more than one process: `_dispatch` claims each
    (trigger, event) before invoking anything, so exactly one worker is the
    active dispatcher at a time.

    A caller that persists the cursor durably should use
    `process_events_batch` instead, which also reports whether the log had a
    hole below the returned cursor (an id allocated but not yet committed);
    this convenience keeps the original contract for callers whose cursor is
    process-local and so is rebuilt from zero on restart anyway.
    """
    batch = await process_events_batch(
        event_log,
        trigger_store,
        invocation_store,
        caller,
        after_id=after_id,
        limit=limit,
    )
    return batch.cursor


# ---
# Canonical-Envelope -> durable-log replay projection (#2506).
#
# The persist-first publisher (`CanonicalEventPublisher`) projects an inserted
# canonical Event onto the legacy bus, whose authoritative `before_handlers`
# bridge appends it into this module's `EventLogStore` — the durable trigger
# log's only ingress. That ingress is at-most-once: a durable-log append that
# fails after the canonical append has committed is correctly surfaced
# (`EventSubscriberFailure`), but the canonical fact is already durable and a
# retry emission of the same `event_id` returns `inserted=False`, suppressing
# the bridge forever. The event then sits outside the only log the trigger
# cursor scans.
#
# The projection below closes that window without creating a second event
# identity or processing lifecycle: a bounded, per-stream replay cursor over
# the canonical EventStore, with source-`event_id` dedupe enforced by the log
# itself (`append(source_event_id=...)`), retry backoff, a terminal
# dead-letter disposition for poison records, and per-stream lease/fencing so
# two replicas share delivery. It is ticked by `Container.process_durable_events`
# — the ordinary ADR-086 processing tick — before the legacy pass, so healing
# needs no special repair path and no test-only entry point.

DEFAULT_MAX_PROJECTION_ATTEMPTS = 3
"""Total attempts a failing projection append gets before it is dead-lettered.

Mirrors ``MAX_PUBLISH_ATTEMPTS`` on the SQLite outbox and ``MAX_ATTEMPTS`` on
delivery receipts: a bounded terminal disposition beats an unbounded retry
loop that wedges the stream's later events forever.
"""

DEFAULT_PROJECTION_BACKOFF_SECONDS = 1.0
"""How long a stream event that just failed its log append waits before its
next attempt is due. A backoff window that has not elapsed holds the stream's
cursor (and therefore its later events) below the failure for this tick —
the same same-stream head-of-line behavior the outbox chose (#1162)."""


DEFAULT_PROJECTION_LEASE_SECONDS = 300.0
"""How long a claimed projection-stream scan lease stays owned before another
replica may take it. Mirrors `events.consumer_cursor.DEFAULT_LEASE_SECONDS`:
long enough that a normal scan is not stolen mid-run, short enough that a
replica killed right after claiming does not strand its streams. Deliberately
a projection-local constant and lease type — the legacy bridge's cursor store
is a separate consumer's mechanics, not an import surface for this one."""


@dataclass(frozen=True)
class ProjectionLease:
    """Exclusive (for the lease) permission to scan one canonical stream.

    `position` is the durable scan position as of the claim; `fencing_token`
    must accompany every `advance`, and a token the store no longer recognises
    means the lease was taken over and the write is refused.
    """

    position: int
    fencing_token: str
    expires_at: float


@dataclass(frozen=True)
class ProjectionFailure:
    """One canonical event whose durable-log append keeps failing.

    ``poisoned_at`` is the terminal poison disposition: set after
    ``max_attempts`` total attempts, it releases the stream (the projector's
    cursor moves past the event) while keeping the failure visible and
    addressable through ``dead_letters``. Identity is the canonical
    ``event_id`` — stable across restarts and replicas.
    """

    event_id: str
    stream_id: str
    attempts: int
    last_error: str
    next_attempt_at: float
    poisoned_at: float | None


@runtime_checkable
class CanonicalProjectionStore(Protocol):
    """Durable per-stream replay cursor for the canonical-log projector (#2506).

    One row per canonical stream. `register_stream` inserts a stream the
    publisher has not seen before at the canonical store's *current*
    high-water sequence — everything at or below it was the pre-projection
    bridge's responsibility and is deliberately never rescanned, so retained
    history cannot be projected a second time. `claim`/`advance` are the same
    leased+fenced, monotonic mechanics the legacy-bridge cursor store uses
    (`events.consumer_cursor`), so two replicas share delivery without
    double-projecting.
    """

    async def register_stream(self, stream_id: str) -> None:
        """Track ``stream_id`` if absent, positioned at its canonical watermark."""
        ...

    async def registered_streams(self) -> tuple[str, ...]:
        """Every tracked stream id, in stable order."""
        ...

    async def claim(
        self,
        stream_id: str,
        *,
        holder: str,
        lease_seconds: float = DEFAULT_PROJECTION_LEASE_SECONDS,
    ) -> ProjectionLease | None:
        """Take or renew this stream's scan lease; ``None`` while another
        holder's lease is live (the caller skips the stream this tick)."""
        ...

    async def advance(self, stream_id: str, *, fencing_token: str, position: int) -> bool:
        """Record the highest confirmed sequence; refuses a stale fencing token
        and never moves the position backwards."""
        ...


@runtime_checkable
class ProjectionFailureStore(Protocol):
    """Durable poison bookkeeping for canonical events that fail to project."""

    async def record_failure(self, event_id: str, stream_id: str, error: str) -> bool:
        """Record one failed attempt; return whether the row is now dead-lettered."""
        ...

    async def forget(self, event_id: str) -> None:
        """Drop any failure evidence — the event's row is confirmed in the log."""
        ...

    async def get(self, event_id: str) -> ProjectionFailure | None:
        """Current failure state for one canonical event."""
        ...

    async def poisoned_records(self, *, limit: int = 100) -> list[ProjectionFailure]:
        """Events past their attempt bound, oldest first, with their evidence."""
        ...


@dataclass(frozen=True)
class ProjectionOutcome:
    """What one `project_canonical_events` pass confirmed, per stream."""

    streams_scanned: int
    #: canonical events whose durable-log row this pass confirmed (appended
    #: now, or already present via the bridge — the log's dedupe decides).
    projected: int
    #: events whose terminal poison disposition this pass released.
    dead_lettered: int
    #: per-stream cursor after the pass; only streams this holder scanned.
    cursors: dict[str, int]


class _ProjectionStep(StrEnum):
    """What one canonical event decided for its stream's scan."""

    CONFIRMED = "confirmed"
    DEAD = "dead"
    HOLD = "hold"


async def _confirm_projection(
    event: EventEnvelope,
    *,
    event_log: EventLogStore,
    failure_store: ProjectionFailureStore,
    append_kwargs: Callable[[EventEnvelope], dict[str, Any]],
    now: float,
) -> _ProjectionStep:
    """Confirm one canonical event's durable-log row, or refuse to pass it.

    ``CONFIRMED`` — the row is present (appended now, or already written by
    the bridge; the log's source-`event_id` dedupe makes both one row).
    ``DEAD`` — a terminal poison disposition released the event; the cursor
    may move past it. ``HOLD`` — a retryable failure stands between the
    cursor and this event; the stream stops below it this tick.
    """
    failure = await failure_store.get(event.event_id)
    if failure is not None:
        if failure.poisoned_at is not None:
            # Poison disposition is terminal: the stream flows past the
            # event, and the failure stays visible for repair.
            return _ProjectionStep.DEAD
        if failure.next_attempt_at > now:
            # Backoff window not elapsed: this event holds the stream's
            # cursor (and its later events) below it for this tick.
            return _ProjectionStep.HOLD
    try:
        await event_log.append(**append_kwargs(event))
    except Exception as exc:
        dead = await failure_store.record_failure(
            event.event_id, str(event.stream_id), f"{type(exc).__name__}: {exc}"
        )
        return _ProjectionStep.DEAD if dead else _ProjectionStep.HOLD
    await failure_store.forget(event.event_id)
    return _ProjectionStep.CONFIRMED


class InMemoryCanonicalProjectionStore:
    """In-memory :class:`CanonicalProjectionStore` (tests, dry-run)."""

    def __init__(self, watermark_source: Any) -> None:
        # The canonical EventStore whose `stream_watermark` positions new
        # registrations; injected because the in-memory canonical store keeps
        # its streams in process memory beside this store.
        self._watermark_source = watermark_source
        self._rows: dict[str, tuple[int, str, str, float]] = {}
        self._lock = asyncio.Lock()

    async def register_stream(self, stream_id: str) -> None:
        watermark = await self._watermark_source.stream_watermark(stream_id)
        async with self._lock:
            if stream_id not in self._rows:
                self._rows[stream_id] = (watermark, "", "", 0.0)

    async def registered_streams(self) -> tuple[str, ...]:
        return tuple(sorted(self._rows))

    async def claim(
        self,
        stream_id: str,
        *,
        holder: str,
        lease_seconds: float = DEFAULT_PROJECTION_LEASE_SECONDS,
    ) -> ProjectionLease | None:
        async with self._lock:
            now = time.time()
            existing = self._rows.get(stream_id)
            if existing is None:
                # A stream the publisher has not registered yet cannot be
                # positioned here — refusing beats silently starting at 0,
                # which would rescan retained history.
                return None
            position, existing_holder, existing_token, expires_at = existing
            if expires_at > now and existing_holder != holder:
                return None
            token = existing_token if existing_holder == holder else uuid.uuid4().hex
            self._rows[stream_id] = (position, holder, token, now + lease_seconds)
            return ProjectionLease(
                position=position, fencing_token=token, expires_at=now + lease_seconds
            )

    async def advance(self, stream_id: str, *, fencing_token: str, position: int) -> bool:
        async with self._lock:
            existing = self._rows.get(stream_id)
            if existing is None or existing[2] != fencing_token:
                return False
            self._rows[stream_id] = (
                max(existing[0], position),
                existing[1],
                existing[2],
                existing[3],
            )
            return True


class InMemoryProjectionFailureStore:
    """In-memory :class:`ProjectionFailureStore` (tests, dry-run)."""

    def __init__(
        self,
        *,
        max_attempts: int = DEFAULT_MAX_PROJECTION_ATTEMPTS,
        retry_backoff_seconds: float = DEFAULT_PROJECTION_BACKOFF_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be non-negative")
        self._max_attempts = max_attempts
        self._retry_backoff_seconds = retry_backoff_seconds
        self._clock = clock
        self._failures: dict[str, ProjectionFailure] = {}

    async def record_failure(self, event_id: str, stream_id: str, error: str) -> bool:
        existing = self._failures.get(event_id)
        if existing is not None and existing.poisoned_at is not None:
            # Terminal disposition is never resurrected by a later attempt.
            return True
        attempts = (existing.attempts if existing is not None else 0) + 1
        now = self._clock()
        poisoned_at = now if attempts >= self._max_attempts else None
        next_attempt_at = 0.0 if poisoned_at is not None else now + self._retry_backoff_seconds
        self._failures[event_id] = ProjectionFailure(
            event_id=event_id,
            stream_id=stream_id,
            attempts=attempts,
            last_error=error[:2048],
            next_attempt_at=next_attempt_at,
            poisoned_at=poisoned_at,
        )
        return poisoned_at is not None

    async def forget(self, event_id: str) -> None:
        self._failures.pop(event_id, None)

    async def get(self, event_id: str) -> ProjectionFailure | None:
        return self._failures.get(event_id)

    async def poisoned_records(self, *, limit: int = 100) -> list[ProjectionFailure]:
        dead = [f for f in self._failures.values() if f.poisoned_at is not None]
        return sorted(dead, key=lambda f: f.event_id)[:limit]


_PROJECTION_SCHEMA = """
CREATE TABLE IF NOT EXISTS canonical_event_projection_streams (
    stream_id TEXT PRIMARY KEY,
    position INTEGER NOT NULL DEFAULT 0,
    holder TEXT NOT NULL DEFAULT '',
    fencing_token TEXT NOT NULL DEFAULT '',
    lease_expires_at REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS canonical_projection_failures (
    event_id TEXT PRIMARY KEY,
    stream_id TEXT NOT NULL DEFAULT '',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    next_attempt_at REAL NOT NULL DEFAULT 0,
    failed_at REAL
);
"""


class SqliteCanonicalProjectionStore:
    """SQLite-backed :class:`CanonicalProjectionStore`.

    Composed on the same connection as the canonical SQLite EventStore: the
    watermark subquery below reads `canonical_event_stream_watermarks` from
    that store's schema, so a new registration and its positioning position
    are one statement on one database.
    """

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def ensure_schema(self) -> None:
        await execute_schema_script(self._conn, _PROJECTION_SCHEMA)
        await self._conn.commit()

    async def register_stream(self, stream_id: str) -> None:
        await self._conn.execute(
            """INSERT INTO canonical_event_projection_streams
               (stream_id, position, holder, fencing_token, lease_expires_at)
               SELECT ?, COALESCE((SELECT last_sequence
                                   FROM canonical_event_stream_watermarks
                                   WHERE stream_id = ?), 0), '', '', 0
               ON CONFLICT(stream_id) DO NOTHING""",
            (stream_id, stream_id),
        )
        await self._conn.commit()

    async def registered_streams(self) -> tuple[str, ...]:
        cursor = await self._conn.execute(
            "SELECT stream_id FROM canonical_event_projection_streams ORDER BY stream_id ASC"
        )
        return tuple(str(row[0]) for row in await cursor.fetchall())

    async def claim(
        self,
        stream_id: str,
        *,
        holder: str,
        lease_seconds: float = DEFAULT_PROJECTION_LEASE_SECONDS,
    ) -> ProjectionLease | None:
        now = time.time()
        new_token = uuid.uuid4().hex
        cursor = await self._conn.execute(
            """INSERT INTO canonical_event_projection_streams
               (stream_id, position, holder, fencing_token, lease_expires_at)
               VALUES (?, 0, ?, ?, ?)
               ON CONFLICT(stream_id) DO UPDATE SET
                 holder = excluded.holder,
                 fencing_token = CASE WHEN canonical_event_projection_streams.holder
                                       = excluded.holder
                                       THEN canonical_event_projection_streams.fencing_token
                                       ELSE excluded.fencing_token END,
                 lease_expires_at = excluded.lease_expires_at
               WHERE canonical_event_projection_streams.lease_expires_at <= ?
                  OR canonical_event_projection_streams.holder = ?
               RETURNING stream_id, position, fencing_token, lease_expires_at""",
            (stream_id, holder, new_token, now + lease_seconds, now, holder),
        )
        row = await cursor.fetchone()
        await self._conn.commit()
        return _sqlite_row_to_lease(tuple(row)) if row is not None else None

    async def advance(self, stream_id: str, *, fencing_token: str, position: int) -> bool:
        cursor = await self._conn.execute(
            """UPDATE canonical_event_projection_streams
               SET position = MAX(position, ?)
               WHERE stream_id = ? AND fencing_token = ?
               RETURNING stream_id""",
            (position, stream_id, fencing_token),
        )
        row = await cursor.fetchone()
        await self._conn.commit()
        return row is not None


class SqliteProjectionFailureStore:
    """SQLite-backed :class:`ProjectionFailureStore`."""

    def __init__(
        self,
        conn: aiosqlite.Connection,
        *,
        max_attempts: int = DEFAULT_MAX_PROJECTION_ATTEMPTS,
        retry_backoff_seconds: float = DEFAULT_PROJECTION_BACKOFF_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be non-negative")
        self._conn = conn
        self._max_attempts = max_attempts
        self._retry_backoff_seconds = retry_backoff_seconds
        self._clock = clock

    async def ensure_schema(self) -> None:
        await execute_schema_script(self._conn, _PROJECTION_SCHEMA)
        await self._conn.commit()

    async def record_failure(self, event_id: str, stream_id: str, error: str) -> bool:
        now = self._clock()
        cursor = await self._conn.execute(
            """INSERT INTO canonical_projection_failures
               (event_id, stream_id, attempts, last_error, next_attempt_at, failed_at)
               VALUES (?, ?, 1, ?, ?, NULL)
               ON CONFLICT(event_id) DO UPDATE SET
                 attempts = canonical_projection_failures.attempts + 1,
                 last_error = excluded.last_error,
                 next_attempt_at = excluded.next_attempt_at,
                 failed_at = CASE
                   WHEN canonical_projection_failures.attempts + 1 >= ?
                   THEN ? ELSE canonical_projection_failures.failed_at END
               WHERE canonical_projection_failures.failed_at IS NULL
               RETURNING attempts""",
            (
                event_id,
                stream_id,
                error[:2048],
                now + self._retry_backoff_seconds,
                self._max_attempts,
                now,
            ),
        )
        row = await cursor.fetchone()
        await self._conn.commit()
        if row is None:
            # Already dead-lettered; the disposition is terminal.
            return True
        return int(row[0]) >= self._max_attempts

    async def forget(self, event_id: str) -> None:
        await self._conn.execute(
            "DELETE FROM canonical_projection_failures WHERE event_id = ?", (event_id,)
        )
        await self._conn.commit()

    async def get(self, event_id: str) -> ProjectionFailure | None:
        cursor = await self._conn.execute(
            """SELECT event_id, stream_id, attempts, last_error, next_attempt_at, failed_at
               FROM canonical_projection_failures WHERE event_id = ?""",
            (event_id,),
        )
        row = await cursor.fetchone()
        return _sqlite_row_to_failure(tuple(row)) if row is not None else None

    async def poisoned_records(self, *, limit: int = 100) -> list[ProjectionFailure]:
        cursor = await self._conn.execute(
            """SELECT event_id, stream_id, attempts, last_error, next_attempt_at, failed_at
               FROM canonical_projection_failures
               WHERE failed_at IS NOT NULL
               ORDER BY event_id ASC LIMIT ?""",
            (limit,),
        )
        return [_sqlite_row_to_failure(tuple(row)) for row in await cursor.fetchall()]


def _sqlite_row_to_lease(row: tuple[object, ...]) -> ProjectionLease:
    return ProjectionLease(
        position=int(row[1]),  # type: ignore[call-overload]
        fencing_token=str(row[2]),
        expires_at=float(row[3]),  # type: ignore[arg-type]
    )


def _sqlite_row_to_failure(row: tuple[object, ...]) -> ProjectionFailure:
    return ProjectionFailure(
        event_id=str(row[0]),
        stream_id=str(row[1] or ""),
        attempts=int(row[2]),  # type: ignore[call-overload]
        last_error=str(row[3] or ""),
        next_attempt_at=float(row[4]),  # type: ignore[arg-type]
        poisoned_at=float(row[5]) if row[5] is not None else None,  # type: ignore[arg-type]
    )


async def project_canonical_events(
    *,
    projection_store: CanonicalProjectionStore,
    event_store: Any,
    event_log: EventLogStore,
    failure_store: ProjectionFailureStore,
    append_kwargs: Callable[[EventEnvelope], dict[str, Any]],
    holder: str,
    limit: int = 100,
    lease_seconds: float = DEFAULT_PROJECTION_LEASE_SECONDS,
    clock: Callable[[], float] = time.time,
) -> ProjectionOutcome:
    """Replay canonical Events missing from the durable trigger log (#2506).

    Per registered stream, under a leased+fenced claim: scan the canonical
    EventStore above the stream's cursor and confirm each event's durable-log
    row. The log's source-`event_id` dedupe makes "append" the only operation
    needed — a row the bridge already wrote comes back unchanged, a missing
    row is written with the exact mapping the bridge uses, and a concurrent
    duplicate append converges on the one row. The cursor advances to each
    confirmed sequence; an append failure records a bounded attempt (backoff
    holds the stream below the failure this tick, later events of the same
    stream wait behind it), and past the attempt bound the event is
    dead-lettered — a visible terminal disposition that releases the stream.
    Canonical sequences are contiguous by construction (the stream watermark
    advances only in the appending transaction), so the cursor can never skip
    an invisible committed Event: an aborted append leaves no gap behind.

    ``append_kwargs`` maps a persisted canonical Event onto durable-log
    ``append`` kwargs; the container injects the publisher's
    `canonical_log_append_kwargs` so a healed row carries exactly the shape
    the bridge would have written, keyed by the canonical `event_id` the log
    dedupes on (#2506).

    Returns what this holder confirmed; streams another replica's live lease
    covers are skipped, not re-scanned.
    """
    projected = 0
    dead_lettered = 0
    scanned = 0
    cursors: dict[str, int] = {}
    for stream_id in await projection_store.registered_streams():
        lease = await projection_store.claim(stream_id, holder=holder, lease_seconds=lease_seconds)
        if lease is None:
            # Another replica holds this stream's tick lease; its scan covers
            # this round. Skipping is what makes two replicas share delivery.
            continue
        scanned += 1
        position = lease.position
        batch = await event_store.list_stream(stream_id, after_sequence=position, limit=limit)
        for event in batch:
            if event.sequence is None:  # pragma: no cover - stores assign sequences
                break
            step = await _confirm_projection(
                event,
                event_log=event_log,
                failure_store=failure_store,
                append_kwargs=append_kwargs,
                now=clock(),
            )
            if step is _ProjectionStep.HOLD:
                break
            position = event.sequence
            cursors[stream_id] = position
            if step is _ProjectionStep.CONFIRMED:
                projected += 1
            else:
                dead_lettered += 1
        if position > lease.position:
            await projection_store.advance(
                stream_id, fencing_token=lease.fencing_token, position=position
            )
    return ProjectionOutcome(
        streams_scanned=scanned,
        projected=projected,
        dead_lettered=dead_lettered,
        cursors=cursors,
    )
