"""Tests for maistro.security.sentinel.audit — InMemoryAuditLog."""

from __future__ import annotations

import base64
from dataclasses import replace

import pytest

from maistro.security._types import AuditEntry
from maistro.security.sentinel.audit import InMemoryAuditLog
from maistro.security.sentinel.signing import AuditSignatureError, AuditSigner


def _without_proof(entry: AuditEntry) -> AuditEntry:
    """Strip the ADR-073 proof fields so a retained record compares equal to
    the entry the caller passed to ``log``. Records are frozen, and the store
    attaches the proof to the retained copy, not the caller's object."""
    return replace(entry, signature="", signing_key_id="", proof_type="")


class TestInMemoryAuditLog:
    @pytest.mark.asyncio
    async def test_log_appends_entry(self) -> None:
        log = InMemoryAuditLog()
        entry = AuditEntry(boundary="tool_call", user_id="u1")
        await log.log(entry)
        entries = await log.get_entries()
        assert [_without_proof(e) for e in entries] == [entry]

    @pytest.mark.asyncio
    async def test_get_entries_returns_reverse_chronological(self) -> None:
        log = InMemoryAuditLog()
        first = AuditEntry(boundary="b1", user_id="u1")
        second = AuditEntry(boundary="b2", user_id="u1")
        await log.log(first)
        await log.log(second)
        entries = await log.get_entries()
        assert [_without_proof(e) for e in entries] == [second, first]

    @pytest.mark.asyncio
    async def test_filters_by_user_id(self) -> None:
        log = InMemoryAuditLog()
        e1 = AuditEntry(boundary="b", user_id="u1")
        e2 = AuditEntry(boundary="b", user_id="u2")
        await log.log(e1)
        await log.log(e2)
        entries = await log.get_entries(user_id="u1")
        assert [_without_proof(e) for e in entries] == [e1]

    @pytest.mark.asyncio
    async def test_filters_by_agent_id(self) -> None:
        log = InMemoryAuditLog()
        e1 = AuditEntry(boundary="b", user_id="u1", agent_id="a1")
        e2 = AuditEntry(boundary="b", user_id="u1", agent_id="a2")
        await log.log(e1)
        await log.log(e2)
        entries = await log.get_entries(agent_id="a1")
        assert [_without_proof(e) for e in entries] == [e1]

    @pytest.mark.asyncio
    async def test_filters_by_org_id(self) -> None:
        log = InMemoryAuditLog()
        e1 = AuditEntry(boundary="b", user_id="u1", org_id="org-a")
        e2 = AuditEntry(boundary="b", user_id="u1", org_id="org-b")
        await log.log(e1)
        await log.log(e2)
        entries = await log.get_entries(org_id="org-a")
        assert [_without_proof(e) for e in entries] == [e1]

    @pytest.mark.asyncio
    async def test_default_read_is_system_scope_only(self) -> None:
        log = InMemoryAuditLog()
        tenant = AuditEntry(boundary="tenant", user_id="u1", org_id="org-a")
        system = AuditEntry(boundary="system", user_id="u1")
        await log.log(tenant)
        await log.log(system)

        assert [_without_proof(e) for e in await log.get_entries()] == [system]

    @pytest.mark.asyncio
    async def test_rejects_ambiguous_scope(self) -> None:
        with pytest.raises(ValueError, match="pass '' for an unscoped read"):
            await InMemoryAuditLog().get_entries(org_id=None)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_respects_limit(self) -> None:
        log = InMemoryAuditLog()
        for i in range(5):
            await log.log(AuditEntry(boundary="b", user_id=f"u{i}"))
        entries = await log.get_entries(limit=2)
        assert len(entries) == 2

    @pytest.mark.asyncio
    async def test_no_entries_returns_empty_list(self) -> None:
        log = InMemoryAuditLog()
        assert await log.get_entries() == []

    @pytest.mark.asyncio
    async def test_decisions_are_signed_and_tampering_is_rejected(self) -> None:
        log = InMemoryAuditLog(signer=AuditSigner(b"k" * 32))
        entry = AuditEntry(boundary="tool_call", user_id="u1", verdict="denied")

        await log.log(entry)
        [stored] = await log.get_entries()

        assert stored.signature
        assert stored.proof_type == "Ed25519Signature2020"
        assert stored.signing_key_id == log.signer.key_id
        assert log.verify(stored)

        # Records are frozen: tampering is modeled the way the durable stores
        # model it (see test_sqlite/test_pg_audit) — a replaced copy of the
        # retained row whose decision bytes differ.
        forged = replace(stored, detail="forged")
        assert not log.verify(forged)

    @pytest.mark.asyncio
    async def test_a_different_key_cannot_verify_a_decision(self) -> None:
        first = InMemoryAuditLog(signer=AuditSigner(b"a" * 32))
        second = InMemoryAuditLog(signer=AuditSigner(b"b" * 32))
        entry = AuditEntry(boundary="tool_call", user_id="u1")

        await first.log(entry)
        [stored] = await first.get_entries()

        assert first.verify(stored)
        assert not second.verify(stored)


class TestAuditSignerFromEnvironment:
    """MAISTRO_AUDIT_SIGNING_KEY is the deployment contract for verifying
    durable proofs after a restart; the seed parser must accept every
    documented spelling and reject everything else loudly."""

    def test_missing_key_generates_an_ephemeral_signer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MAISTRO_AUDIT_SIGNING_KEY", raising=False)
        signer = AuditSigner.from_environment()

        assert signer.ephemeral is True

    def test_base64url_seed_is_accepted_and_reproduces_the_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seed = b"s" * 32
        monkeypatch.setenv(
            "MAISTRO_AUDIT_SIGNING_KEY", base64.urlsafe_b64encode(seed).decode("ascii")
        )

        signer = AuditSigner.from_environment()

        assert signer.ephemeral is False
        assert signer.key_id == AuditSigner(seed).key_id
        assert signer.public_key == AuditSigner(seed).public_key

    def test_hex_seed_is_accepted_and_reproduces_the_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seed = bytes(range(32))
        monkeypatch.setenv("MAISTRO_AUDIT_SIGNING_KEY", seed.hex())

        signer = AuditSigner.from_environment()

        assert signer.ephemeral is False
        assert signer.key_id == AuditSigner(seed).key_id

    def test_malformed_seed_is_rejected_loudly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAISTRO_AUDIT_SIGNING_KEY", "not-a-key!!")

        with pytest.raises(AuditSignatureError):
            AuditSigner.from_environment()

    def test_wrong_length_seed_is_rejected_loudly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAISTRO_AUDIT_SIGNING_KEY", "00" * 31)

        with pytest.raises(AuditSignatureError):
            AuditSigner.from_environment()
