"""Signed Sentinel decision records and key rotation (issue #69)."""

from __future__ import annotations

from dataclasses import replace

import aiosqlite
import pytest

from maistro.persistence.sqlite_audit import SqliteAuditLog
from maistro.security._types import AuditEntry
from maistro.security.sentinel.authz_types import Principal
from maistro.security.sentinel.integrity import DecisionSigner, verify_decision
from maistro.security.sentinel.policy import Sentinel


class _CleanWarden:
    async def scan(self, text: str, boundary: str):
        from maistro.security._types import WardenVerdict

        return WardenVerdict(clean=True)


class _Audit:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    async def log(self, entry: AuditEntry) -> None:
        self.entries.append(entry)


@pytest.fixture
def signed_entry() -> tuple[DecisionSigner, AuditEntry]:
    signer = DecisionSigner()
    entry = AuditEntry(
        boundary="policy.decision",
        user_id="owner-1",
        action="deploy",
        principal_id="owner-1",
        verdict="allowed",
        policy_snapshot='{"permission_table":{"deploy":["admin"]}}',
        payload='{"authorized":true}',
    )
    entry.integrity = signer.sign(entry)
    return signer, entry


def test_mutating_payload_identity_timestamp_or_policy_invalidates_signature(
    signed_entry: tuple[DecisionSigner, AuditEntry],
) -> None:
    signer, entry = signed_entry
    assert signer.verify(entry)
    assert verify_decision(entry)

    for mutation in (
        {"payload": '{"authorized":false}'},
        {"user_id": "attacker"},
        {"timestamp": entry.timestamp.replace(year=entry.timestamp.year + 1)},
        {"policy_snapshot": '{"permission_table":{}}'},
    ):
        assert not signer.verify(replace(entry, **mutation))
        assert not verify_decision(replace(entry, **mutation))


def test_rotation_keeps_retired_keys_verifiable(
    signed_entry: tuple[DecisionSigner, AuditEntry],
) -> None:
    signer, old_entry = signed_entry
    old_key_id = signer.active_key_id
    new_key_id = signer.rotate()
    assert old_key_id != new_key_id
    assert len(signer.verification_history) == 2
    assert signer.verify(old_entry)

    new_entry = replace(old_entry, timestamp=old_entry.timestamp.replace(year=2027))
    new_entry.integrity = signer.sign(new_entry)
    assert new_entry.integrity.key_id == new_key_id
    assert signer.verify(new_entry)


@pytest.mark.asyncio
async def test_authorize_product_path_returns_and_persists_signed_decision() -> None:
    audit = _Audit()
    sentinel = Sentinel(
        warden=_CleanWarden(),
        permission_table={"deploy": frozenset({"admin"})},
        audit_log=audit,
    )
    decision = await sentinel.authorize("deploy", Principal("owner-1", "human", ("admin",)))

    assert decision.authorized
    assert decision.integrity is not None
    assert len(audit.entries) == 1
    record = audit.entries[0]
    assert record.boundary == "policy.decision"
    assert record.policy_snapshot
    assert record.integrity == decision.integrity
    assert verify_decision(record)
    assert not verify_decision(replace(record, user_id="attacker"))


@pytest.mark.asyncio
async def test_sqlite_audit_roundtrip_preserves_public_verification_material() -> None:
    audit = _Audit()
    sentinel = Sentinel(
        warden=_CleanWarden(),
        permission_table={"deploy": frozenset({"admin"})},
        audit_log=audit,
    )
    await sentinel.authorize("deploy", Principal("owner-1", "human", ("admin",)))

    connection = await aiosqlite.connect(":memory:")
    try:
        durable = SqliteAuditLog(connection)
        await durable.ensure_schema()
        await durable.log(audit.entries[0])
        stored = (await durable.get_entries())[0]
        assert stored.integrity == audit.entries[0].integrity
        assert verify_decision(stored)
    finally:
        await connection.close()


def test_public_material_does_not_expose_signing_private_key(
    signed_entry: tuple[DecisionSigner, AuditEntry],
) -> None:
    _, entry = signed_entry
    assert entry.integrity is not None
    assert not hasattr(entry.integrity, "private_key")
    assert "private" not in entry.integrity.public_key.lower()
