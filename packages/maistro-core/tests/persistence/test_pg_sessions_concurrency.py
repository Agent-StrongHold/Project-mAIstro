"""Real-PostgreSQL concurrency evidence for PgSessionStore (#327)."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import asyncpg
import pytest

from maistro.persistence.pg_sessions import PgSessionStore

from .conftest import requires_postgres


@requires_postgres
async def test_concurrent_batches_are_contiguous_and_never_collide(pg_pool: Any) -> None:
    store = PgSessionStore(pg_pool)

    await asyncio.gather(
        *(
            store.append_messages(
                "shared-session",
                [
                    {"role": "user", "content": f"user-{index}"},
                    {"role": "assistant", "content": f"assistant-{index}"},
                ],
            )
            for index in range(12)
        )
    )

    rows = await pg_pool.fetch(
        "SELECT seq, role, content FROM sessions WHERE session_id = $1 ORDER BY seq",
        "shared-session",
    )
    assert [row["seq"] for row in rows] == list(range(24))
    assert len({row["seq"] for row in rows}) == 24

    # Each append owns the session lock for its whole two-message transaction,
    # so another writer cannot land between the user and assistant rows.
    for offset in range(0, 24, 2):
        user = rows[offset]
        assistant = rows[offset + 1]
        assert user["role"] == "user"
        assert assistant["role"] == "assistant"
        assert assistant["content"].removeprefix("assistant-") == user["content"].removeprefix(
            "user-"
        )


@requires_postgres
async def test_failed_multi_message_append_commits_no_prefix(pg_pool: Any) -> None:
    store = PgSessionStore(pg_pool)
    invalid = cast(
        list[dict[str, str]],
        [
            {"role": "user", "content": "must-roll-back"},
            {"role": "assistant", "content": object()},
        ],
    )

    with pytest.raises(asyncpg.DataError):
        await store.append_messages("atomic-session", invalid)

    count = await pg_pool.fetchval(
        "SELECT count(*) FROM sessions WHERE session_id = $1",
        "atomic-session",
    )
    assert count == 0


@requires_postgres
async def test_retention_sweep_cannot_delete_fresh_concurrent_appends(pg_pool: Any) -> None:
    store = PgSessionStore(pg_pool, ttl_seconds=3600)

    await asyncio.gather(
        *(
            store.append_messages("retained", [{"role": "user", "content": str(index)}])
            for index in range(8)
        ),
        *(store.purge_expired(ttl_seconds=3600) for _ in range(4)),
    )

    rows = await pg_pool.fetch(
        "SELECT seq FROM sessions WHERE session_id = $1 ORDER BY seq",
        "retained",
    )
    assert [row["seq"] for row in rows] == list(range(8))
