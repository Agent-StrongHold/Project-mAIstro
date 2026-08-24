"""A spine payload survives whichever pool wrote it, and whichever reads it (#132).

`maistro.persistence.get_pool` registers a `json.dumps`/`json.loads` codec for
`jsonb`; a raw `asyncpg.create_pool` does not, and its default codec is `str`
in both directions. Both pools are legitimate and both reach these stores --
the container's URL path builds the first, and #135's caller-supplied-pool seam
hands over the second.

`decode_payload` already made *reads* independent of that choice. Writes were
not: `json_of` produces text, and bound plainly to a `jsonb` column that text
was stored as an object by one pool and re-encoded into a jsonb **string** by
the other. A row written that way is wrong in the database, so no amount of
read-side tolerance recovers it -- and the reader that noticed was the one on
the *other* kind of pool, several suites away from the write.

These tests cross the two deliberately: each writes with one pool and reads
with the other, in both directions, and checks the column's own
`jsonb_typeof`. A suite that used one kind of pool throughout would pass with
every payload in the database double-encoded, which is exactly what happened.
"""

from __future__ import annotations

import json

import pytest

from maistro.testing.postgres import postgres_dsn

pytestmark = pytest.mark.skipif(
    not postgres_dsn(), reason="needs a migrated PostgreSQL; see maistro.testing.postgres"
)


async def _codec_pool():
    """A pool built the way `maistro.persistence.get_pool` builds one."""
    import asyncpg

    from maistro.persistence import _register_json_codecs

    return await asyncpg.create_pool(
        postgres_dsn(), min_size=1, max_size=2, init=_register_json_codecs
    )


async def _raw_pool():
    """A pool built the way a caller handing one over builds it (#135)."""
    import asyncpg

    return await asyncpg.create_pool(postgres_dsn(), min_size=1, max_size=2)


def _store(pool):
    from maistro.projects.pg_scope_store import PgProjectScopeStore

    return PgProjectScopeStore(pool)


async def _kind(pool, workspace_id: str) -> str | None:
    """What PostgreSQL itself thinks the stored payload is."""
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT jsonb_typeof(payload) FROM canonical_projects "
            "WHERE workspace_id = $1 AND is_root",
            workspace_id,
        )


@pytest.mark.parametrize(
    ("writer", "reader"),
    [
        pytest.param(_codec_pool, _raw_pool, id="codec-writes-raw-reads"),
        pytest.param(_raw_pool, _codec_pool, id="raw-writes-codec-reads"),
        pytest.param(_codec_pool, _codec_pool, id="codec-both"),
        pytest.param(_raw_pool, _raw_pool, id="raw-both"),
    ],
)
async def test_a_root_project_round_trips_across_pool_kinds(writer, reader) -> None:
    workspace_id = f"ws-{writer.__name__}-{reader.__name__}"
    write_pool = await writer()
    read_pool = await reader()
    try:
        async with write_pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM canonical_projects WHERE workspace_id = $1", workspace_id
            )
        written = await _store(write_pool).create_root(workspace_id)

        # The column, before anything reads it back through a model: a jsonb
        # `string` here is a corrupt row whatever the reader then does with it.
        assert await _kind(write_pool, workspace_id) == "object"

        read_back = await _store(read_pool).root_for_workspace(workspace_id)
        assert read_back is not None
        assert read_back.project_id == written.project_id
        assert read_back.workspace_id == workspace_id
    finally:
        async with write_pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM canonical_projects WHERE workspace_id = $1", workspace_id
            )
        await write_pool.close()
        await read_pool.close()


async def test_the_codec_pool_is_the_one_that_used_to_double_encode() -> None:
    """Pins the mechanism, not just the symptom.

    Without the `::text::jsonb` cast this is what the store did: hand a
    registered `json.dumps` codec a string that is already JSON, and it encodes
    it a second time. Asserting it directly means a future statement that drops
    the cast fails here with the reason attached, rather than somewhere
    downstream as a pydantic `model_type` error on a `str`.
    """
    pool = await _codec_pool()
    try:
        async with pool.acquire() as conn:
            await conn.execute("DROP TABLE IF EXISTS jsonb_codec_probe")
            await conn.execute("CREATE TABLE jsonb_codec_probe (id int primary key, p jsonb)")
            text = json.dumps({"a": 1})

            await conn.execute("INSERT INTO jsonb_codec_probe VALUES (1, $1)", text)
            await conn.execute("INSERT INTO jsonb_codec_probe VALUES (2, $1::text::jsonb)", text)

            kinds = dict(
                await conn.fetch("SELECT id, jsonb_typeof(p) FROM jsonb_codec_probe ORDER BY id")
            )
            await conn.execute("DROP TABLE jsonb_codec_probe")
    finally:
        await pool.close()

    assert kinds == {1: "string", 2: "object"}
