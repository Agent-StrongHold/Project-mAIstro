"""Bounded, cursor-fair page walking for recovery/discovery scans.

Five M1 audit issues (#1098, #1056, #1109, #1127, and the fairness half of
#1143) describe the same defect at different seams: a bounded, oldest-first
``list_by_status(..., limit=N)``/``list_due(..., limit=N)`` query, followed by
an *in-memory* eligibility filter applied to that fixed page. If more than
``N`` rows ahead of the eligible ones belong to another consumer, have no
deadline yet, or are not human work, every tick re-reads the identical
ineligible prefix and the eligible work behind it is never reached — even
though it is durably correct and the deadline has passed.

``fair_page_scan`` is the one fix for all of them: push eligibility filtering
*into* the page walk by advancing a keyset cursor (``after``) that every
caller here already exposes, oldest/earliest-first, rather than filtering a
single fixed-size page after the fact. The walk is bounded by
``max_inspected`` so one pathological prefix cannot turn a tick into an
unbounded table scan (the stop condition every one of those issues states
explicitly).

**A bounded scan needs a continuation, or the bound becomes the starvation.**
On its own, ``max_inspected`` recreates the defect one size up: a scan that
always starts from the top and may inspect at most N rows can never reach an
eligible row behind N ineligible ones, however many ticks it is given — every
tick re-reads the same prefix and stops at the same place. ``ScanContinuation``
is what makes the bound a *pace* rather than a *ceiling*: the caller holds one
per seam across ticks, the scan resumes after the last row it inspected, and
it restarts from the top only once it has walked off the end of the store.
Every row is therefore inspected within ``ceil(rows / max_inspected)`` ticks,
whatever sits ahead of it. The continuation carries a position and nothing
else — eligibility is still re-derived from durable facts on every read — so
a process restart costs the position, never correctness.

This module owns no lifecycle, no recovery policy, and no store. It is a pure
combinator over whatever page-fetch closure and eligibility predicate the
caller supplies.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")
C = TypeVar("C")

#: Default ceiling on rows *inspected* by one bounded scan call, independent
#: of how many turn out eligible. Keeps one starvation-prone prefix from
#: turning a single tick into an unbounded walk. It is a pace, not a horizon:
#: a caller that hands the scan a `ScanContinuation` reaches the rows behind
#: the ceiling on the following ticks rather than never.
DEFAULT_MAX_INSPECTED = 2000

#: Default page size requested from the underlying store on each fetch.
DEFAULT_PAGE_SIZE = 100


@dataclass
class ScanContinuation(Generic[C]):
    """Where a bounded scan resumes on its next tick (#1127, #1098).

    Owned by the caller — one per seam per store, held across ticks — never
    by this module, which keeps nothing between calls. ``resume_after`` is
    the keyset position of the last row the previous tick inspected, or
    ``None`` to start from the top of the ordering.

    Restart semantics are explicit and there are exactly two: the scan resets
    the position to ``None`` itself when it walks off the end of the store, so
    the rows before this tick's starting point get their turn next; and the
    caller sets it to ``None`` when the store or ordering behind the position
    changes, which is the only other time a saved position stops meaning
    anything. A position that has become stale any other way — the row it
    names was deleted, say — is harmless: keyset paging reads strictly after
    it, and a position past the end costs one empty tick before the reset.
    """

    resume_after: C | None = None


@dataclass(frozen=True)
class _Walk(Generic[T, C]):
    items: list[T]
    resume_after: C | None


async def fair_page_scan(
    *,
    fetch_page: Callable[[C | None, int], Awaitable[list[T]]],
    cursor_of: Callable[[T], C],
    eligible: Callable[[T], bool],
    limit: int,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_inspected: int = DEFAULT_MAX_INSPECTED,
    continuation: ScanContinuation[C] | None = None,
) -> list[T]:
    """Walk pages by cursor until ``limit`` eligible items are found.

    ``fetch_page(cursor, page_size)`` must return rows strictly after
    ``cursor`` in the same deterministic order ``cursor_of`` is drawn from
    (``None`` for the first page) — the exact contract every keyset-paginated
    ``list_by_status``/``list_due`` already documents. An *empty* page ends
    the walk. A short-but-nonempty page does not: some callers (notably
    ``CanonicalDurableRunStore.list_due``, which re-checks freshness against
    the canonical Run after paging its index) can legitimately return fewer
    rows than requested without that meaning no more rows exist, so treating
    a short page as "done" would risk stopping one page early.

    ``limit`` bounds *eligible* items returned, not rows inspected — the
    semantics every one of #1098/#1056/#1109/#1127 asks for explicitly.
    ``max_inspected`` is the separate, deliberate bound on total work one call
    may do; reaching it ends the scan with whatever eligible items were found
    so far.

    ``continuation`` is where the scan starts and where it records where to
    start next time: after the last row it inspected when it stopped at the
    limit or the ceiling, ``None`` when it walked off the end. Without one the
    scan starts from the top every call and remembers nothing, which is
    correct for a one-shot query and is the starvation-prone shape for a
    repeated tick over a store that can outgrow the ceiling.

    A failure raised by ``fetch_page`` itself — the underlying store/session —
    is never caught here: it is exactly the "infrastructure-wide" failure
    class recovery callers must let abort the tick (#1143), and it propagates
    unchanged, leaving the continuation where it was.
    """
    if limit <= 0 or max_inspected <= 0:
        return []
    start = continuation.resume_after if continuation is not None else None
    walk = await _walk(
        fetch_page,
        cursor_of,
        eligible,
        start=start,
        limit=limit,
        page_size=page_size,
        max_inspected=max_inspected,
    )
    if continuation is not None:
        continuation.resume_after = walk.resume_after
    return walk.items


async def _walk(
    fetch_page: Callable[[C | None, int], Awaitable[list[T]]],
    cursor_of: Callable[[T], C],
    eligible: Callable[[T], bool],
    *,
    start: C | None,
    limit: int,
    page_size: int,
    max_inspected: int,
) -> _Walk[T, C]:
    found: list[T] = []
    cursor = start
    inspected = 0
    while len(found) < limit and inspected < max_inspected:
        page = await fetch_page(cursor, min(page_size, max_inspected - inspected))
        if not page:
            # Walked off the end: the next tick starts from the top, so the
            # rows before `start` get their turn.
            return _Walk(found, None)
        for item in page:
            inspected += 1
            # Advanced per row, not per page: a stop at `limit` mid-page must
            # resume after the last row *inspected*, or the rest of that page
            # would be skipped on the next tick.
            cursor = cursor_of(item)
            if eligible(item):
                found.append(item)
                if len(found) >= limit:
                    return _Walk(found, cursor)
    return _Walk(found, cursor)


__all__ = ["DEFAULT_MAX_INSPECTED", "DEFAULT_PAGE_SIZE", "ScanContinuation", "fair_page_scan"]
