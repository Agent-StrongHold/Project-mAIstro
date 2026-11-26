"""Tests for maistro.security.sentinel.audit — InMemoryAuditLog."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime

import pytest

from maistro.security._types import AuditEntry
from maistro.security.sentinel.audit import (
    InMemoryAuditLog,
    log_scoped_tool_denial,
)
from maistro.security.sentinel.signing import (
    AuditSignatureError,
    AuditSigner,
    canonical_audit_bytes,
)


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
    async def test_pre_sentinel_tool_denial_is_retained_and_signed(self) -> None:
        """The allowlist refusal survives the signing merge as scoped evidence."""

        @dataclass
        class _Auth:
            user_id: str = "user-1"
            org_id: str = "org-1"

        log = InMemoryAuditLog(signer=AuditSigner(b"k" * 32))
        await log_scoped_tool_denial(
            log,
            tool_name="undeclared_tool",
            reason="tool is outside the effective allowlist",
            auth=_Auth(),
            agent_name="agent-1",
        )

        [stored] = await log.get_entries(org_id="org-1")
        assert stored.boundary == "tool_allowlist"
        assert stored.verdict == "denied"
        assert stored.action == "tool_dispatch"
        assert stored.tool_name == "undeclared_tool"
        assert stored.detail == "tool is outside the effective allowlist"
        assert (stored.user_id, stored.org_id, stored.agent_id) == ("user-1", "org-1", "agent-1")
        assert log.verify(stored)
        assert await log.get_entries() == []

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


class TestCanonicalAuditBytes:
    """The canonical bytes are the proof's coverage contract: deterministic,
    proof-field-free at every nesting depth, and normalized so records that
    describe the same decision carry the same evidence."""

    def test_non_dataclass_entry_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="dataclasses"):
            canonical_audit_bytes({"boundary": "tool_call"})  # type: ignore[arg-type]

    def test_empty_legacy_verdict_is_normalized_to_allowed(self) -> None:
        """Rows persisted before the verdict vocabulary settled store ''. The
        proof must read that as the `allowed` decision it meant, so a legacy
        row and a modern row describing the same decision produce identical
        canonical bytes — and verify identically under the same key."""
        signer = AuditSigner(b"k" * 32)
        legacy = AuditEntry(boundary="tool_call", user_id="u1", verdict="")
        modern = AuditEntry(boundary="tool_call", user_id="u1", verdict="allowed")

        assert canonical_audit_bytes(legacy) == canonical_audit_bytes(modern)
        assert signer.sign(legacy).signature == signer.sign(modern).signature
        assert signer.verify(signer.sign(legacy))

    def test_rich_value_types_canonicalize_deterministically(self) -> None:
        """The canonicalizer must be total over value shapes a decision can
        carry: datetimes serialize, tuples become lists (JSON has no tuple),
        nested dataclasses drop proof fields at every depth, and dict keys
        sort so insertion order cannot change the bytes."""

        @dataclass
        class _Nested:
            name: str
            signature: str = "must-never-reach-the-bytes"

        @dataclass
        class _Rich:
            moment: datetime
            tags: tuple[str, ...]
            nested: _Nested
            meta: dict[str, str]

        first = _Rich(
            datetime(2026, 1, 1, tzinfo=UTC),
            ("deny", "egress"),
            _Nested("child"),
            {"zebra": "2", "alpha": "1"},
        )
        second = _Rich(
            datetime(2026, 1, 1, tzinfo=UTC),
            ("deny", "egress"),
            _Nested("child", "a-different-proof"),
            {"alpha": "1", "zebra": "2"},
        )

        payload = json.loads(canonical_audit_bytes(first))
        assert payload["moment"] == "2026-01-01T00:00:00+00:00"
        assert payload["tags"] == ["deny", "egress"]
        assert payload["nested"] == {"name": "child"}
        assert list(payload["meta"]) == ["alpha", "zebra"]
        assert canonical_audit_bytes(first) == canonical_audit_bytes(second)


class TestAuditSignerMutableEntries:
    def test_mutable_entry_is_signed_in_place_preserving_identity(self) -> None:
        """The historical Sentinel entry type is mutable; signing it must keep
        the caller's object identity (the documented contract) rather than
        silently swapping in a copy, because callers compose the proof onto a
        record they may still hold."""

        @dataclass
        class _MutableEntry:
            boundary: str
            user_id: str
            verdict: str = "allowed"
            signature: str = ""
            signing_key_id: str = ""
            proof_type: str = ""

        signer = AuditSigner(b"k" * 32)
        entry = _MutableEntry(boundary="tool_call", user_id="u1")

        assert signer.sign(entry) is entry
        assert entry.signature
        assert entry.proof_type == "Ed25519Signature2020"
        assert signer.verify(entry)


class TestVerifyRejectsIncompleteProofs:
    """verify() must refuse records whose proof is present-but-wrong, not
    only records whose decision bytes were tampered with."""

    @pytest.mark.asyncio
    async def test_wrong_proof_type_is_rejected(self) -> None:
        log = InMemoryAuditLog(signer=AuditSigner(b"k" * 32))
        await log.log(AuditEntry(boundary="tool_call", user_id="u1"))
        [stored] = await log.get_entries()

        assert not log.verify(replace(stored, proof_type="JsonWebSignature2020"))

    @pytest.mark.asyncio
    async def test_missing_signature_is_rejected(self) -> None:
        log = InMemoryAuditLog(signer=AuditSigner(b"k" * 32))
        await log.log(AuditEntry(boundary="tool_call", user_id="u1"))
        [stored] = await log.get_entries()

        assert not log.verify(replace(stored, signature=""))
