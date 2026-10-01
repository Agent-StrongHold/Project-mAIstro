"""The authority cutover is recorded, proven, and reversible (#102).

The cutover acceptance: the flip happens only after the replacement path
works end-to-end (byte-exact round-trip proof), the event/version is
explicitly recorded, and it stays reversible during migration validation.
The durable legs run against the SQLite control store with the same
per-connection discipline the item store uses, so "restart durability" here
means new connections reading what a closed connection wrote.
"""

from __future__ import annotations

import os
import uuid

import aiosqlite
import pytest

from maistro.backlog.cutover import (
    AuthorityLedger,
    BacklogAuthority,
    CutoverError,
    InMemoryAuthorityLedger,
    InMemoryDocumentState,
    SqliteAuthorityLedger,
    SqliteDocumentState,
    current_authority,
    cutover_to_db,
    export_authoritative,
    import_document,
    revert_to_markdown,
)
from maistro.backlog.markdown_io import parse_markdown
from maistro.backlog.store import InMemoryBacklogStore
from maistro.testing.postgres import postgres_dsn

DOC = (
    "# Backlog\n\n"
    "## Items (`eng-NNN`)\n\n"
    "### First\n\n"
    "**[eng-001] Base — Proposed — M1**\n- base work\n\n"
    "**[eng-002] Dependent — Proposed — M1**\n- Blocked-by: `eng-001`\n"
)

POST_CUTOVER_ITEM = "**[eng-003] Born in the db — Proposed — M2**\n- fresh work\n"


# ---------------------------------------------------------------------------
# The ledger
# ---------------------------------------------------------------------------


async def test_authority_defaults_to_markdown_and_flips_are_recorded() -> None:
    ledger: AuthorityLedger = InMemoryAuthorityLedger()
    assert await current_authority(ledger) is BacklogAuthority.MARKDOWN

    cut = await ledger.append(
        authority=BacklogAuthority.DB, actor="human:blake", note="cutover after E2E"
    )
    assert cut.revision == 1
    assert await current_authority(ledger) is BacklogAuthority.DB

    back = await revert_to_markdown(ledger, actor="human:blake")
    assert back.revision == 2
    assert await current_authority(ledger) is BacklogAuthority.MARKDOWN

    history = await ledger.history()
    assert [record.authority for record in history] == [
        BacklogAuthority.DB,
        BacklogAuthority.MARKDOWN,
    ]
    assert history[0].note == "cutover after E2E"
    assert all(record.actor == "human:blake" for record in history)


async def test_sqlite_ledger_and_document_state_survive_a_restart(tmp_path) -> None:
    path = tmp_path / "control.db"

    async def open_store():
        conn = await aiosqlite.connect(path)
        ledger = SqliteAuthorityLedger(conn)
        documents = SqliteDocumentState(conn)
        await ledger.ensure_schema()
        await documents.ensure_schema()
        return conn, ledger, documents

    conn, ledger, documents = await open_store()
    try:
        await ledger.append(authority=BacklogAuthority.DB, actor="t", note="cut")
        document = parse_markdown(DOC)
        await documents.put_tokens("BACKLOG.md", document.tokens)
    finally:
        await conn.close()

    # New connections: the durable answer, not a shared in-memory one.
    conn2, ledger2, documents2 = await open_store()
    try:
        assert await current_authority(ledger2) is BacklogAuthority.DB
        record = await ledger2.current()
        assert record is not None and record.revision == 1
        tokens = await documents2.get_tokens("BACKLOG.md")
        assert tokens is not None
        assert tokens == parse_markdown(DOC).tokens
        assert await documents2.get_tokens("other.md") is None
    finally:
        await conn2.close()


async def test_pg_ledger_and_document_state_survive_a_restart() -> None:
    """The PostgreSQL control stores read the same durable answer across
    pools, from the Alembic-managed tables (`049`) the SQLite twin mirrors."""
    dsn = postgres_dsn()
    if not dsn:
        if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
            msg = "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_PG_DSN is empty"
            raise RuntimeError(msg)
        pytest.skip("set MAISTRO_TEST_PG_DSN to a migrated PostgreSQL database")
    asyncpg = pytest.importorskip("asyncpg")
    from maistro.backlog.pg_store import PgAuthorityLedger, PgDocumentState

    pool = await asyncpg.create_pool(dsn)
    assert pool is not None
    try:
        ledger = PgAuthorityLedger(pool)
        documents = PgDocumentState(pool)
        await ledger.ensure_schema()
        await documents.ensure_schema()

        # The ledger table is installation-global, so this leg tags its rows
        # and asserts only on them: the suite may share the database.
        tag = f"pg-leg-{uuid.uuid4().hex[:12]}"
        cut = await ledger.append(authority=BacklogAuthority.DB, actor=tag, note="cut")
        back = await revert_to_markdown(ledger, actor=tag, note="revert")
        assert back.revision == cut.revision + 1
        await documents.put_tokens("BACKLOG.md", parse_markdown(DOC).tokens)

        # A second pool: the durable answer, not a shared in-memory one.
        pool2 = await asyncpg.create_pool(dsn)
        assert pool2 is not None
        try:
            ledger2 = PgAuthorityLedger(pool2)
            documents2 = PgDocumentState(pool2)
            mine = [r for r in await ledger2.history() if r.actor == tag]
            assert [r.authority for r in mine] == [
                BacklogAuthority.DB,
                BacklogAuthority.MARKDOWN,
            ]
            current = await ledger2.current()
            assert current is not None and current.revision >= back.revision
            tokens = await documents2.get_tokens("BACKLOG.md")
            assert tokens is not None
            assert tokens == parse_markdown(DOC).tokens
            assert await documents2.get_tokens("other.md") is None
        finally:
            await pool2.close()
    finally:
        await pool.close()


async def test_pg_control_stores_refuse_an_unmigrated_database() -> None:
    """Alembic owns the control DDL, so a database migration `049` has not
    touched is an explicit refusal naming the migration, never a quiet
    self-created schema."""

    class _EmptyPool:
        async def fetchval(self, _sql: str, _table: str) -> None:
            return None

    from maistro.backlog.pg_store import PgAuthorityLedger

    ledger = PgAuthorityLedger(_EmptyPool())  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="alembic upgrade"):
        await ledger.ensure_schema()


# ---------------------------------------------------------------------------
# The cutover operation
# ---------------------------------------------------------------------------


async def test_cutover_requires_a_lossless_round_trip_first(monkeypatch) -> None:
    store = InMemoryBacklogStore()
    ledger = InMemoryAuthorityLedger()
    documents = InMemoryDocumentState()
    await import_document(store, DOC, document_state=documents)

    # The cutover imports first (healing any drift), then proves the export.
    # If the renderer ever failed to reproduce the document -- the proof the
    # flip is built on -- the flip must be refused with the file still
    # canonical. Force that failure directly to exercise the guard.
    def lossy(tokens, items):
        return DOC + "\n(could not reproduce this line)\n"

    monkeypatch.setattr("maistro.backlog.cutover.render_document", lossy)
    with pytest.raises(CutoverError, match="byte-for-byte"):
        await cutover_to_db(store, DOC, ledger, document_state=documents)
    assert await current_authority(ledger) is BacklogAuthority.MARKDOWN


async def test_cutover_proves_the_round_trip_then_records_the_flip() -> None:
    store = InMemoryBacklogStore()
    ledger = InMemoryAuthorityLedger()
    documents = InMemoryDocumentState()

    record = await cutover_to_db(store, DOC, ledger, actor="human:blake", document_state=documents)
    assert record.revision == 1
    assert record.authority is BacklogAuthority.DB
    assert await current_authority(ledger) is BacklogAuthority.DB
    # The document state is persisted with the flip, so the file can be
    # regenerated after a restart without the original text.
    assert await documents.get_tokens("BACKLOG.md") == parse_markdown(DOC).tokens


async def test_post_cutover_export_is_deterministic_and_restart_stable(tmp_path) -> None:
    import aiosqlite

    from maistro.backlog.sqlite_store import SqliteBacklogStore

    path = tmp_path / "backlog.db"
    conn = await aiosqlite.connect(path)
    store = SqliteBacklogStore(conn)
    documents = SqliteDocumentState(conn)
    ledger = SqliteAuthorityLedger(conn)
    await store.ensure_schema()
    await documents.ensure_schema()
    await ledger.ensure_schema()
    try:
        await cutover_to_db(store, DOC, ledger, document_state=documents)
        first = await export_authoritative(store, documents)
        assert first == DOC
    finally:
        await conn.close()

    # A restart (fresh connections to the same database) regenerates the same
    # bytes from the database alone.
    conn2 = await aiosqlite.connect(path)
    store2 = SqliteBacklogStore(conn2)
    documents2 = SqliteDocumentState(conn2)
    try:
        assert await export_authoritative(store2, documents2) == DOC
        # An item created in the database after the cutover appears under the
        # generated heading, deterministically.
        await store2.create_item(
            workspace_id="root-backlog",
            title="Born in the db",
            actor="agent:x",
            details="fresh work",
            milestone="M2",
            item_id="eng-003",
        )
        with_new = await export_authoritative(store2, documents2)
        assert POST_CUTOVER_ITEM in with_new
        assert with_new.index("## Items added after the authority cutover") > with_new.index(
            "**[eng-002]"
        )
        assert await export_authoritative(store2, documents2) == with_new
    finally:
        await conn2.close()


async def test_revert_restores_markdown_authority_and_keeps_history() -> None:
    store = InMemoryBacklogStore()
    ledger = InMemoryAuthorityLedger()
    documents = InMemoryDocumentState()
    await cutover_to_db(store, DOC, ledger, document_state=documents)
    await revert_to_markdown(ledger, actor="human:blake", note="validation found a gap")
    assert await current_authority(ledger) is BacklogAuthority.MARKDOWN
    history = await ledger.history()
    assert len(history) == 2
    assert history[1].note == "validation found a gap"
    # The imported state survives the revert: re-cutting over is a re-proof,
    # not a re-import from scratch.
    assert await documents.get_tokens("BACKLOG.md") is not None
