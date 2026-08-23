"""The durable quota and session stores run against migration 004 (#182).

`PgQuotaTracker` and `PgSessionStore` queried `quota_usage` and `sessions`, and
no revision created either — so both raised `UndefinedTableError` on their first
call against a migrated database. They are the intended durable owners per
ADR-082226-5104, and neither could start.

These tests exercise the **stores** against the **migration**, rather than
asserting the DDL twice. A test that re-states the schema and checks the
catalogue would have passed on the day this was broken: what was missing was not
a column, it was the table, and only a store actually running notices that.

Three properties are worth naming because a plausible schema gets them wrong:

- Quota accumulates. `record_usage` upserts with `ON CONFLICT (provider,
  cycle_key)`, which needs a matching key or the statement raises rather than
  adding to the running total.
- `sessions.timestamp` is populated by the server. No caller passes it, and both
  the read filter and the TTL purge depend on it.
- Two workers appending to one session cannot silently share a sequence number.
  `append_messages` derives `seq` with `MAX(seq) + 1` and then inserts; the
  composite primary key is what makes that race loud.

Skips without `MAISTRO_TEST_DATABASE_URL`; `MAISTRO_REQUIRE_PG_LEGS` turns the
skip into a failure where a server is guaranteed.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = os.environ.get("MAISTRO_TEST_DATABASE_URL", "")

#: A scratch database per run, so applying migrations cannot disturb whatever
#: else the configured one holds.
SCRATCH_DB = "maistro_migration_qs_test"


def _require_postgres() -> str:
    """The URL, or a skip — unless the caller declared a server is guaranteed."""
    if DATABASE_URL:
        return DATABASE_URL
    if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
        msg = (
            "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_DATABASE_URL is empty: "
            "the durable store legs cannot run and must not be silently skipped"
        )
        raise RuntimeError(msg)
    pytest.skip("MAISTRO_TEST_DATABASE_URL is unset; these stores need a real server")


def _alembic_env(url: str) -> dict[str, str]:
    """`DB_*` for alembic's `DatabaseSettings`, pointed at the scratch database."""
    parts = urlsplit(url)
    return {
        **os.environ,
        "DB_HOST": parts.hostname or "127.0.0.1",
        "DB_PORT": str(parts.port or 5432),
        "DB_NAME": SCRATCH_DB,
        "DB_USER": parts.username or "postgres",
        "DB_PASSWORD": parts.password or "",
    }


async def _recreate_scratch_database(url: str) -> None:
    """Drop and recreate the scratch database on a plain (non-pooled) connection.

    `CREATE DATABASE` cannot run inside a transaction block, which is why this
    uses a single connection to `postgres` rather than a pool.
    """
    import asyncpg

    admin = await asyncpg.connect(urlsplit(url)._replace(path="/postgres").geturl())
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}"')
        await admin.execute(f'CREATE DATABASE "{SCRATCH_DB}"')
    finally:
        await admin.close()


@pytest.fixture(scope="module")
def migrated_url() -> str:
    """A scratch database with revision 004 applied.

    `stamp 003` then upgrade rather than a full `upgrade head` from empty: 001
    needs the `vector` extension and this revision does not depend on anything
    001-003 create, so walking the whole chain would couple these tests to a
    pgvector image for no gain. #178 owns the chain-from-empty case.

    The upgrade targets `004_quota_sessions` by name rather than `head`, because
    stamping over a prefix and then asking for `head` is a claim about every
    future revision as well as this one. #122's 005 is the first to make that
    false: it `ALTER`s `learnings`, a table 001 creates and this fixture only
    ever stamped, so `head` walked into `UndefinedTable` on a revision these
    tests are not about. Naming the revision under test keeps this suite's
    failures its own.
    """
    url = _require_postgres()
    # asyncpg rather than psycopg2: asyncpg is a declared root dependency, and
    # psycopg2-binary is only present transitively here. Depending on a package
    # nothing declares is how a suite passes locally and dies in CI — the note
    # about `gherkin-official` in pyproject.toml records the same trap.
    asyncio.run(_recreate_scratch_database(url))

    env = _alembic_env(url)
    for args in (["stamp", "003"], ["upgrade", "004_quota_sessions"]):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if result.returncode != 0:
            # `check=True` raises a CalledProcessError that reports the exit
            # code and swallows the captured output, so the one thing worth
            # reading is the one thing you do not get. The first CI run of this
            # suite reported `returned non-zero exit status 1` ten times over
            # while alembic had been saying `ModuleNotFoundError: No module
            # named 'psycopg2'` all along — a round trip spent on a message
            # that was already in the buffer.
            msg = (
                f"alembic {' '.join(args)} failed with exit {result.returncode}\n"
                f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
            )
            raise AssertionError(msg)
    return urlsplit(url)._replace(path=f"/{SCRATCH_DB}").geturl()


@pytest.fixture
async def pool(migrated_url):
    import asyncpg

    pool = await asyncpg.create_pool(migrated_url, min_size=1, max_size=8)
    try:
        await pool.execute("TRUNCATE quota_usage, sessions")
        yield pool
    finally:
        await pool.close()


class TestQuotaTrackerRunsAgainstTheMigration:
    async def test_usage_accumulates_rather_than_raising(self, pool):
        """The headline: before this migration the first call raised
        `UndefinedTableError`. The upsert also needs `(provider, cycle_key)` to
        be a real key, or it raises for a second reason."""
        from maistro.persistence.pg_quota import PgQuotaTracker

        tracker = PgQuotaTracker(pool)
        await tracker.record_usage("anthropic", "2026-08", 100, 20)
        second = await tracker.record_usage("anthropic", "2026-08", 5, 1)

        assert second["input_tokens"] == 105
        assert second["output_tokens"] == 21
        assert second["total_tokens"] == 126
        assert second["request_count"] == 2

    async def test_providers_and_cycles_are_separate_rows(self, pool):
        from maistro.persistence.pg_quota import PgQuotaTracker

        tracker = PgQuotaTracker(pool)
        await tracker.record_usage("anthropic", "2026-08", 10, 1)
        await tracker.record_usage("anthropic", "2026-09", 20, 2)
        await tracker.record_usage("openai", "2026-08", 30, 3)

        assert len(await tracker.get_all_usage()) == 3

    async def test_the_cycle_key_is_normalised_before_it_reaches_the_key(self, pool):
        """`cycle_key` lowercases and strips. If that happened after the upsert
        rather than before, ` 2026-08 ` and `2026-08` would be two rows and the
        cycle's total would be split across them."""
        from maistro.persistence.pg_quota import PgQuotaTracker

        tracker = PgQuotaTracker(pool)
        await tracker.record_usage("anthropic", "2026-08", 10, 1)
        await tracker.record_usage("anthropic", "  2026-08  ", 10, 1)

        usage = await tracker.get_all_usage()
        assert len(usage) == 1
        assert usage[0]["total_tokens"] == 22


class TestSessionStoreRunsAgainstTheMigration:
    async def test_append_and_read_round_trip(self, pool):
        from maistro.persistence.pg_sessions import PgSessionStore

        store = PgSessionStore(pool)
        await store.append_messages(
            "s1", [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]
        )

        assert await store.get_history("s1") == [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]

    async def test_the_server_supplies_the_timestamp(self, pool):
        """No caller passes it, and both the read filter and the purge depend on
        it. A nullable column without a default would make every row invisible
        to `get_history` and immune to `purge_expired` — the store would look
        like it was losing writes."""
        from maistro.persistence.pg_sessions import PgSessionStore

        await PgSessionStore(pool).append_messages("s1", [{"role": "user", "content": "x"}])

        stamped = await pool.fetchval("SELECT timestamp FROM sessions WHERE session_id = 's1'")
        assert stamped is not None

    async def test_history_is_ordered_and_capped(self, pool):
        from maistro.persistence.pg_sessions import PgSessionStore

        store = PgSessionStore(pool, max_messages=3)
        await store.append_messages(
            "s1", [{"role": "user", "content": str(index)} for index in range(6)]
        )

        assert [m["content"] for m in await store.get_history("s1")] == ["3", "4", "5"]

    async def test_purge_expired_deletes_rather_than_hiding(self, pool):
        """TTL used to be a read-time filter only, so expired conversation
        content was invisible but retained indefinitely. The purge has to
        actually delete, which needs `timestamp` to be a real stored column."""
        from maistro.persistence.pg_sessions import PgSessionStore

        store = PgSessionStore(pool)
        await store.append_messages("s1", [{"role": "user", "content": "old"}])
        assert await pool.fetchval("SELECT count(*) FROM sessions") == 1

        assert await store.purge_expired(ttl_seconds=-1) == 1
        assert await pool.fetchval("SELECT count(*) FROM sessions") == 0

    async def test_appending_purges_inline(self, pool):
        """`append_messages` runs the purge itself — there is no scheduled
        sweeper to defer to. Asserted separately because it is why the previous
        test cannot use an already-expired TTL to set up: the append would have
        cleaned up after itself before `purge_expired` ever ran."""
        from maistro.persistence.pg_sessions import PgSessionStore

        store = PgSessionStore(pool, ttl_seconds=-1)
        await store.append_messages("s1", [{"role": "user", "content": "old"}])

        assert await pool.fetchval("SELECT count(*) FROM sessions") == 0

    async def test_deleting_a_session_leaves_the_others(self, pool):
        from maistro.persistence.pg_sessions import PgSessionStore

        store = PgSessionStore(pool)
        await store.append_messages("s1", [{"role": "user", "content": "a"}])
        await store.append_messages("s2", [{"role": "user", "content": "b"}])
        await store.delete_session("s1")

        assert await store.get_history("s1") == []
        assert len(await store.get_history("s2")) == 1


class TestTheSequenceRaceIsLoud:
    """`append_messages` derives `seq` from `MAX(seq) + 1` and then inserts — a
    read-then-write with a window in it. The schema decides what that costs.

    Not fixed here, deliberately: fixing it means changing how the store
    allocates sequences, which is the store's change and not the migration's.
    What the migration owes is that the race cannot be silent, and that is what
    this asserts. Recorded in #182 rather than left for a deployment to find.
    """

    async def test_concurrent_appends_cannot_share_a_sequence_number(self, pool):
        from maistro.persistence.pg_sessions import PgSessionStore

        store = PgSessionStore(pool)
        results = await asyncio.gather(
            *(store.append_messages("s1", [{"role": "user", "content": str(i)}]) for i in range(8)),
            return_exceptions=True,
        )

        # Either every append landed, or the losers raised. What must not happen
        # is two rows at one sequence number, which a table without the
        # composite key would have allowed.
        rows = await pool.fetch("SELECT seq FROM sessions WHERE session_id = 's1'")
        sequences = [r["seq"] for r in rows]
        assert len(sequences) == len(set(sequences)), f"duplicate sequence numbers: {sequences}"
        assert any(isinstance(r, Exception) for r in results) or len(sequences) == 8
