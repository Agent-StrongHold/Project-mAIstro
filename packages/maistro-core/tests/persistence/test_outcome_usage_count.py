"""The reporting-call count survives the round trip on both backends (#717).

A column added to one store and forgotten in the other is the failure #696 was
filed for, on this exact table. So both legs are one parametrized suite rather
than two files, and the PostgreSQL leg runs against a real migrated database:
what has to hold is that migration 025 added the column and that an `INTEGER`
column accepts `None` -- neither of which a mocked connection asserting on the
SQL string can show.

The distinction under test is `None` versus `0`, and it survives only if every
layer preserves it: the INSERT must bind NULL rather than coalesce, and the
read-back must not default a missing key to zero.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from maistro.types.memory import Outcome

from .conftest import postgres_dsn

pytestmark = [pytest.mark.contract("behavioral")]


class _SqliteLeg:
    name = "sqlite"

    def __init__(self, store: Any) -> None:
        self.store = store

    async def written_column(self, outcome_id: int) -> Any:
        """The stored value, read outside the mapper.

        Read raw as well as through `list_outcomes` because the mapper is the
        layer most able to hide a NULL: `r.get(..., 0)` would make an unwritten
        column read back as a measured zero, and only the raw read can tell
        that apart.
        """
        cursor = await self.store._conn.execute(
            "SELECT usage_reported_calls FROM outcomes WHERE id = ?", (outcome_id,)
        )
        row = await cursor.fetchone()
        return row[0]


class _PostgresLeg:
    name = "postgres"

    def __init__(self, store: Any, pool: Any) -> None:
        self.store = store
        self._pool = pool

    async def written_column(self, outcome_id: int) -> Any:
        async with self._pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT usage_reported_calls FROM outcomes WHERE id = $1", outcome_id
            )


@pytest.fixture(params=["sqlite", "postgres"])
async def leg(request: Any, pg_pool: Any) -> AsyncIterator[Any]:
    if request.param == "sqlite":
        aiosqlite = pytest.importorskip("aiosqlite")
        from maistro.persistence.sqlite_outcomes import SqliteOutcomeStore

        conn = await aiosqlite.connect(":memory:")
        store = SqliteOutcomeStore(conn)
        await store.ensure_schema()
        try:
            yield _SqliteLeg(store)
        finally:
            await conn.close()
        return

    if pg_pool is None:
        pytest.skip("set MAISTRO_TEST_PG_DSN to a migrated PostgreSQL database")
    from maistro.persistence.pg_outcomes import PgOutcomeStore

    yield _PostgresLeg(PgOutcomeStore(pg_pool), pg_pool)


def _outcome(**kwargs: Any) -> Outcome:
    fields: dict[str, Any] = {
        "request_id": "r-1",
        "task_type": "chat",
        "model_used": "m",
        "provider": "p",
        "user_id": "u-1",
    }
    fields.update(kwargs)
    return Outcome(**fields)


class TestTheCountSurvivesTheRoundTrip:
    @pytest.mark.ac("SPEC-083026-6cef/AC-6")
    async def test_a_counted_turn_comes_back_with_its_count(self, leg: Any) -> None:
        oid = await leg.store.record(
            _outcome(input_tokens=15, output_tokens=3, usage_reported_calls=2)
        )

        assert await leg.written_column(oid) == 2
        [stored] = [o for o in await leg.store.list_outcomes() if o.id == oid]
        assert stored.usage_reported_calls == 2

    @pytest.mark.ac("SPEC-083026-6cef/AC-6")
    async def test_a_turn_nothing_counted_comes_back_absent_not_zero(self, leg: Any) -> None:
        """`0` would claim the writer counted and found none. The whole point
        of the column is that those are different, so a NULL that reads back as
        `0` gives the column back its old ambiguity."""
        oid = await leg.store.record(_outcome())

        assert await leg.written_column(oid) is None
        [stored] = [o for o in await leg.store.list_outcomes() if o.id == oid]
        assert stored.usage_reported_calls is None

    @pytest.mark.ac("SPEC-083026-6cef/AC-6")
    async def test_a_counted_zero_is_not_the_same_row_as_an_uncounted_one(self, leg: Any) -> None:
        counted = await leg.store.record(_outcome(request_id="counted", usage_reported_calls=0))
        uncounted = await leg.store.record(_outcome(request_id="uncounted"))

        assert await leg.written_column(counted) == 0
        assert await leg.written_column(uncounted) is None

    async def test_the_stored_tokens_are_unchanged_by_the_new_column(self, leg: Any) -> None:
        """A regression guard on the placeholder numbering: an INSERT whose
        column list and value tuple drift apart writes every field into the
        wrong column, and the count is the last of twenty-five."""
        oid = await leg.store.record(
            _outcome(input_tokens=11, output_tokens=7, usage_reported_calls=1)
        )

        [stored] = [o for o in await leg.store.list_outcomes() if o.id == oid]
        assert (stored.input_tokens, stored.output_tokens) == (11, 7)
        assert stored.request_id == "r-1"


class TestARowPredatingTheColumn:
    @pytest.mark.ac("SPEC-083026-6cef/AC-6")
    def test_a_row_with_no_such_key_maps_to_none(self) -> None:
        """A read from a database migrated before 025 has no such key at all,
        which is a different shape from a NULL and reaches the same mapper."""
        from maistro.persistence.pg_outcomes import _row_to_outcome as pg_map
        from maistro.persistence.sqlite_outcomes import _row_to_outcome as sqlite_map

        row = {
            "id": 1,
            "request_id": "r-1",
            "success": True,
            "created_at": "2026-08-30T00:00:00+00:00",
        }
        assert sqlite_map(dict(row)).usage_reported_calls is None
        assert pg_map({**row, "created_at": None}).usage_reported_calls is None


class TestTheMigrationIsRegistered:
    @pytest.mark.ac("SPEC-083026-6cef/AC-6")
    def test_the_postgres_leg_is_not_silently_skipped_when_it_is_required(self) -> None:
        """CI sets `MAISTRO_TEST_PG_DSN`. If it ever stops doing so, the
        PostgreSQL leg skips and this suite proves half of what it claims -- the
        half that is not the one with a migration behind it."""
        import os

        if os.environ.get("MAISTRO_REQUIRE_PG_LEGS") and not postgres_dsn():
            pytest.fail(
                "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_PG_DSN is empty: "
                "the PostgreSQL round-trip leg cannot run and must not be silently skipped"
            )
