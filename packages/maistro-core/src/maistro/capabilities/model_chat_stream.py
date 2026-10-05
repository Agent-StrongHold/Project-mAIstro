"""Bounded chunk delivery around the existing governed Invocation task.

This module owns no lifecycle transitions: cancellation is delivered to the
same invocation task that admitted and dispatched the Provider.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable, Coroutine
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from maistro.capabilities.invocation import EffectNotApplied

if TYPE_CHECKING:
    from maistro.capabilities.model_chat import ModelCallResult


class StreamDelivery:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1)
        self.provider_started = False
        self.provider_finished = False
        self.stop_requested = False

    def start_provider(self) -> None:
        """Refuse a closed consumer before any physical dispatch can begin."""
        if self.stop_requested:
            raise EffectNotApplied("model stream closed before provider dispatch")
        self.provider_started = True

    async def publish(self, chunk: dict[str, Any]) -> None:
        await self.queue.put(chunk)


def _replay_chunk(body: dict[str, Any]) -> dict[str, Any]:
    chunk = {key: value for key, value in body.items() if key != "choices"}
    chunk["_maistro_replayed"] = True
    chunk["choices"] = [
        {
            **{key: value for key, value in choice.items() if key != "message"},
            "delta": choice.get("message", {}),
        }
        for choice in body.get("choices", [])
    ]
    return chunk


async def stream_model_call(
    invoke: Callable[[StreamDelivery], Coroutine[Any, Any, ModelCallResult]],
) -> AsyncGenerator[dict[str, Any], None]:
    delivery = StreamDelivery()
    invocation = asyncio.create_task(invoke(delivery))
    pending: asyncio.Task[dict[str, Any]] | None = None
    emitted = False
    try:
        while not invocation.done() or not delivery.queue.empty():
            pending = asyncio.create_task(delivery.queue.get())
            await asyncio.wait({invocation, pending}, return_when=asyncio.FIRST_COMPLETED)
            if pending.done():
                chunk = pending.result()
                pending = None
                emitted = True
                yield chunk
            else:
                pending.cancel()
                with suppress(asyncio.CancelledError):
                    await pending
                pending = None
        result = await invocation
        if not emitted:
            yield _replay_chunk(result.body)
    finally:
        await _join_invocation(invocation, pending, delivery=delivery)


async def _join_invocation(
    invocation: asyncio.Task[ModelCallResult],
    pending: asyncio.Task[dict[str, Any]] | None,
    *,
    delivery: StreamDelivery,
) -> None:
    """Keep cleanup alive through repeated consumer cancellation.

    Gathering retrieves task exceptions without masking the original stream
    error or close. Cancellation of this consumer never cancels the canonical
    admission or terminal write: only an active Provider is cancelled, exactly
    once. A pending admission reaches its executor with stop_requested set and
    refuses before HTTP, using the existing no-effect terminalization path.
    """
    delivery.stop_requested = True
    tasks: list[asyncio.Task[Any]] = [invocation]
    if pending is not None:
        pending.cancel()
        tasks.append(pending)
    if not invocation.done() and delivery.provider_started and not delivery.provider_finished:
        invocation.cancel()
    invocation_settlement = asyncio.gather(*tasks, return_exceptions=True)
    cancelled = False
    while not invocation_settlement.done():
        try:
            await asyncio.shield(invocation_settlement)
        except asyncio.CancelledError:
            cancelled = True
    if cancelled:
        raise asyncio.CancelledError
