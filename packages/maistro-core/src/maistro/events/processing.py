"""Event processing loop: durable log -> triggers -> idempotent handler calls.

Pure async function (`process_events`) with injected stores and handler
caller, designed to be ticked by the reactor loop (SPEC-013). All delivery
semantics from ADR-086 live here:

- at-least-once: the cursor only advances past an event once every matching
  trigger's invocation is terminal (success or failed), so a crash replays it;
- idempotent: (trigger_id, event_id) invocation rows dedupe redelivery;
- retry: a failing handler is retried on subsequent ticks up to
  ``MAX_ATTEMPTS`` (3) total attempts, then marked failed and a
  ``handler.failed`` event is appended to the log.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import httpx

from maistro.events.invocations import MAX_ATTEMPTS, InvocationStatus
from maistro.http import shared_client

if TYPE_CHECKING:
    from maistro.events.durable_log import EventLogStore, LoggedEvent
    from maistro.events.invocations import InvocationStore
    from maistro.events.trigger_store import TriggerDefinition, TriggerStore

logger = logging.getLogger("maistro.events.processing")

HANDLER_FAILED_EVENT = "handler.failed"


class HandlerCallError(Exception):
    """A handler invocation failed (HTTP error status, transport error, ...)."""


@runtime_checkable
class HandlerCaller(Protocol):
    """Injected async callable that delivers an event to a trigger's handler.

    Must raise :class:`HandlerCallError` (or any exception) on failure;
    returning normally means the handler committed its effect.
    """

    async def __call__(self, trigger: TriggerDefinition, event: LoggedEvent) -> None: ...


class HTTPHandlerCaller:
    """POST the event JSON to ``trigger.handler_url`` via httpx."""

    def __init__(self, timeout: float = 5.0, client: httpx.AsyncClient | None = None) -> None:
        self._timeout = timeout
        self._client = client

    async def __call__(self, trigger: TriggerDefinition, event: LoggedEvent) -> None:
        try:
            if self._client is not None:
                response = await self._client.post(
                    trigger.handler_url, json=event.to_dict(), timeout=self._timeout
                )
            else:
                async with shared_client(timeout=self._timeout) as client:
                    response = await client.post(trigger.handler_url, json=event.to_dict())
        except httpx.HTTPError as exc:
            raise HandlerCallError(f"transport error calling {trigger.handler_url}: {exc}") from exc
        if response.status_code >= 400:
            raise HandlerCallError(f"{response.status_code}: {response.text}")


async def _dispatch(
    event_log: EventLogStore,
    invocation_store: InvocationStore,
    caller: HandlerCaller,
    trigger: TriggerDefinition,
    event: LoggedEvent,
) -> bool:
    """Run one trigger against one event; return whether it has settled.

    "Settled" means terminal — succeeded, or failed past `MAX_ATTEMPTS`. An
    unsettled trigger holds the caller's cursor back so the next tick replays
    the event, which is what makes a crash mid-handler safe.

    Split out of `process_events` because the loop grew past the complexity
    ratchet when dispatch became a claim; the two halves read better apart
    anyway — this one owns one invocation, the caller owns the cursor.
    """
    # `claim`, not `get_or_create`: the latter hands every racing worker the
    # same non-terminal row, and a non-terminal row reads as permission to call
    # the handler — so two workers both fired the side effect on one event.
    # `claim` returns the invocation to exactly one of them and `None` to the
    # rest, whether the answer is "already done" or "someone else has it".
    #
    # `attempts` is incremented by the claim itself, inside the same statement,
    # so a handler that keeps dying still converges on MAX_ATTEMPTS instead of
    # being retried forever by whichever worker happens to win each round.
    invocation = await invocation_store.claim(trigger.trigger_id, event.id)
    if invocation is None:
        # Someone else owns this dispatch, or it is already settled. Either way
        # this worker must not call the handler — and must not report the event
        # settled unless it actually is, or the cursor advances past an event
        # still in flight and nothing ever replays it.
        settled = await invocation_store.get(trigger.trigger_id, event.id)
        return settled is not None and settled.is_terminal

    event_settled = True
    try:
        await caller(trigger, event)
    except Exception as exc:
        invocation.last_error = str(exc)
        if invocation.attempts >= MAX_ATTEMPTS:
            invocation.status = InvocationStatus.FAILED
            logger.error(
                "Handler for trigger %s failed permanently on event %d: %s",
                trigger.name or trigger.trigger_id,
                event.id,
                exc,
            )
            await event_log.append(
                HANDLER_FAILED_EVENT,
                entity_type="trigger",
                entity_id=trigger.trigger_id,
                payload={"trigger": trigger.name, "event_id": event.id, "error": str(exc)},
                source="reactor",
            )
        else:
            invocation.status = InvocationStatus.RETRYING
            event_settled = False
    else:
        invocation.status = InvocationStatus.SUCCESS
        invocation.last_error = ""
    # Release the lease on the way out. Without this a RETRYING invocation stays
    # owned by a worker that has already finished with it, and nothing retries
    # the event until the lease lapses — a failed attempt would sit idle for the
    # whole lease window instead of being picked up on the next tick. Terminal
    # statuses do not need it (`claim` refuses them anyway); releasing uniformly
    # means there is no path that forgets.
    invocation.lease_expires_at = 0.0
    await invocation_store.save(invocation)
    return event_settled


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

    The returned cursor is the id of the last event whose matching triggers
    have ALL reached a terminal status; persist it between ticks and pass it
    back as ``after_id``. Events with retrying/pending invocations hold the
    cursor back so the next tick retries them. Restarting from an older
    cursor (e.g. 0 after a crash) is safe: successful invocations are
    skipped, so no handler double-applies.

    Safe to run in more than one process: `_dispatch` claims each
    (trigger, event) before invoking anything, so exactly one worker calls a
    given handler.
    """
    events = await event_log.query(after_id=after_id, limit=limit)
    cursor = after_id
    for event in events:
        settled = [
            await _dispatch(event_log, invocation_store, caller, trigger, event)
            for trigger in await trigger_store.get_matching(event.event_type)
        ]
        event_settled = all(settled)
        if not event_settled:
            # Hold the cursor: this event must be replayed next tick.
            break
        cursor = event.id
    return cursor
