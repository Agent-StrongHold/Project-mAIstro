"""SPEC-083026-427c: prompt versions and labels, against stores that enforce keys.

The suite this replaces drove `PgPromptManager` through a fake connection. A
fake enforces no keys, so two *unconditional* failures sat on `develop` under a
green tick: `ON CONFLICT (name, label)` could not infer the partial index it
named, and the second row the production-init wrote collided with
`prompts_pkey`. Every new prompt created under a label other than `production`
raised, always. A test that cannot fail on a key violation is not evidence
about a key, which is why the PostgreSQL cases here refuse to run against
anything but a real server.

`prompt_store` is parametrized over both backends for the behaviour they must
share. Concurrency, rollback and constraint enforcement are PostgreSQL-only:
SQLite serializes every writer at the database, so it cannot exhibit the race
being closed and testing it there would prove nothing about the fix.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import AsyncIterator
from typing import Any

import pytest

from maistro.persistence.pg_prompts import PgPromptManager

pytest.importorskip("aiosqlite")
import aiosqlite

pytestmark = [pytest.mark.contract("behavioral")]


@pytest.fixture
async def sqlite_prompts() -> AsyncIterator[Any]:
    from maistro.persistence.sqlite_prompts import SqlitePromptManager

    conn = await aiosqlite.connect(":memory:")
    manager = SqlitePromptManager(conn)
    await manager.ensure_schema()
    try:
        yield manager
    finally:
        await conn.close()


@pytest.fixture
async def pg_prompts(pg_pool: Any) -> AsyncIterator[Any]:
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    yield PgPromptManager(pg_pool)


@pytest.fixture(params=["sqlite", "postgres"])
async def prompt_store(request: pytest.FixtureRequest, pg_pool: Any) -> AsyncIterator[Any]:
    if request.param == "sqlite":
        from maistro.persistence.sqlite_prompts import SqlitePromptManager

        conn = await aiosqlite.connect(":memory:")
        manager = SqlitePromptManager(conn)
        await manager.ensure_schema()
        try:
            yield manager
        finally:
            await conn.close()
        return
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    yield PgPromptManager(pg_pool)


async def _versions(store: Any, name: str) -> list[int]:
    """The version numbers a store holds for one name, read behind its back.

    Deliberately not through the manager: the manager exposes labels, and what
    several criteria are about is how many *versions* exist, which no label can
    report.
    """
    if isinstance(store, PgPromptManager):
        async with store._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT version FROM prompts WHERE name = $1 ORDER BY version", name
            )
        return [int(r["version"]) for r in rows]
    cursor = await store._conn.execute(
        "SELECT version FROM prompts WHERE name = ? ORDER BY version", (name,)
    )
    return [int(r[0]) for r in await cursor.fetchall()]


async def _raw_insert(store: Any, sql: str) -> None:
    """Write a row bypassing the manager, on whichever backend this is.

    The point of AC-7 is that the constraints hold against *any* writer, so the
    writer here must not be the class under test.
    """
    if isinstance(store, PgPromptManager):
        async with store._pool.acquire() as conn:
            await conn.execute(sql)
        return
    await store._conn.execute(sql)


def _integrity_error(store: Any) -> type[BaseException]:
    """The exception a violated constraint raises on this backend."""
    if isinstance(store, PgPromptManager):
        asyncpg = pytest.importorskip("asyncpg")
        error: type[BaseException] = asyncpg.IntegrityConstraintViolationError
        return error
    return sqlite3.IntegrityError


async def _all_content(store: Any, name: str) -> list[str]:
    """Every version's content for one name, in version order."""
    if isinstance(store, PgPromptManager):
        async with store._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT content FROM prompts WHERE name = $1 ORDER BY version", name
            )
        return [str(r["content"]) for r in rows]
    cursor = await store._conn.execute(
        "SELECT content FROM prompts WHERE name = ? ORDER BY version", (name,)
    )
    return [str(r[0]) for r in await cursor.fetchall()]


class TestAVersionAndItsLabels:
    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-083026-427c/AC-1")
    async def test_the_first_version_of_a_prompt_can_be_created(self, prompt_store) -> None:
        """AC-1. On `develop` this raised on PostgreSQL for every prompt whose
        first write was not explicitly labelled `production` -- which is the
        default path, since `upsert`'s default label is empty."""
        await prompt_store.upsert("agent.alpha", "hello", config={"t": 1})

        assert await prompt_store.get("agent.alpha", label="latest") == "hello"
        assert await prompt_store.get("agent.alpha", label="production") == "hello"

    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-083026-427c/AC-2")
    async def test_two_labels_on_one_version_store_the_content_once(self, prompt_store) -> None:
        """AC-2. The old shape had no way to say this, so it wrote the content
        twice and let the two copies drift."""
        await prompt_store.upsert("agent.alpha", "hello")

        assert await _versions(prompt_store, "agent.alpha") == [1]

    @pytest.mark.asyncio
    async def test_a_promotion_moves_a_label_without_making_a_version(self, prompt_store) -> None:
        await prompt_store.upsert("agent.alpha", "v1")
        await prompt_store.upsert("agent.alpha", "v2", label="staging")

        assert await prompt_store.get("agent.alpha", label="staging") == "v2"
        assert await prompt_store.get("agent.alpha", label="production") == "v1"
        assert await _versions(prompt_store, "agent.alpha") == [1, 2]

    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-083026-427c/AC-5")
    async def test_an_identical_rewrite_creates_no_new_version(self, prompt_store) -> None:
        """AC-5. A client that times out and retries must not double the
        history. The label still moves, so the retry is a no-op rather than a
        refusal."""
        await prompt_store.upsert("agent.alpha", "v1", config={"t": 1})
        await prompt_store.upsert("agent.alpha", "v1", config={"t": 1}, label="staging")

        assert await _versions(prompt_store, "agent.alpha") == [1]
        assert await prompt_store.get("agent.alpha", label="staging") == "v1"

    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-083026-427c/AC-5")
    async def test_a_changed_config_is_a_new_version_even_at_identical_content(
        self, prompt_store
    ) -> None:
        """The other side of AC-5, and the one that keeps it honest: idempotence
        keyed on content alone would swallow a temperature change silently."""
        await prompt_store.upsert("agent.alpha", "v1", config={"t": 1})
        await prompt_store.upsert("agent.alpha", "v1", config={"t": 2})

        assert await _versions(prompt_store, "agent.alpha") == [1, 2]

    @pytest.mark.asyncio
    async def test_an_unresolvable_label_falls_back_to_the_highest_version(
        self, prompt_store
    ) -> None:
        await prompt_store.upsert("agent.alpha", "v1")
        await prompt_store.upsert("agent.alpha", "v2", label="staging")

        assert await prompt_store.get("agent.alpha", label="never-set") == "v2"

    @pytest.mark.asyncio
    async def test_a_name_with_no_versions_reads_empty(self, prompt_store) -> None:
        assert await prompt_store.get_with_config("absent") == ("", {})


class TestTheDatabaseHoldsTheProperties:
    """AC-7. Constraints, not code discipline: they hold against any writer.

    Both backends, because "the database enforces it" was the claim SQLite was
    quietly not making -- its table declared no key over `(name, version)` at
    all, and its foreign key was parsed and ignored, `PRAGMA foreign_keys`
    being off by default. Asserting this only where it already held would have
    left that exactly as it was.
    """

    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-083026-427c/AC-7")
    async def test_a_duplicate_version_for_one_name_is_refused(self, prompt_store) -> None:
        await prompt_store.upsert("agent.alpha", "v1")

        with pytest.raises(_integrity_error(prompt_store)):
            await _raw_insert(
                prompt_store,
                "INSERT INTO prompts (name, version, content, config) "
                "VALUES ('agent.alpha', 1, 'other', '{}')",
            )

    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-083026-427c/AC-7")
    async def test_one_label_cannot_point_at_two_versions(self, prompt_store) -> None:
        await prompt_store.upsert("agent.alpha", "v1")
        await prompt_store.upsert("agent.alpha", "v2")

        with pytest.raises(_integrity_error(prompt_store)):
            await _raw_insert(
                prompt_store,
                "INSERT INTO prompt_labels (name, label, version) "
                "VALUES ('agent.alpha', 'latest', 1)",
            )

    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-083026-427c/AC-7")
    async def test_a_label_cannot_name_a_version_that_does_not_exist(self, prompt_store) -> None:
        await prompt_store.upsert("agent.alpha", "v1")

        with pytest.raises(_integrity_error(prompt_store)):
            await _raw_insert(
                prompt_store,
                "INSERT INTO prompt_labels (name, label, version) "
                "VALUES ('agent.alpha', 'staging', 99)",
            )


class TestConcurrentWriters:
    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-083026-427c/AC-3")
    async def test_writers_to_one_name_do_not_share_a_version_number(self, prompt_store) -> None:
        """AC-3. Five concurrent writers. On PostgreSQL they arrive on five
        pooled connections and queue on the advisory lock; on SQLite they share
        one connection and queue on `BEGIN IMMEDIATE` behind the write mutex.
        Either way the versions must come out 1..5 with nothing lost.

        Five rather than two: two coroutines can happen to serialize on a fast
        loop, and a race that only sometimes reproduces is a test that only
        sometimes tests.
        """
        contents = [f"v{i}" for i in range(5)]

        await asyncio.gather(*(prompt_store.upsert("agent.alpha", c) for c in contents))

        assert await _versions(prompt_store, "agent.alpha") == [1, 2, 3, 4, 5]
        assert sorted(await _all_content(prompt_store, "agent.alpha")) == sorted(contents), (
            "a writer's content was lost"
        )

    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-083026-427c/AC-4")
    async def test_a_failed_write_leaves_the_label_where_it_was(
        self, prompt_store, monkeypatch
    ) -> None:
        """AC-4. The failure is injected *inside* the transaction, after the
        version row is written, so what is asserted is the database rolling the
        whole thing back -- not the code's intention to.
        """
        await prompt_store.upsert("agent.alpha", "v1")
        store_type = type(prompt_store)
        original = store_type._version_for

        async def _explode(self, *args, **kwargs):
            await original(self, *args, **kwargs)
            raise RuntimeError("injected after the version row was written")

        monkeypatch.setattr(store_type, "_version_for", _explode)

        with pytest.raises(RuntimeError):
            await prompt_store.upsert("agent.alpha", "v2", label="production")

        monkeypatch.undo()
        assert await prompt_store.get("agent.alpha", label="production") == "v1"
        assert await prompt_store.get("agent.alpha", label="latest") == "v1"
        assert await _versions(prompt_store, "agent.alpha") == [1]

    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-083026-427c/AC-6")
    async def test_writers_to_different_names_do_not_contend(self, pg_prompts, monkeypatch) -> None:
        """AC-6. PostgreSQL only, and deliberately so: SQLite's write lock is
        the whole database, so it has no per-name granularity to test and
        asserting this there would assert nothing.

        A write to `alpha` is made slow *while holding its lock*, and a write to
        `beta` must finish without waiting for it. The holder is a real `upsert`
        rather than a hand-written `pg_advisory_xact_lock` call, and that is the
        whole point: an earlier draft took the lock in the test body using the
        key the correct implementation computes, and then passed unchanged when
        the implementation was mutated to one global key -- asserting against
        its own copy of the rule rather than the code's.
        """
        original = PgPromptManager._version_for
        holding = asyncio.Event()

        async def _slow(self, conn, name, content, config_json):
            if name == "agent.alpha":
                holding.set()
                await asyncio.sleep(2.0)
            return await original(self, conn, name, content, config_json)

        monkeypatch.setattr(PgPromptManager, "_version_for", _slow)

        alpha = asyncio.create_task(pg_prompts.upsert("agent.alpha", "a1"))
        try:
            await asyncio.wait_for(holding.wait(), timeout=5.0)
            await asyncio.wait_for(pg_prompts.upsert("agent.beta", "b1"), timeout=1.0)
        finally:
            await alpha

        assert await pg_prompts.get("agent.beta", label="latest") == "b1"
        assert await pg_prompts.get("agent.alpha", label="latest") == "a1"


class TestTheTwoBackendsAgree:
    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-083026-427c/AC-8")
    async def test_the_same_writes_read_back_the_same(self, sqlite_prompts, pg_prompts) -> None:
        """AC-8. The claim `SqlitePromptManager` makes in its own docstring --
        "the same protocol as PgPromptManager" -- asserted rather than stated.
        It was false: the two stores disagreed about whether a version could
        appear twice, and each suite agreed with its own store.
        """
        writes = [
            ("agent.alpha", "v1", {}, ""),
            ("agent.alpha", "v2", {"t": 1}, "staging"),
            ("agent.alpha", "v2", {"t": 1}, "canary"),  # a retry, not a version
            ("agent.beta", "b1", {}, "production"),
        ]
        for store in (sqlite_prompts, pg_prompts):
            for name, content, config, label in writes:
                await store.upsert(name, content, config=config, label=label)

        for name in ("agent.alpha", "agent.beta"):
            assert await _versions(sqlite_prompts, name) == await _versions(pg_prompts, name), name
            for label in ("latest", "production", "staging", "canary"):
                assert await sqlite_prompts.get_with_config(
                    name, label=label
                ) == await pg_prompts.get_with_config(name, label=label), f"{name}/{label}"
