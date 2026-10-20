"""Coverage for maistro.persistence.pg_audit.PgAuditLog (was 0%).

asyncpg.Pool/Connection are faked with the same in-process test double used
across the persistence test suite: records exact SQL + params, returns
canned rows, so tests assert on emitted SQL/params, not just "didn't raise".
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from maistro.persistence.pg_audit import PgAuditLog
from maistro.security.sentinel.integrity import (
    DecisionSignature,
    DecisionSigner,
    IntegrityStatus,
    inspect_decision,
)
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
        "",
        "",  # team_id getattr default
        "a1",
        "bash",
        "allowed",
        "ok",
        "t1",
        "r1",
        "",
        "u1",
        "",
        "",
        None,
        None,
        None,
        None,
        "[]",
        "",
        entry.timestamp,
    )


@pytest.mark.asyncio
async def test_log_binds_the_signed_timestamp_instead_of_the_column_default(
    log: PgAuditLog, conn: FakeConnection
) -> None:
    """``audit_log.timestamp`` defaults to ``now()``.

    The timestamp is inside the signed contract, so a row that lets the default
    stand can never re-verify after reload. Binding the entry's own timestamp —
    and normalizing a naive one to UTC rather than letting the server's timezone
    decide — is what makes a durable PG record verifiable at all.
    """
    stamp = datetime(2024, 5, 1, 12, 30, 45, 123456, tzinfo=UTC)
    await log.log(AuditEntry(boundary="policy.decision", user_id="u1", timestamp=stamp))
    call = conn.calls[0]
    assert "timestamp" in call.query.split("VALUES")[0]
    assert call.args[-1] == stamp

    naive = datetime(2024, 5, 1, 12, 30, 45, 123456)
    await log.log(AuditEntry(boundary="policy.decision", user_id="u1", timestamp=naive))
    bound = conn.calls[1].args[-1]
    assert bound == stamp
    assert bound.tzinfo is not None


@pytest.mark.asyncio
async def test_log_persists_inputs_hash_and_public_verification_material(
    log: PgAuditLog, conn: FakeConnection
) -> None:
    """#69: the hash the signature covers must survive the write, or a reloaded
    row cannot be re-verified no matter what keyring the reader holds."""
    entry = AuditEntry(
        boundary="policy.decision",
        user_id="u1",
        action="deploy",
        timestamp=datetime(2024, 1, 1, tzinfo=UTC),
        inputs_hash="deadbeef",
        integrity=DecisionSignature(
            key_id="sentinel-abc",
            algorithm="Ed25519",
            signature="sig",
            public_key="pub",
        ),
    )
    await log.log(entry)
    call = conn.calls[0]
    assert "inputs_hash" in call.query
    assert call.args[-2] == "deadbeef"
    assert call.args[-1] == entry.timestamp
    assert call.args[13:17] == ("", "sig", "sentinel-abc", "Ed25519")
    assert call.args[17] == "pub"


@pytest.mark.asyncio
async def test_get_entries_rebuilds_the_signed_verification_contract(
    log: PgAuditLog, conn: FakeConnection
) -> None:
    """Reload must restore every signed field, including the inputs hash."""
    conn.queue_fetch(
        [
            {
                "timestamp": datetime(2024, 1, 1, tzinfo=UTC),
                "boundary": "policy.decision",
                "user_id": "u1",
                "action": "deploy",
                "policy_snapshot": '{"permission_table":{"deploy":["admin"]}}',
                "payload": '{"authorized":true}',
                "inputs_hash": "deadbeef",
                "signature": "sig",
                "signature_key_id": "sentinel-abc",
                "signature_algorithm": "Ed25519",
                "signature_public_key": "pub",
            }
        ]
    )
    entry = (await log.get_entries())[0]
    assert entry.inputs_hash == "deadbeef"
    assert entry.integrity is not None
    assert entry.integrity.key_id == "sentinel-abc"


@pytest.mark.asyncio
async def test_get_entries_unsigned_history_row_carries_no_verification_material(
    log: PgAuditLog, conn: FakeConnection
) -> None:
    """A pre-signing historical row reloads with ``integrity is None`` so the
    reader can label it unverifiable instead of presenting it as signed."""
    conn.queue_fetch([{"timestamp": datetime(2024, 1, 1, tzinfo=UTC), "signature": None}])
    entry = (await log.get_entries())[0]
    assert entry.integrity is None
    assert inspect_decision(entry) is IntegrityStatus.UNSIGNED


@pytest.mark.asyncio
async def test_log_tool_name_none_becomes_empty_string(
    log: PgAuditLog, conn: FakeConnection
) -> None:
    entry = AuditEntry(boundary="b", user_id="u", agent_id="a", tool_name=None)
    await log.log(entry)
    call = conn.calls[0]
    assert call.args[5] == ""


@pytest.mark.asyncio
async def test_log_team_id_passthrough_when_present(log: PgAuditLog, conn: FakeConnection) -> None:
    entry = AuditEntry(boundary="b", user_id="u", team_id="team-9", agent_id="a")
    await log.log(entry)
    call = conn.calls[0]
    assert call.args[3] == "team-9"


@pytest.mark.asyncio
async def test_get_entries_no_filters_uses_where_true(
    log: PgAuditLog, conn: FakeConnection
) -> None:
    conn.queue_fetch([])
    await log.get_entries()
    call = conn.calls[0]
    assert "WHERE TRUE" in call.query
    assert call.args == (100,)


@pytest.mark.asyncio
async def test_get_entries_user_id_filter_builds_param(
    log: PgAuditLog, conn: FakeConnection
) -> None:
    conn.queue_fetch([])
    await log.get_entries(user_id="u1", limit=5)
    call = conn.calls[0]
    assert "user_id = $1" in call.query
    assert "LIMIT $2" in call.query
    assert call.args == ("u1", 5)


@pytest.mark.asyncio
async def test_get_entries_both_filters_combined_with_and(
    log: PgAuditLog, conn: FakeConnection
) -> None:
    conn.queue_fetch([])
    await log.get_entries(user_id="u1", agent_id="a1")
    call = conn.calls[0]
    assert "user_id = $1 AND agent_id = $2" in call.query
    assert call.args == ("u1", "a1", 100)


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
    entries = await log.get_entries(user_id="u1")
    assert len(entries) == 1
    e = entries[0]
    assert isinstance(e, AuditEntry)
    assert e.timestamp == ts
    assert e.boundary == "tool_call"
    assert e.user_id == "u1"
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
    assert e.team_id == ""
    assert e.agent_id == ""
    assert e.tool_name is None
    assert e.verdict == "allowed"
    assert e.detail == ""
    assert e.trace_id == ""
    assert e.request_id == ""


def test_allowed_filter_columns_is_exactly_user_and_agent_id() -> None:
    from maistro.persistence.pg_audit import _ALLOWED_FILTER_COLUMNS

    assert frozenset({"user_id", "agent_id"}) == _ALLOWED_FILTER_COLUMNS


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


def _row_as_stored(query: str, args: tuple[Any, ...]) -> dict[str, Any]:
    """Mirror what the database would hand back for the columns we wrote.

    The double deliberately derives the row from the emitted INSERT's own column
    list: a signed field that is never written cannot come back, and the
    verification assertion below fails. That is the property the fake-asyncpg
    suite was blind to when ``timestamp`` silently fell through to the column's
    ``now()`` default.
    """
    head = query.split("VALUES")[0]
    columns = [c.strip() for c in head[head.index("(") + 1 : head.rindex(")")].split(",")]
    assert len(columns) == len(args), (columns, args)
    return dict(zip(columns, args, strict=True))


@pytest.mark.asyncio
async def test_a_signed_decision_survives_the_write_and_reverifies(log, conn) -> None:
    """#69: every field the signature covers must be persisted for the PG store.

    Sign with the real signer, write, read the row back, and verify — the check
    a reviewer can run against a production audit table.
    """
    signer = DecisionSigner()
    entry = AuditEntry(
        boundary="policy.decision",
        user_id="owner-1",
        principal_id="owner-1",
        org_id="org-1",
        team_id="team-1",
        agent_id="agent-1",
        action="deploy",
        tool_name="deploy",
        verdict="denied",
        detail="over budget",
        policy_snapshot='{"permission_table":{"deploy":["admin"]}}',
        payload='{"authorized":false}',
        inputs_hash="3f7868f23fd7ecf0",
    )
    entry = replace(entry, integrity=signer.sign(entry))
    await log.log(entry)
    conn.queue_fetch([_row_as_stored(*[(c.query, c.args) for c in conn.calls][-1])])

    stored = (await log.get_entries(user_id="owner-1"))[0]
    assert stored.integrity == entry.integrity
    assert inspect_decision(stored, trusted_keys=signer.keyring) is IntegrityStatus.VERIFIED
    assert inspect_decision(stored) is IntegrityStatus.VERIFIED

    tampered = replace(stored, timestamp=stored.timestamp.replace(year=2030))
    assert inspect_decision(tampered, trusted_keys=signer.keyring) is (
        IntegrityStatus.INVALID_SIGNATURE
    )
