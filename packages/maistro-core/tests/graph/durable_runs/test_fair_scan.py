"""Unit tests for the bounded, cursor-fair page-walking combinator.

`fair_page_scan` is the one fix shared by #1098/#1056/#1109/#1127/#1143: these
tests exercise it directly, independent of any store, so the paging/bound/
propagation contract is pinned once rather than re-derived per call site.
"""

from __future__ import annotations

import pytest

from maistro.graph.durable_runs.fair_scan import fair_page_scan

pytestmark = [pytest.mark.contract("behavioral")]


def _int_store(values: list[int], *, page_size_cap: int | None = None):
    """A fake keyset-paginated store over plain ints, cursor == the int itself."""
    calls: list[tuple[int | None, int]] = []

    async def fetch_page(cursor: int | None, page_size: int) -> list[int]:
        calls.append((cursor, page_size))
        if page_size_cap is not None:
            page_size = min(page_size, page_size_cap)
        start = (
            0
            if cursor is None
            else next((i for i, v in enumerate(values) if v > cursor), len(values))
        )
        return values[start : start + page_size]

    return fetch_page, calls


async def test_finds_eligible_items_past_a_long_ineligible_prefix() -> None:
    """The core fix: eligibility filtered after a fixed-size query would have
    missed this; paging with an advancing cursor cannot."""
    values = list(range(250))  # 0..249, all ineligible except 249
    fetch_page, calls = _int_store(values, page_size_cap=50)

    found = await fair_page_scan(
        fetch_page=fetch_page,
        cursor_of=lambda item: item,
        eligible=lambda item: item == 249,
        limit=1,
        page_size=50,
    )

    assert found == [249]
    # More than one page was required: the prefix (249 items) exceeds one
    # 50-item page, so this proves cursor advancement, not just a big page.
    assert len(calls) > 1


async def test_stops_once_limit_eligible_items_are_found() -> None:
    values = list(range(20))
    fetch_page, calls = _int_store(values)

    found = await fair_page_scan(
        fetch_page=fetch_page,
        cursor_of=lambda item: item,
        eligible=lambda item: item % 2 == 0,
        limit=3,
        page_size=100,
    )

    assert found == [0, 2, 4]
    assert len(calls) == 1  # one page (size 100) already covers all 20 rows


async def test_empty_page_ends_the_scan() -> None:
    fetch_page, _calls = _int_store([])

    found = await fair_page_scan(
        fetch_page=fetch_page,
        cursor_of=lambda item: item,
        eligible=lambda item: True,
        limit=5,
    )

    assert found == []


async def test_a_short_but_nonempty_page_does_not_end_the_scan() -> None:
    """A page shorter than requested must not be treated as "no more data":
    CanonicalDurableRunStore.list_due can legitimately return a short page
    after re-checking freshness, without that meaning the walk is done."""
    # Requested page_size is 5, but each fetch returns only 2 rows -- fewer
    # than requested, yet real data remains beyond it.
    pages = [[1, 2], [3, 4], [5]]
    calls: list[int | None] = []

    async def fetch_page(cursor, page_size):
        calls.append(cursor)
        index = len(calls) - 1
        return pages[index] if index < len(pages) else []

    found = await fair_page_scan(
        fetch_page=fetch_page,
        cursor_of=lambda item: item,
        eligible=lambda item: True,
        limit=5,
        page_size=5,
    )

    assert found == [1, 2, 3, 4, 5]
    assert len(calls) == 3  # each short page still triggered the next fetch


async def test_max_inspected_bounds_one_call_even_with_nothing_eligible() -> None:
    """An arbitrarily large run of ineligible rows cannot turn one call into
    an unbounded scan (#1056's stop condition)."""
    values = list(range(10_000))
    fetch_page, calls = _int_store(values)

    found = await fair_page_scan(
        fetch_page=fetch_page,
        cursor_of=lambda item: item,
        eligible=lambda _item: False,
        limit=1,
        page_size=100,
        max_inspected=250,
    )

    assert found == []
    total_inspected = sum(min(page_size, 250) for _cursor, page_size in calls)
    assert total_inspected <= 250


async def test_cursor_advances_across_calls_are_not_required_for_one_scan_to_finish() -> None:
    """No cursor is retained between separate `fair_page_scan` calls: durable
    eligibility, not scan memory, is the source of truth after a restart."""
    values = [1, 2, 3]
    fetch_page, calls = _int_store(values)

    first = await fair_page_scan(
        fetch_page=fetch_page, cursor_of=lambda item: item, eligible=lambda item: item == 3, limit=1
    )
    second = await fair_page_scan(
        fetch_page=fetch_page, cursor_of=lambda item: item, eligible=lambda item: item == 3, limit=1
    )

    assert first == [3]
    assert second == [3]
    # Both calls started from cursor=None -- no state carried between them.
    assert calls[0][0] is None
    assert calls[len(calls) // 2][0] is None


async def test_a_non_positive_limit_is_a_noop_and_never_fetches() -> None:
    async def fetch_page(_cursor, _page_size):
        raise AssertionError("must not be called for a non-positive limit")

    assert (
        await fair_page_scan(
            fetch_page=fetch_page, cursor_of=lambda item: item, eligible=lambda _item: True, limit=0
        )
        == []
    )


async def test_a_failure_fetching_a_page_propagates_uncaught() -> None:
    """The infrastructure-wide failure class #1143 requires recovery callers
    to let abort the tick: a failure from the store/session itself, not from
    one candidate's own processing."""

    async def fetch_page(_cursor, _page_size):
        raise ConnectionError("database connection lost")

    with pytest.raises(ConnectionError, match="database connection lost"):
        await fair_page_scan(
            fetch_page=fetch_page, cursor_of=lambda item: item, eligible=lambda _item: True, limit=1
        )
