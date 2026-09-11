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
single fixed-size page after the fact. A poisoned or foreign prefix of any
size can no longer hide eligible work — the walk pages past it in the same
call, bounded by ``max_inspected`` so one pathological prefix cannot turn a
tick into an unbounded table scan (the stop condition every one of those
issues states explicitly).

This module owns no lifecycle, no recovery policy, and no store. It is a pure
combinator over whatever page-fetch closure and eligibility predicate the
caller supplies.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")
C = TypeVar("C")

#: Default ceiling on rows *inspected* by one bounded scan call, independent
#: of how many turn out eligible. Keeps one starvation-prone prefix from
#: turning a single tick into an unbounded walk; the next tick still makes
#: progress because eligibility is re-derived from durable facts on every
#: call, not from anything this scan remembers between calls.
DEFAULT_MAX_INSPECTED = 2000

#: Default page size requested from the underlying store on each fetch.
DEFAULT_PAGE_SIZE = 100


async def fair_page_scan(
    *,
    fetch_page: Callable[[C | None, int], Awaitable[list[T]]],
    cursor_of: Callable[[T], C],
    eligible: Callable[[T], bool],
    limit: int,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_inspected: int = DEFAULT_MAX_INSPECTED,
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
    so far, and the next call starts over from the beginning since no cursor
    is retained across calls (durable eligibility, not scan memory, is what
    every acceptance criterion here requires to survive a restart).

    A failure raised by ``fetch_page`` itself — the underlying store/session —
    is never caught here: it is exactly the "infrastructure-wide" failure
    class recovery callers must let abort the tick (#1143), and it propagates
    unchanged.
    """
    if limit <= 0 or max_inspected <= 0:
        return []
    found: list[T] = []
    cursor: C | None = None
    inspected = 0
    while len(found) < limit and inspected < max_inspected:
        effective_page_size = min(page_size, max_inspected - inspected)
        page = await fetch_page(cursor, effective_page_size)
        if not page:
            break
        for item in page:
            inspected += 1
            if eligible(item):
                found.append(item)
                if len(found) >= limit:
                    break
        cursor = cursor_of(page[-1])
    return found


__all__ = ["DEFAULT_MAX_INSPECTED", "DEFAULT_PAGE_SIZE", "fair_page_scan"]
