"""Coverage for maistro.persistence.pg_audit.PgAuditLog (was 0%).

asyncpg.Pool/Connection are faked with the same in-process test double used
across the persistence test suite: records exact SQL + params, returns
canned rows, so tests assert on emitted SQL/params, not just "didn't raise".
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest

from maistro.persistence.pg_audit import PgAuditLog
from maistro.security._types import AuditEntry as SentinelAuditEntry
from maistro.security._types import Violation as SentinelViolation
from maistro.security.sentinel.signing import SIGNING_KEY_ENV, AuditSigner
from maistro.testing.postgres import postgres_dsn
from maistro.types.security import AuditEntry


class FakeRecord(dict):
    """Mimics asyncpg.Record: supports both ``row["x"]`` and ``row.get("x")``."""


class Call:
    def __init__(self, method: str, query: str, args: tuple[Any, ...]) -> None:
        self.method = method
        self.query = query
        self.args = args


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[Call] = []
        self._fetch_results: list[list[FakeRecord]] = []

    def queue_fetch(self, rows: list[dict[str, Any]]) -> None:
        self._fetch_results.append([FakeRecord(r) for r in rows])

    async def fetch(self, query: str, *args: Any) -> list[FakeRecord]:
        self.calls.append(Call("fetch", query, args))
        return self._fetch_results.pop(0) if self._fetch_results else []

    async def execute(self, query: str, *args: Any) -> str:
        self.calls.append(Call("execute", query, args))
        return "INSERT 0 1"


class FakePool:
    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn

    def acquire(self) -> _AcquireCtx:
        return _AcquireCtx(self._conn)


class _AcquireCtx:
    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn

    async def __aenter__(self) -> FakeConnection:
        return self._conn

    async def __aexit__(self, *exc: Any) -> None:
        return None


@pytest.fixture
def conn() -> FakeConnection:
    return FakeConnection()


@pytest.fixture
def log(conn: FakeConnection) -> PgAuditLog:
    return PgAuditLog(FakePool(conn))


@pytest.fixture
async def unmigrated_pool() -> AsyncIterator[Any]:
    """An asyncpg pool on a database of its own that no revision has touched.

    ``MAISTRO_TEST_PG_DSN`` names a *migrated* database, so the one schema a
    test cannot get from it is the pre-migration one. Yields ``None`` without a
    server, like every other PostgreSQL case in this directory.
    """
    dsn = postgres_dsn()
    if not dsn:
        yield None
        return
    asyncpg = pytest.importorskip("asyncpg")
    from sqlalchemy.engine import make_url

    name = f"audit_unmigrated_{uuid.uuid4().hex[:12]}"
    admin = await asyncpg.connect(dsn)
    try:
        await admin.execute(f'CREATE DATABASE "{name}"')
    finally:
        await admin.close()
    url = make_url(dsn).set(database=name).render_as_string(hide_password=False)
    pool = await asyncpg.create_pool(url, min_size=1, max_size=2)
    try:
        yield pool
    finally:
        await pool.close()
        admin = await asyncpg.connect(dsn)
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        finally:
            await admin.close()


def test_ephemeral_signing_key_warns_on_a_durable_store(
    conn: FakeConnection, caplog: pytest.LogCaptureFixture
) -> None:
    """The ADR-073 restart contract needs a configured key: without one this
    durable store writes proofs no later process can verify, so it must say
    so at wire time instead of failing silently on the first post-restart
    ``verify()``."""
    with caplog.at_level(logging.WARNING, logger="maistro.persistence.audit"):
        PgAuditLog(FakePool(conn))
    messages = " ".join(record.getMessage() for record in caplog.records)
    assert SIGNING_KEY_ENV in messages
    assert "verify" in messages


def test_supplied_signing_key_does_not_warn_on_a_durable_store(
    conn: FakeConnection, caplog: pytest.LogCaptureFixture
) -> None:
    """A deployment that configured its key chose durability; no warning."""
    with caplog.at_level(logging.WARNING, logger="maistro.persistence.audit"):
        PgAuditLog(FakePool(conn), signer=AuditSigner(bytes(32)))
    assert not [r for r in caplog.records if r.name == "maistro.persistence.audit"]


@pytest.mark.asyncio
async def test_ensure_schema_adds_proof_columns_idempotently(conn: FakeConnection) -> None:
    """Databases created before signed audit records lack the proof columns;
    wiring runs this upgrade on every start, so it must be the idempotent
    ADD COLUMN IF NOT EXISTS form covering all three proof columns."""
    await PgAuditLog(FakePool(conn), signer=AuditSigner(bytes(32))).ensure_schema()

    assert [call.query for call in conn.calls] == [
        "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS signature TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS signing_key_id TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS proof_type TEXT NOT NULL DEFAULT ''",
    ]


@pytest.mark.asyncio
async def test_ensure_schema_never_fabricates_the_migrated_audit_table(
    unmigrated_pool: Any,
) -> None:
    """Alembic owns ``audit_log``; a startup upgrade may not create it.

    Runtime ``CREATE TABLE IF NOT EXISTS`` here looked helpful and was not: the
    table it produced gave ``org_id`` no server default (036 declares one), and
    the alembic chain could then never be applied to that database — ``upgrade
    head`` dies with ``DuplicateTable: relation "audit_log" already exists``
    because 005's ``create_table`` is not conditional. The contract is the one
    the sibling PostgreSQL stores keep: an idempotent ``ADD COLUMN`` against a
    migrated table, and a loud ``UndefinedTable`` on one that was never
    migrated, rather than a silently forked schema.
    """
    if unmigrated_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    asyncpg = pytest.importorskip("asyncpg")

    with pytest.raises(asyncpg.exceptions.UndefinedTableError):
        await PgAuditLog(unmigrated_pool, signer=AuditSigner(bytes(32))).ensure_schema()

    async with unmigrated_pool.acquire() as conn:
        created = await conn.fetchval("SELECT to_regclass('audit_log')")
    assert created is None


@pytest.mark.asyncio
async def test_log_inserts_with_team_id_and_tool_name_defaults(
    log: PgAuditLog, conn: FakeConnection
) -> None:
    entry = AuditEntry(
        boundary="tool_call",
        user_id="u1",
        agent_id="a1",
        tool_name="bash",
        verdict="allowed",
        detail="ok",
        trace_id="t1",
        request_id="r1",
    )
    await log.log(entry)
    assert len(conn.calls) == 1
    call = conn.calls[0]
    assert call.method == "execute"
    assert "INSERT INTO audit_log" in call.query
    assert call.args == (
        "tool_call",
        "u1",
        "",  # org_id getattr default
        "",  # team_id getattr default
        "a1",
        "bash",
        "allowed",
        "ok",
        "t1",
        "r1",
        log.signer.sign(entry).signature,
        log.signer.key_id,
        "Ed25519Signature2020",
    )


@pytest.mark.asyncio
async def test_log_persists_org_scope(log: PgAuditLog, conn: FakeConnection) -> None:
    await log.log(AuditEntry(boundary="b", user_id="u", org_id="org-a", agent_id="a"))

    call = conn.calls[0]
    assert "org_id" in call.query
    assert call.args[2] == "org-a"


@pytest.mark.asyncio
async def test_log_tool_name_none_becomes_empty_string(
    log: PgAuditLog, conn: FakeConnection
) -> None:
    entry = AuditEntry(boundary="b", user_id="u", agent_id="a", tool_name=None)
    await log.log(entry)
    call = conn.calls[0]
    assert call.args[5] == ""


@pytest.mark.asyncio
async def test_persisted_deny_row_verifies_as_reconstructed(
    log: PgAuditLog, conn: FakeConnection
) -> None:
    """The row PgAuditLog writes must verify when read back as a durable row.

    Durable stores never serialize the violations tuple, so the INSERT params
    are the whole persisted record: rebuilding an AuditEntry from them and
    verifying is the exact restart contract, exercised for a deny decision
    that carries violations.
    """
    await log.log(
        SentinelAuditEntry(
            boundary="tool_call",
            user_id="u1",
            tool_name="bash",
            verdict="denied",
            violations=(
                SentinelViolation(
                    boundary="tool_call", rule="dangerous-command", severity="high", detail="d"
                ),
            ),
        )
    )

    (
        boundary,
        user_id,
        org_id,
        team_id,
        agent_id,
        tool_name,
        verdict,
        detail,
        trace_id,
        request_id,
        signature,
        signing_key_id,
        proof_type,
    ) = conn.calls[0].args
    row = AuditEntry(
        boundary=boundary,
        user_id=user_id,
        org_id=org_id,
        team_id=team_id,
        agent_id=agent_id,
        tool_name=tool_name or None,
        verdict=verdict,
        detail=detail,
        trace_id=trace_id,
        request_id=request_id,
        signature=signature,
        signing_key_id=signing_key_id,
        proof_type=proof_type,
    )
    assert log.verify(row)


@pytest.mark.asyncio
async def test_log_team_id_passthrough_when_present(log: PgAuditLog, conn: FakeConnection) -> None:
    entry = AuditEntry(boundary="b", user_id="u", team_id="team-9", agent_id="a")
    await log.log(entry)
    call = conn.calls[0]
    assert call.args[3] == "team-9"


@pytest.mark.asyncio
async def test_get_entries_defaults_to_system_scope(log: PgAuditLog, conn: FakeConnection) -> None:
    conn.queue_fetch([])
    await log.get_entries()
    call = conn.calls[0]
    assert "WHERE org_id = $1" in call.query
    assert call.args == ("", 100)


@pytest.mark.asyncio
async def test_get_entries_user_id_filter_builds_param(
    log: PgAuditLog, conn: FakeConnection
) -> None:
    conn.queue_fetch([])
    await log.get_entries(user_id="u1", limit=5)
    call = conn.calls[0]
    assert "user_id = $1" in call.query
    assert "LIMIT $3" in call.query
    assert call.args == ("u1", "", 5)


@pytest.mark.asyncio
async def test_get_entries_both_filters_combined_with_and(
    log: PgAuditLog, conn: FakeConnection
) -> None:
    conn.queue_fetch([])
    await log.get_entries(user_id="u1", agent_id="a1")
    call = conn.calls[0]
    assert "user_id = $1 AND agent_id = $2 AND org_id = $3" in call.query
    assert call.args == ("u1", "a1", "", 100)


@pytest.mark.asyncio
async def test_get_entries_org_scope_composes_in_sql(log: PgAuditLog, conn: FakeConnection) -> None:
    conn.queue_fetch([])
    await log.get_entries(user_id="u1", agent_id="a1", org_id="org-a")
    call = conn.calls[0]
    assert "user_id = $1 AND agent_id = $2 AND org_id = $3" in call.query
    assert call.args == ("u1", "a1", "org-a", 100)


@pytest.mark.asyncio
async def test_get_entries_rejects_none_org_scope(log: PgAuditLog, conn: FakeConnection) -> None:
    with pytest.raises(ValueError, match="pass '' for an unscoped read"):
        await log.get_entries(org_id=None)  # type: ignore[arg-type]
    assert conn.calls == []


@pytest.mark.asyncio
async def test_get_entries_returns_reconstructed_audit_entries(
    log: PgAuditLog, conn: FakeConnection
) -> None:
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    conn.queue_fetch(
        [
            {
                "timestamp": ts,
                "boundary": "tool_call",
                "user_id": "u1",
                "org_id": "org-a",
                "team_id": "team-1",
                "agent_id": "a1",
                "tool_name": "bash",
                "verdict": "allowed",
                "detail": "ok",
                "trace_id": "t1",
                "request_id": "r1",
            }
        ]
    )
    entries = await log.get_entries(user_id="u1", org_id="org-a")
    assert len(entries) == 1
    e = entries[0]
    assert isinstance(e, AuditEntry)
    assert e.timestamp == ts
    assert e.boundary == "tool_call"
    assert e.user_id == "u1"
    assert e.org_id == "org-a"
    assert e.team_id == "team-1"
    assert e.agent_id == "a1"
    assert e.tool_name == "bash"
    assert e.verdict == "allowed"
    assert e.detail == "ok"
    assert e.trace_id == "t1"
    assert e.request_id == "r1"


@pytest.mark.asyncio
async def test_get_entries_missing_optional_fields_default(
    log: PgAuditLog, conn: FakeConnection
) -> None:
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    conn.queue_fetch([{"timestamp": ts}])
    entries = await log.get_entries()
    e = entries[0]
    assert e.boundary == ""
    assert e.user_id == ""
    assert e.org_id == ""
    assert e.team_id == ""
    assert e.agent_id == ""
    assert e.tool_name is None
    assert e.verdict == "allowed"
    assert e.detail == ""
    assert e.trace_id == ""
    assert e.request_id == ""


def test_allowed_filter_columns_include_org_scope() -> None:
    from maistro.persistence.pg_audit import _ALLOWED_FILTER_COLUMNS

    assert frozenset({"user_id", "agent_id", "org_id"}) == _ALLOWED_FILTER_COLUMNS


@pytest.mark.asyncio
async def test_get_entries_invalid_filter_column_raises(
    log: PgAuditLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The allowlist guard is dead code via the public API today (only
    user_id/agent_id are accepted params, both allowlisted) — patch the
    allowlist itself to a smaller set so the guard's error branch actually
    executes, proving it works if a new filter column is ever added without
    updating the allowlist."""
    import maistro.persistence.pg_audit as pg_audit_module

    monkeypatch.setattr(pg_audit_module, "_ALLOWED_FILTER_COLUMNS", frozenset({"agent_id"}))
    with pytest.raises(ValueError, match="Invalid filter column: 'user_id'"):
        await log.get_entries(user_id="u1")


@pytest.mark.asyncio
async def test_get_entries_rejects_unknown_keyword(log: PgAuditLog) -> None:
    with pytest.raises(TypeError, match="unexpected keyword argument 'status'"):
        await log.get_entries(status="denied")  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_real_postgres_two_org_scope_and_schema(
    pg_pool: Any,
) -> None:
    """Exercise the migration, write, and predicate against PostgreSQL itself."""
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")

    async with pg_pool.acquire() as conn:
        columns = await conn.fetch(
            """SELECT column_name, is_nullable, column_default
               FROM information_schema.columns
               WHERE table_name = 'audit_log' AND column_name = 'org_id'"""
        )
        indexes = await conn.fetch(
            """SELECT indexdef FROM pg_indexes
               WHERE tablename = 'audit_log' AND indexname = 'ix_audit_log_scope'"""
        )
    assert [row["column_name"] for row in columns] == ["org_id"]
    assert columns[0]["is_nullable"] == "YES"
    assert columns[0]["column_default"] in ("''::text", "''::character varying")
    assert '(org_id, "timestamp")' in indexes[0]["indexdef"]

    audit = PgAuditLog(pg_pool)
    await audit.log(AuditEntry(boundary="org-a", user_id="u", org_id="org-a"))
    await audit.log(AuditEntry(boundary="org-b", user_id="u", org_id="org-b"))

    entries = await audit.get_entries(user_id="u", org_id="org-a")

    assert [entry.boundary for entry in entries] == ["org-a"]
    assert all(entry.org_id == "org-a" for entry in entries)
