"""Unit tests for the bounded, cursor-fair page-walking combinator.

`fair_page_scan` is the one fix shared by #1098/#1056/#1109/#1127/#1143: these
tests exercise it directly, independent of any store, so the paging/bound/
propagation contract is pinned once rather than re-derived per call site.
"""

from __future__ import annotations

import pytest

from maistro.graph.durable_runs.fair_scan import (
    DEFAULT_MAX_INSPECTED,
    ScanContinuation,
    ScanPage,
    fair_page_scan,
)

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


class TestAContinuationCrossesAPrefixLongerThanTheBound:
    """The review finding on the first cut: a bounded scan that restarts from
    the top every tick is the starvation defect one size up. With ordered
    rows 0..2000, only row 2000 eligible, `limit=1` and the default 2,000-row
    ceiling, three successive calls returned `[[], [], []]` — each restarted
    at `None` and fetched the identical twenty pages. A continuation held
    across ticks is what turns the ceiling into a pace.
    """

    async def test_a_row_behind_the_ceiling_is_reached_on_the_next_tick(self) -> None:
        values = list(range(DEFAULT_MAX_INSPECTED + 1))  # 0..2000
        fetch_page, calls = _int_store(values)
        scan: ScanContinuation[int] = ScanContinuation()

        def _tick():
            return fair_page_scan(
                fetch_page=fetch_page,
                cursor_of=lambda item: item,
                eligible=lambda item: item == DEFAULT_MAX_INSPECTED,
                limit=1,
                continuation=scan,
            )

        first = await _tick()
        assert first == []
        assert scan.resume_after == DEFAULT_MAX_INSPECTED - 1, (
            "the tick stopped at the ceiling and must resume after the last row it inspected"
        )
        resumed_from = len(calls)

        second = await _tick()

        assert second == [DEFAULT_MAX_INSPECTED]
        assert calls[resumed_from][0] == DEFAULT_MAX_INSPECTED - 1, (
            "the second tick must start where the first stopped, not at the top"
        )

    async def test_the_control_row_just_inside_the_ceiling_is_reached_in_one_tick(self) -> None:
        values = list(range(DEFAULT_MAX_INSPECTED + 1))
        fetch_page, _calls = _int_store(values)
        scan: ScanContinuation[int] = ScanContinuation()

        found = await fair_page_scan(
            fetch_page=fetch_page,
            cursor_of=lambda item: item,
            eligible=lambda item: item == DEFAULT_MAX_INSPECTED - 1,
            limit=1,
            continuation=scan,
        )

        assert found == [DEFAULT_MAX_INSPECTED - 1]

    async def test_a_stop_at_the_limit_resumes_after_the_last_inspected_row_not_the_page(
        self,
    ) -> None:
        """Resuming after the *page* would skip the rest of the page the limit
        was reached in — a second starvation, page-sized. The cursor advances
        per row."""
        values = list(range(10))
        fetch_page, calls = _int_store(values)
        scan: ScanContinuation[int] = ScanContinuation()

        first = await fair_page_scan(
            fetch_page=fetch_page,
            cursor_of=lambda item: item,
            eligible=lambda item: item % 2 == 0,
            limit=1,
            page_size=10,
            continuation=scan,
        )
        second = await fair_page_scan(
            fetch_page=fetch_page,
            cursor_of=lambda item: item,
            eligible=lambda item: item % 2 == 0,
            limit=1,
            page_size=10,
            continuation=scan,
        )

        assert (first, second) == ([0], [2])
        assert calls[1][0] == 0

    async def test_walking_off_the_end_restarts_from_the_top(self) -> None:
        """The one restart the scan performs itself: once it has seen the end
        of the store, the rows before this tick's starting point are owed a
        turn, so the next tick starts at the top."""
        values = [1, 2, 3, 4]
        fetch_page, calls = _int_store(values)
        scan: ScanContinuation[int] = ScanContinuation(resume_after=2)

        found = await fair_page_scan(
            fetch_page=fetch_page,
            cursor_of=lambda item: item,
            eligible=lambda item: item == 1,
            limit=1,
            continuation=scan,
        )

        assert found == []
        assert scan.resume_after is None
        assert calls[0][0] == 2

        again = await fair_page_scan(
            fetch_page=fetch_page,
            cursor_of=lambda item: item,
            eligible=lambda item: item == 1,
            limit=1,
            continuation=scan,
        )

        assert again == [1]

    async def test_a_position_past_the_end_costs_one_empty_tick_then_restarts(self) -> None:
        """A stale position — the store shrank, or the ordering moved — is
        harmless: keyset paging reads strictly after it, finds nothing, and the
        scan resets itself."""
        values = [1, 2, 3]
        fetch_page, _calls = _int_store(values)
        scan: ScanContinuation[int] = ScanContinuation(resume_after=999)

        assert (
            await fair_page_scan(
                fetch_page=fetch_page,
                cursor_of=lambda item: item,
                eligible=lambda item: True,
                limit=1,
                continuation=scan,
            )
            == []
        )
        assert scan.resume_after is None

    async def test_a_fetch_failure_leaves_the_continuation_where_it_was(self) -> None:
        """The tick aborts (#1143's infrastructure-wide class); the position
        it had reached before the failure is still the right place to resume."""
        scan: ScanContinuation[int] = ScanContinuation(resume_after=7)

        async def fetch_page(_cursor, _page_size):
            raise ConnectionError("database connection lost")

        with pytest.raises(ConnectionError):
            await fair_page_scan(
                fetch_page=fetch_page,
                cursor_of=lambda item: item,
                eligible=lambda _item: True,
                limit=1,
                continuation=scan,
            )

        assert scan.resume_after == 7


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


class TestAPageThatFiltersItsOwnRows:
    """A fetcher that drops rows reports progress separately from results.

    `CanonicalDurableRunStore.list_due` reads a page of due-index ids and then
    removes the ones whose canonical Run has gone terminal. A page of stale
    ids therefore comes back empty while having moved through the index, and
    an empty list is also what the end of the index looks like. Read as the
    same thing, the walk resets to the top on every tick and never gets past
    a stale prefix longer than one page.
    """

    async def test_an_empty_page_that_moved_does_not_end_the_walk(self) -> None:
        """The review's repro: 100 stale rows ahead of one live row."""
        pages: list[tuple[int | None, int]] = []

        async def fetch_page(cursor, page_size):
            pages.append((cursor, page_size))
            if cursor is None:
                # Every id on this page assembled into a terminal Run.
                return ScanPage(items=[], resume_after=100, inspected=100)
            return ScanPage(items=[101], resume_after=101, inspected=1)

        scan: ScanContinuation[int] = ScanContinuation()
        found = await fair_page_scan(
            fetch_page=fetch_page,
            cursor_of=lambda item: item,
            eligible=lambda _item: True,
            limit=1,
            continuation=scan,
        )

        assert found == [101]
        assert [cursor for cursor, _size in pages] == [None, 100]
        assert scan.resume_after == 101

    async def test_the_inspection_ceiling_still_counts_dropped_rows(self) -> None:
        """A dropped row is work done. Counting only yielded rows would let
        one tick walk an unbounded number of stale rows."""
        fetched = 0

        async def fetch_page(cursor, page_size):
            nonlocal fetched
            fetched += 1
            start = 0 if cursor is None else cursor
            return ScanPage(items=[], resume_after=start + page_size, inspected=page_size)

        scan: ScanContinuation[int] = ScanContinuation()
        assert (
            await fair_page_scan(
                fetch_page=fetch_page,
                cursor_of=lambda item: item,
                eligible=lambda _item: True,
                limit=1,
                page_size=100,
                max_inspected=250,
                continuation=scan,
            )
            == []
        )

        assert fetched == 3
        assert scan.resume_after == 250

    async def test_an_exhausted_page_restarts_from_the_top(self) -> None:
        """Only the index actually ending means start over next tick."""
        scan: ScanContinuation[int] = ScanContinuation(resume_after=40)

        async def fetch_page(_cursor, _page_size):
            return ScanPage(items=[], resume_after=55, inspected=15, exhausted=True)

        assert (
            await fair_page_scan(
                fetch_page=fetch_page,
                cursor_of=lambda item: item,
                eligible=lambda _item: True,
                limit=1,
                continuation=scan,
            )
            == []
        )
        assert scan.resume_after is None

    async def test_a_page_that_yields_but_cannot_place_itself_still_ends(self) -> None:
        """A fetcher that yields nothing and reports no position cannot be
        paged past; ending the walk restarts from the top rather than spinning
        on the same cursor."""
        calls = 0

        async def fetch_page(_cursor, _page_size):
            nonlocal calls
            calls += 1
            return ScanPage(items=[], resume_after=None, inspected=3)

        scan: ScanContinuation[int] = ScanContinuation(resume_after=9)
        assert (
            await fair_page_scan(
                fetch_page=fetch_page,
                cursor_of=lambda item: item,
                eligible=lambda _item: True,
                limit=1,
                continuation=scan,
            )
            == []
        )
        assert calls == 1
        assert scan.resume_after is None

    async def test_a_page_position_past_its_last_kept_row_is_taken(self) -> None:
        """Rows dropped *after* the last one kept are still paged past."""
        seen: list[int | None] = []

        async def fetch_page(cursor, _page_size):
            seen.append(cursor)
            if cursor is None:
                return ScanPage(items=[3], resume_after=50, inspected=50)
            return ScanPage(items=[], resume_after=None, inspected=0, exhausted=True)

        scan: ScanContinuation[int] = ScanContinuation()
        assert await fair_page_scan(
            fetch_page=fetch_page,
            cursor_of=lambda item: item,
            eligible=lambda _item: True,
            limit=2,
            continuation=scan,
        ) == [3]
        assert seen == [None, 50]
