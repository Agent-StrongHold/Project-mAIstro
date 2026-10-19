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
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import httpx

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

if TYPE_CHECKING:
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
        current = await invocation_store.get(trigger.trigger_id, event.id)
        return current is not None and current.settled_for_cursor

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

    prior_uncertainty = claimed.uncertain_prior_dispatch
    safe_contract = delivery.replay_safety in _SAFE_REPLAY_SAFETIES
    if prior_uncertainty and not safe_contract:
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
        current = await invocation_store.get(trigger.trigger_id, event.id)
        return current is not None and current.settled_for_cursor

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

    `holes` lists, in ascending order, the first id of every run of ids in
    ``(after_id, cursor]`` that the log did not return this tick; it is empty
    when the ids the log returned were contiguous from ``after_id + 1``. The
    field exists for the PostgreSQL backend:
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
    the contiguity check: as events are settled in id order, each one whose
    id is not ``previous + 1`` marks a hole, and the first missing id of each
    is reported alongside the cursor so a durable consumer can refuse to
    persist past it.
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
            holes.append(cursor + 1)
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
