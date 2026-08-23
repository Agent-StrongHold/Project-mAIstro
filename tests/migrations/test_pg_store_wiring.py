"""A `postgresql://` URL wires stores that actually work (#122).

`maistro.container` had no PostgreSQL branch: a deployment configured with
`DATABASE_URL=postgresql://…` took the `else` and got in-memory stores, so
learnings, outcomes, sessions and quota vanished on restart with nothing in the
log saying the configured database had been ignored. PostgreSQL is the durable
system of record per ADR-082226-5104, which makes that the canonical store being
silently skipped rather than an unwired optional backend.

**Why these tests run the real thing.** The stores had never executed against a
migrated database, so nothing had ever checked that their SQL and the schema
agree — and they did not. Running against live PostgreSQL 18.6 with 001-004
applied produced `UndefinedColumnError` on `learnings.store` and on
`outcomes.record`, plus four defects no schema assertion would have found: three
NOT NULL columns omitted from a raw INSERT (migration 001 declares them with
SQLAlchemy's `default=`, which the ORM applies in Python and which emits no
DEFAULT clause), a `str(list)` where a JSONB column wanted JSON, and a
`trigger_keys` round trip that returned raw JSON text to `list(...)` and so came
back as individual characters.

A test that re-asserted the DDL would have passed on the day every one of those
was broken. Only a store actually running notices.

The `assert_never_wires_in_memory` test is the regression guard for the original
bug, and it is deliberately an identity check rather than a "does it work"
check: an in-memory store *works*: it accepts every write and answers every
read. What it does not do is survive a restart, and no functional assertion can
tell the difference inside one process.

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

from maistro.types.config import AgentConfig
from maistro.types.errors import ConfigError
from maistro.types.memory import Learning, Outcome

REPO_ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = os.environ.get("MAISTRO_TEST_DATABASE_URL", "")

#: A scratch database per run, so applying migrations cannot disturb whatever
#: else the configured one holds.
SCRATCH_DB = "maistro_pg_wiring_test"


def _require_postgres() -> str:
    """The URL, or a skip — unless the caller declared a server is guaranteed."""
    if DATABASE_URL:
        return DATABASE_URL
    if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
        msg = (
            "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_DATABASE_URL is empty: "
            "the PostgreSQL wiring legs cannot run and must not be silently skipped"
        )
        raise RuntimeError(msg)
    pytest.skip("MAISTRO_TEST_DATABASE_URL is unset; this wiring needs a real server")


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
    """A scratch database with the whole chain applied, from empty.

    The full `upgrade head` rather than a stamp-and-step: `learnings` and
    `outcomes` are created by 001, so these tests genuinely depend on the chain
    running end to end — which also means they need the `vector` extension, and
    so the `pgvector/pgvector:pg17` image rather than plain `postgres:17`.
    """
    url = _require_postgres()
    asyncio.run(_recreate_scratch_database(url))

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        env=_alembic_env(url),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if result.returncode != 0:
        # `check=True` would raise a CalledProcessError reporting the exit code
        # and swallowing the captured output — the one thing worth reading.
        msg = (
            f"alembic upgrade head failed with exit {result.returncode}\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )
        raise AssertionError(msg)
    return urlsplit(url)._replace(path=f"/{SCRATCH_DB}").geturl()


@pytest.fixture
async def container(migrated_url):
    """A container wired from a `postgresql://` URL, torn down with its pool."""
    from maistro.container import create_container

    wired = await create_container(
        AgentConfig(router_api_key="test-key", database_url=migrated_url)
    )
    try:
        await wired.db_pool.execute("TRUNCATE learnings, outcomes, sessions, quota_usage")
        yield wired
    finally:
        await wired.db_pool.close()


class TestContainerSelectsPostgres:
    """The `else` branch that discarded the configured database is gone."""

    async def test_a_postgresql_url_never_wires_in_memory(self, container) -> None:
        wired = {
            "learning_store": type(container.learning_store).__name__,
            "outcome_store": type(container.outcome_store).__name__,
            "session_store": type(container.session_store).__name__,
            "quota_tracker": type(container.quota_tracker).__name__,
        }
        assert wired == {
            "learning_store": "PgLearningStore",
            "outcome_store": "PgOutcomeStore",
            "session_store": "PgSessionStore",
            "quota_tracker": "PgQuotaTracker",
        }

    @pytest.mark.parametrize("scheme", ["postgresql", "postgres", "postgresql+asyncpg"])
    async def test_every_accepted_spelling_reaches_the_same_backend(
        self, migrated_url, scheme
    ) -> None:
        """`postgres://` is what several hosted providers hand out, and
        `postgresql+asyncpg://` is the SQLAlchemy spelling an operator may
        already have set for alembic. Rejecting either would fail a deployment
        that is correctly configured, and asyncpg's own parser accepts only the
        first two — so the suffix has to be stripped rather than passed through.
        """
        from maistro.container import create_container

        url = migrated_url.replace("postgresql://", f"{scheme}://", 1)
        wired = await create_container(AgentConfig(router_api_key="test-key", database_url=url))
        try:
            assert type(wired.learning_store).__name__ == "PgLearningStore"
        finally:
            await wired.db_pool.close()

    async def test_an_unreachable_server_fails_without_leaking_the_password(
        self,
    ) -> None:
        """A refused connection is a startup failure, not a reason to fall back.

        The redaction is the second half and the reason `_redact_url` exists: a
        PostgreSQL DSN carries `user:password@` as a matter of course, and this
        error lands in an uncaught startup traceback — process logs and whatever
        collects them.
        """
        from maistro.container import create_container

        _require_postgres()
        with pytest.raises(ConfigError) as caught:
            await create_container(
                AgentConfig(
                    router_api_key="test-key",
                    database_url="postgresql://alice:hunter2@127.0.0.1:1/nope",
                )
            )
        message = str(caught.value)
        assert "hunter2" not in message
        assert "alice" not in message
        assert "127.0.0.1" in message


class TestStoresRunAgainstTheMigratedSchema:
    """Every defect below raised or corrupted against 001-004 as shipped."""

    async def test_a_learning_survives_the_round_trip_intact(self, container) -> None:
        stored = Learning(
            category="tool",
            trigger_keys=["timeout", "retry"],
            learning="raise the read deadline",
            tool_name="http_get",
            source_query="why did it time out",
            org_id="org-1",
            team_id="team-1",
            agent_id="agent-1",
            user_id="user-1",
            hit_count=3,
            rca_category="latency",
            rca_prevention="cache the response",
            success_after_use=2,
            failure_after_use=1,
        )
        assert await container.learning_store.store(stored) > 0

        found = await container.learning_store.find_relevant("timeout", org_id="org-1")
        assert len(found) == 1
        got = found[0]
        # Named field by field rather than compared as a whole: `id` is assigned
        # by the database, and a bare dataclass comparison would hide which of
        # these was the one that did not come back.
        assert got.trigger_keys == ["timeout", "retry"]
        assert got.source_query == "why did it time out"
        assert got.team_id == "team-1"
        assert got.hit_count == 3
        assert got.rca_category == "latency"
        assert got.rca_prevention == "cache the response"
        assert (got.success_after_use, got.failure_after_use) == (2, 1)

    async def test_trigger_keys_come_back_as_keys_and_not_as_characters(self, container) -> None:
        """The corruption this guards was silent, and it fed the dedup key.

        asyncpg's JSONB codec is text in both directions, so `list(row[...])`
        split the stored JSON into single characters. `store` scores overlap on
        exactly this set, which meant two unrelated learnings sharing the letter
        `t` counted as overlapping.
        """
        await container.learning_store.store(
            Learning(trigger_keys=["timeout"], tool_name="http_get", org_id="o")
        )
        found = await container.learning_store.find_relevant("timeout", org_id="o")
        assert found[0].trigger_keys == ["timeout"]
        assert "t" not in found[0].trigger_keys

    async def test_an_outcome_carrying_a_tool_call_records(self, container) -> None:
        """`str([{"a": 1}])` is `"[{'a': 1}]"` — single quotes, not JSON.

        Only the empty-list case, whose repr happens to be valid JSON, ever
        parsed, so every outcome that recorded an actual tool call failed while
        the trivial one passed.
        """
        recorded = await container.outcome_store.record(
            Outcome(
                request_id="req-1",
                task_type="code",
                model_used="m",
                provider="p",
                tool_calls=[{"name": "grep", "args": {"pattern": "x"}}],
                success=False,
                error_type="boom",
                org_id="org-1",
                team_id="team-1",
                user_id="user-1",
                agent_id="agent-1",
                input_tokens=3,
                output_tokens=4,
                charged_microchips=99,
                pricing_version="v2",
            )
        )
        assert recorded > 0
        row = await container.db_pool.fetchrow(
            "SELECT org_id, tool_calls, charged_microchips, pricing_version "
            "FROM outcomes WHERE request_id = 'req-1'"
        )
        # `org_id` read back from the row rather than from the store: it was
        # omitted from the INSERT entirely, and it is what `ix_outcomes_org_task`
        # and every by-org rollup key on.
        assert row["org_id"] == "org-1"
        assert row["charged_microchips"] == 99
        assert row["pricing_version"] == "v2"

    async def test_session_history_round_trips(self, container) -> None:
        await container.session_store.append_messages(
            "session-1", [{"role": "user", "content": "hello"}]
        )
        assert await container.session_store.get_history("session-1") == [
            {"role": "user", "content": "hello"}
        ]

    async def test_quota_accumulates_across_calls(self, container) -> None:
        await container.quota_tracker.record_usage("openai", "2026-08", 10, 5)
        totals = await container.quota_tracker.record_usage("openai", "2026-08", 1, 2)
        assert totals["total_tokens"] == 18
        assert totals["request_count"] == 2


class TestUnmigratedDatabaseFailsLoudly:
    """Schema ownership stays with alembic, and its absence is not papered over."""

    async def test_a_database_with_no_tables_names_the_missing_one(self, migrated_url) -> None:
        """The container issues no CREATE TABLE, so an operator who skipped
        `alembic upgrade head` gets `UndefinedTableError: relation "learnings"
        does not exist` — loud, specific, and not a database this container
        invented in place of the one the migrations describe.
        """
        import asyncpg

        from maistro.container import create_container

        bare = "maistro_pg_wiring_bare"
        admin = await asyncpg.connect(urlsplit(migrated_url)._replace(path="/postgres").geturl())
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{bare}"')
            await admin.execute(f'CREATE DATABASE "{bare}"')
        finally:
            await admin.close()

        url = urlsplit(migrated_url)._replace(path=f"/{bare}").geturl()
        with pytest.raises(asyncpg.UndefinedTableError) as caught:
            await create_container(AgentConfig(router_api_key="test-key", database_url=url))
        assert "learnings" in str(caught.value)
