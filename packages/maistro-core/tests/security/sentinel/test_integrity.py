"""Tamper-evident Sentinel decision records and key rotation (issue #69, ADR-073).

Every case here is written against the guarantee the contract states: a record
that was signed stays verifiable from the durable store, and every protected
field — identity, scope, timestamp, policy snapshot, inputs hash, decision
payload, violations — fails verification the moment it is altered. Verification
is exercised in both modes the contract allows (embedded material, and a pinned
verification-key reference), because only the pinned mode resists a writer who
replaces the key as well as the signature.
"""

from __future__ import annotations

import base64
import dataclasses
import json
import subprocess
import sys
from dataclasses import replace

import aiosqlite
import pytest

from maistro.events.durable_log import InMemoryEventLog
from maistro.persistence.sqlite_audit import SqliteAuditLog
from maistro.security._types import AuditEntry, AuthContext, Violation, WardenVerdict
from maistro.security.sentinel.authz_types import Principal
from maistro.security.sentinel.elevation import hash_args
from maistro.security.sentinel.integrity import (
    DecisionSignature,
    DecisionSigner,
    IntegrityStatus,
    canonical_decision_payload,
    inspect_decision,
    verify_decision,
)
from maistro.security.sentinel.policy import Sentinel

PROTECTED_FIELDS = (
    "timestamp",
    "boundary",
    "user_id",
    "org_id",
    "team_id",
    "principal_id",
    "agent_id",
    "action",
    "tool_name",
    "verdict",
    "detail",
    "policy_snapshot",
    "payload",
    "inputs_hash",
    "violations",
)


class _CleanWarden:
    async def scan(self, text: str, boundary: str) -> WardenVerdict:
        return WardenVerdict(clean=True)


class _Audit:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    async def log(self, entry: AuditEntry) -> None:
        self.entries.append(entry)


def _sentinel(audit: _Audit, *, signer: DecisionSigner | None = None) -> Sentinel:
    return Sentinel(
        warden=_CleanWarden(),
        permission_table={"deploy": frozenset({"admin"})},
        audit_log=audit,
        integrity_signer=signer or DecisionSigner(),
    )


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _tamper(entry: AuditEntry, field: str) -> AuditEntry:
    """Alter exactly one protected field, leaving the embedded signature alone."""
    if field == "timestamp":
        return replace(entry, timestamp=entry.timestamp.replace(year=entry.timestamp.year + 4))
    if field == "inputs_hash":
        return replace(entry, inputs_hash=hash_args({"tampered": True}))
    if field == "violations":
        return replace(
            entry,
            violations=(
                Violation(
                    boundary=entry.boundary,
                    rule="forged",
                    severity="info",
                    detail="",
                ),
            ),
        )
    values: dict[str, object] = {
        "boundary": "post_call",
        "user_id": "attacker",
        "org_id": "other-org",
        "team_id": "other-team",
        "principal_id": "attacker",
        "agent_id": "rogue-agent",
        "action": "delete",
        "tool_name": "delete",
        "verdict": "denied" if entry.verdict != "denied" else "allowed",
        "detail": "rewritten reason",
        "policy_snapshot": "{}",
        "payload": '{"authorized":true}',
    }
    return replace(entry, **{field: values[field]})


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


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
        payload='{"authorized":false}',
    )
    entry = replace(entry, inputs_hash=hash_args({"path": "/srv/app"}))
    entry = replace(entry, integrity=signer.sign(entry))
    return signer, entry


def test_mutating_payload_identity_timestamp_or_policy_invalidates_signature(
    signed_entry: tuple[DecisionSigner, AuditEntry],
) -> None:
    signer, entry = signed_entry
    assert signer.verify(entry)
    assert verify_decision(entry)

    for field in ("payload", "user_id", "timestamp", "policy_snapshot"):
        mutated = _tamper(entry, field)
        assert not signer.verify(mutated), field
        assert not verify_decision(mutated), field


@pytest.mark.parametrize("field", PROTECTED_FIELDS)
def test_every_signed_field_is_protected(
    signed_entry: tuple[DecisionSigner, AuditEntry],
    field: str,
) -> None:
    """AC-2: no protected field may be altered without verification failing."""
    signer, entry = signed_entry
    mutated = _tamper(entry, field)
    assert inspect_decision(mutated) is IntegrityStatus.INVALID_SIGNATURE, field
    assert not signer.verify(mutated), field
    assert not verify_decision(mutated), field
    assert not verify_decision(mutated, trusted_keys=signer.keyring), field


def test_signed_field_list_covers_the_canonical_payload(
    signed_entry: tuple[DecisionSigner, AuditEntry],
) -> None:
    """The signed contract's field set is stated, not implied by formatting.

    A field added to ``canonical_decision_payload`` without a case in
    :data:`PROTECTED_FIELDS` fails here instead of silently going untested.
    """
    _, entry = signed_entry
    payload = json.loads(canonical_decision_payload(entry))
    assert set(payload["identity"]) == {
        "user_id",
        "org_id",
        "team_id",
        "principal_id",
        "agent_id",
    }
    signed_fields = (set(payload) - {"identity"}) | set(payload["identity"])
    # ``schema`` is the contract version, not a decision field an editor can
    # meaningfully retarget, so it is signed but has no tamper case.
    assert signed_fields == set(PROTECTED_FIELDS) | {"schema"}
    assert "integrity" not in payload, "the signature must never sign itself"


def test_invalid_signature_bytes_are_rejected(
    signed_entry: tuple[DecisionSigner, AuditEntry],
) -> None:
    """A signature that is well-formed base64 but is not this record's signature."""
    signer, entry = signed_entry
    raw = bytearray(_unb64(entry.integrity.signature))
    raw[0] ^= 0x01
    forged = replace(
        entry,
        integrity=replace(
            entry.integrity,
            signature=base64.urlsafe_b64encode(bytes(raw)).rstrip(b"=").decode("ascii"),
        ),
    )
    assert inspect_decision(forged) is IntegrityStatus.INVALID_SIGNATURE
    assert not verify_decision(forged)
    assert not signer.verify(forged)
    assert not verify_decision(forged, trusted_keys=signer.keyring)

    garbage = replace(entry, integrity=replace(entry.integrity, signature="not-valid-base64_~"))
    assert inspect_decision(garbage) is IntegrityStatus.INVALID_SIGNATURE


def test_unsupported_algorithm_is_not_a_signature(
    signed_entry: tuple[DecisionSigner, AuditEntry],
) -> None:
    _, entry = signed_entry
    other = replace(entry, integrity=replace(entry.integrity, algorithm="HS256"))
    assert inspect_decision(other) is IntegrityStatus.UNSUPPORTED_ALGORITHM
    assert not verify_decision(other)


def test_unknown_key_is_rejected_by_a_pinned_keyring(
    signed_entry: tuple[DecisionSigner, AuditEntry],
) -> None:
    """A record signed by a key the verifier does not trust never reads valid."""
    signer, entry = signed_entry
    foreign = DecisionSigner()
    assert inspect_decision(entry, trusted_keys=foreign.keyring) is IntegrityStatus.UNKNOWN_KEY
    assert not verify_decision(entry, trusted_keys=foreign.keyring)

    unused_reference = {"sentinel-not-issued": entry.integrity.public_key}
    assert inspect_decision(entry, trusted_keys=unused_reference) is IntegrityStatus.UNKNOWN_KEY

    pinned = dict(foreign.keyring)
    pinned.update(signer.keyring)
    assert inspect_decision(entry, trusted_keys=pinned) is IntegrityStatus.VERIFIED


def test_pinned_keyring_refuses_embedded_material_that_disagrees_with_the_reference(
    signed_entry: tuple[DecisionSigner, AuditEntry],
) -> None:
    """A row whose embedded key contradicts the pinned reference is not trusted.

    The verifier does not pick a winner between the two: disagreement is itself
    evidence the row was edited, so it fails closed as ``UNKNOWN_KEY``.
    """
    signer, entry = signed_entry
    rival = DecisionSigner()
    other_key = rival.keyring[rival.active_key_id]
    spoofed = replace(entry, integrity=replace(entry.integrity, public_key=other_key))

    assert inspect_decision(spoofed) is IntegrityStatus.INVALID_SIGNATURE
    assert not verify_decision(spoofed)
    assert inspect_decision(spoofed, trusted_keys=signer.keyring) is IntegrityStatus.UNKNOWN_KEY
    assert not verify_decision(spoofed, trusted_keys=signer.keyring)
    # The unaltered record still verifies under the same pinned reference.
    assert inspect_decision(entry, trusted_keys=signer.keyring) is IntegrityStatus.VERIFIED


def test_key_swap_forgery_fails_under_a_pinned_keyring(
    signed_entry: tuple[DecisionSigner, AuditEntry],
) -> None:
    """The threat ADR-073 names: a writer edits the record, re-signs it with a
    key they control, and replaces the embedded public key.

    Embedded material alone cannot detect it — the forged record is internally
    consistent — which is why the contract requires an independently trusted
    verification-key reference. The pinned keyring does detect it, and the
    retained verification history is what a reviewer pins against.
    """
    signer, entry = signed_entry
    attacker = DecisionSigner()
    forged = _tamper(entry, "user_id")
    forged = replace(forged, integrity=attacker.sign(forged))

    assert verify_decision(forged), "embedded verification is corruption-detection only"
    assert inspect_decision(forged, trusted_keys=signer.keyring) is IntegrityStatus.UNKNOWN_KEY
    assert not verify_decision(forged, trusted_keys=signer.keyring)


def test_unsigned_historical_record_is_labeled_unverifiable(
    signed_entry: tuple[DecisionSigner, AuditEntry],
) -> None:
    """Records written before signing landed read UNSIGNED, never VERIFIED, and
    are distinguished from tampered records so a report can say "unverifiable
    history" rather than "forged history"."""
    signer, entry = signed_entry
    unsigned = replace(entry, integrity=None)
    assert inspect_decision(unsigned) is IntegrityStatus.UNSIGNED
    assert inspect_decision(unsigned, trusted_keys=signer.keyring) is IntegrityStatus.UNSIGNED
    assert not verify_decision(unsigned)
    # The label is distinct from a tampered record, so unverifiable history is
    # never reported as forged history (and never as signed history).
    assert inspect_decision(_tamper(entry, "user_id")) is IntegrityStatus.INVALID_SIGNATURE


def test_unsigned_record_cannot_be_presented_as_signed(
    signed_entry: tuple[DecisionSigner, AuditEntry],
) -> None:
    """Retro-fitting a signature onto a historical row is caught by pinning."""
    signer, entry = signed_entry
    unsigned = replace(entry, integrity=None)
    attacker = DecisionSigner()
    unsigned = replace(unsigned, integrity=attacker.sign(unsigned))
    assert verify_decision(unsigned), "self-authenticated forgery"
    assert inspect_decision(unsigned, trusted_keys=signer.keyring) is IntegrityStatus.UNKNOWN_KEY


def test_rotation_keeps_retired_keys_verifiable(
    signed_entry: tuple[DecisionSigner, AuditEntry],
) -> None:
    signer, old_entry = signed_entry
    old_key_id = signer.active_key_id
    new_key_id = signer.rotate()
    assert old_key_id != new_key_id
    assert len(signer.verification_history) == 2
    assert signer.verify(old_entry)

    new_entry = replace(old_entry, payload='{"authorized":true}')
    new_entry = replace(new_entry, integrity=signer.sign(new_entry))
    assert new_entry.integrity.key_id == new_key_id
    assert signer.verify(new_entry)
    assert verify_decision(new_entry, trusted_keys=signer.keyring)
    # A verifier that pinned only the retired key cannot read the new record,
    # and a verifier that pinned only the active key cannot read the old one:
    # the history is what makes both readable, not a wildcard trust.
    assert inspect_decision(new_entry, trusted_keys={old_key_id: signer.keyring[old_key_id]}) is (
        IntegrityStatus.UNKNOWN_KEY
    )
    assert inspect_decision(old_entry, trusted_keys={new_key_id: signer.keyring[new_key_id]}) is (
        IntegrityStatus.UNKNOWN_KEY
    )


def test_rotation_history_is_public_material_only(
    signed_entry: tuple[DecisionSigner, AuditEntry],
) -> None:
    """Rotation retires a key without leaking what signed the older records.

    The retired private key is dropped from the signer's live material; only
    public verification keys are retained for history.
    """
    signer, entry = signed_entry
    retired = signer.active_key_id
    active = signer.rotate()

    assert {key.key_id for key in signer.verification_history} == {retired, active}
    assert set(signer.keyring) == {retired, active}
    assert all(len(_unb64(value)) == 32 for value in signer.keyring.values())
    assert list(signer._private_keys) == [active]
    assert retired not in signer._private_keys
    assert signer.verify(entry)


def test_record_exposes_no_signing_material(
    signed_entry: tuple[DecisionSigner, AuditEntry],
) -> None:
    """The audit record carries a public key and a signature — nothing a holder
    could sign further records with."""
    _, entry = signed_entry
    assert not hasattr(entry.integrity, "private_key")
    assert {field.name for field in dataclasses.fields(DecisionSignature)} == {
        "key_id",
        "algorithm",
        "signature",
        "public_key",
    }
    assert len(_unb64(entry.integrity.public_key)) == 32
    assert len(_unb64(entry.integrity.signature)) == 64
    assert entry.integrity.signature != entry.integrity.public_key


@pytest.mark.asyncio
async def test_authorize_product_path_returns_and_persists_signed_decision() -> None:
    audit = _Audit()
    signer = DecisionSigner()
    sentinel = _sentinel(audit, signer=signer)
    decision = await sentinel.authorize("deploy", Principal("owner-1", "human", ("admin",)))

    assert decision.authorized
    assert decision.integrity is not None
    assert decision.integrity.key_id == signer.active_key_id
    assert decision.integrity.public_key == signer.keyring[signer.active_key_id]
    assert len(audit.entries) == 1
    record = audit.entries[0]
    assert record.boundary == "policy.decision"
    assert record.verdict == "allowed"
    assert record.policy_snapshot
    assert record.integrity == decision.integrity
    assert verify_decision(record)
    assert inspect_decision(record, trusted_keys=signer.keyring) is IntegrityStatus.VERIFIED
    assert not verify_decision(_tamper(record, "user_id"))


@pytest.mark.asyncio
async def test_authorize_emits_canonical_policy_decision_event() -> None:
    """ADR-037 `policy.decision` is appended beside the signed audit record.

    The event must carry the same decision, inputs hash and public
    verification material as the record, so a reader can correlate the two
    without trusting a second source or reading a private key.
    """
    audit = _Audit()
    signer = DecisionSigner()
    events = InMemoryEventLog()
    sentinel = _sentinel(audit, signer=signer)
    sentinel.attach_event_log(events)

    decision = await sentinel.authorize(
        "deploy", Principal("owner-1", "human", ("admin",)), args={"change": "42"}
    )

    record = audit.entries[0]
    logged = await events.query(event_type="policy.decision")
    assert len(logged) == 1
    payload = logged[0].payload
    assert payload["policy_id"] == "maistro.sentinel"
    assert payload["decision"] == "allowed"
    assert payload["inputs_hash"] == record.inputs_hash == hash_args({"change": "42"})
    assert payload["action"] == "deploy"
    assert payload["principal_id"] == "owner-1"
    assert payload["integrity"]["key_id"] == signer.active_key_id
    assert payload["integrity"]["signature"] == decision.integrity.signature
    assert payload["integrity"]["public_key"] == signer.keyring[signer.active_key_id]


@pytest.mark.asyncio
async def test_pre_call_emits_policy_decision_event_for_gate_outcome() -> None:
    """The `pre_call` gate outcome is a decision too, and its event is durable.

    A reader can tell which boundary produced the event and which inputs the
    signed record covers, which is what lets the audit and event streams be
    reconciled after the fact.
    """
    audit = _Audit()
    signer = DecisionSigner()
    events = InMemoryEventLog()
    sentinel = Sentinel(
        warden=_CleanWarden(),
        permission_table={"tool": frozenset({"admin"})},
        audit_log=audit,
        integrity_signer=signer,
        event_log=events,
    )
    args = {"query": "gate inputs"}
    await sentinel.pre_call(
        "tool", args, AuthContext(user_id="u1", roles=frozenset({"admin"})), schema={}
    )

    logged = await events.query(event_type="policy.decision")
    assert len(logged) == 1
    assert logged[0].payload["boundary"] == "pre_call"
    assert logged[0].payload["inputs_hash"] == hash_args(args)
    assert logged[0].payload["integrity"]["key_id"] == signer.active_key_id


def test_signer_from_seed_is_stable_across_processes() -> None:
    """The deployment seed reproduces the same key id/public key after restart."""
    seed = _b64(b"\x01" * 32)
    first = DecisionSigner.from_seed_b64(seed)
    second = DecisionSigner.from_seed_b64(seed)
    assert first.active_key_id == second.active_key_id
    assert first.keyring == second.keyring

    entry = AuditEntry(boundary="policy.decision", user_id="u1", verdict="allowed")
    signed = first.sign(entry)
    reloaded = dataclasses.replace(entry, integrity=signed)
    assert inspect_decision(reloaded, trusted_keys=second.keyring) is IntegrityStatus.VERIFIED


def test_signer_from_seed_rejects_bad_material_without_echoing_it() -> None:
    for bad in ("not-base64!", _b64(b"short"), "", _b64(bytes(32)) + "!"):
        with pytest.raises(ValueError) as caught:
            DecisionSigner.from_seed_b64(bad)
        assert bad not in str(caught.value) or bad == ""


@pytest.mark.asyncio
async def test_denied_product_decision_is_signed_and_verifiable() -> None:
    """The denial path is a signed decision too, not only the happy path: a
    forged "authorized" written into a recorded denial is the point."""
    audit = _Audit()
    signer = DecisionSigner()
    sentinel = _sentinel(audit, signer=signer)
    decision = await sentinel.authorize("deploy", Principal("guest-1", "human", ("user",)))

    assert not decision.authorized
    assert decision.integrity is not None
    record = audit.entries[0]
    assert record.verdict == "denied"
    assert record.payload and record.policy_snapshot
    assert inspect_decision(record, trusted_keys=signer.keyring) is IntegrityStatus.VERIFIED

    flipped = replace(record, payload='{"authorized":true,"reason":""}')
    assert flipped.payload != record.payload
    assert inspect_decision(flipped) is IntegrityStatus.INVALID_SIGNATURE
    assert not verify_decision(flipped, trusted_keys=signer.keyring)


@pytest.mark.asyncio
async def test_pre_call_decision_binds_the_inputs_hash() -> None:
    """The signature covers the call's inputs, so a record cannot be replayed
    against different arguments."""
    audit = _Audit()
    signer = DecisionSigner()
    sentinel = Sentinel(
        warden=_CleanWarden(),
        permission_table={"tool": frozenset({"user"})},
        audit_log=audit,
        integrity_signer=signer,
    )
    args = {"query": "payload the caller actually sent"}
    verdict = await sentinel.pre_call(
        "tool", args, AuthContext(user_id="u1", roles=frozenset({"user"})), schema={}
    )

    assert verdict.allowed
    record = audit.entries[0]
    assert record.inputs_hash == hash_args(args)
    assert inspect_decision(record, trusted_keys=signer.keyring) is IntegrityStatus.VERIFIED
    replayed = replace(record, inputs_hash=hash_args({"query": "different call"}))
    assert inspect_decision(replayed) is IntegrityStatus.INVALID_SIGNATURE


@pytest.mark.asyncio
async def test_sqlite_audit_roundtrip_preserves_public_verification_material() -> None:
    audit = _Audit()
    signer = DecisionSigner()
    sentinel = _sentinel(audit, signer=signer)
    await sentinel.authorize("deploy", Principal("owner-1", "human", ("admin",)))

    connection = await aiosqlite.connect(":memory:")
    try:
        durable = SqliteAuditLog(connection)
        await durable.ensure_schema()
        await durable.log(audit.entries[0])
        stored = (await durable.get_entries())[0]
        assert stored.integrity == audit.entries[0].integrity
        assert stored.inputs_hash == audit.entries[0].inputs_hash
        assert stored.verdict == audit.entries[0].verdict
        assert verify_decision(stored)
        assert inspect_decision(stored, trusted_keys=signer.keyring) is IntegrityStatus.VERIFIED
        assert not verify_decision(_tamper(stored, "policy_snapshot"))
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_durable_roundtrip_verifies_allowed_and_denied_then_fails_on_every_field() -> None:
    """#69 completion evidence: exercise a real allowed and a real denied
    decision, persist and reload them, verify, then alter each protected field
    on the reloaded row and require failure."""
    audit = _Audit()
    signer = DecisionSigner()
    sentinel = _sentinel(audit, signer=signer)
    allowed = await sentinel.authorize("deploy", Principal("owner-1", "human", ("admin",)))
    denied = await sentinel.authorize("deploy", Principal("guest-1", "human", ("user",)))
    assert allowed.authorized and not denied.authorized
    assert len(audit.entries) == 2

    connection = await aiosqlite.connect(":memory:")
    try:
        durable = SqliteAuditLog(connection)
        await durable.ensure_schema()
        for entry in audit.entries:
            await durable.log(entry)
        stored = await durable.get_entries()
        assert len(stored) == 2
        by_verdict = {row.verdict: row for row in stored}
        assert set(by_verdict) == {"allowed", "denied"}

        for verdict, decision in (("allowed", allowed), ("denied", denied)):
            row = by_verdict[verdict]
            assert row.integrity == decision.integrity
            assert inspect_decision(row, trusted_keys=signer.keyring) is IntegrityStatus.VERIFIED
            for field in PROTECTED_FIELDS:
                tampered = _tamper(row, field)
                assert inspect_decision(tampered) is IntegrityStatus.INVALID_SIGNATURE, (
                    verdict,
                    field,
                )
                assert not verify_decision(tampered, trusted_keys=signer.keyring), (verdict, field)
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_durable_store_keeps_unsigned_history_labeled_unsigned() -> None:
    """A row written before signing existed reloads with no verification
    material, reads UNSIGNED, and never reads as signed."""
    connection = await aiosqlite.connect(":memory:")
    try:
        durable = SqliteAuditLog(connection)
        await durable.ensure_schema()
        historical = AuditEntry(boundary="policy.decision", user_id="u1", verdict="allowed")
        assert historical.integrity is None
        await durable.log(historical)

        stored = (await durable.get_entries())[0]
        assert stored.integrity is None
        assert inspect_decision(stored) is IntegrityStatus.UNSIGNED
        assert not verify_decision(stored)
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_store_survives_rotation_and_holds_no_private_material() -> None:
    """Records signed under a retired key stay verifiable from the durable
    store, and nothing written to the store is signing material."""
    audit = _Audit()
    signer = DecisionSigner()
    sentinel = _sentinel(audit, signer=signer)
    await sentinel.authorize("deploy", Principal("owner-1", "human", ("admin",)))
    retired = signer.active_key_id
    signer.rotate()

    connection = await aiosqlite.connect(":memory:")
    try:
        durable = SqliteAuditLog(connection)
        await durable.ensure_schema()
        await durable.log(audit.entries[0])
        stored = (await durable.get_entries())[0]
        assert stored.integrity.key_id == retired
        assert inspect_decision(stored, trusted_keys=signer.keyring) is IntegrityStatus.VERIFIED

        cursor = await connection.execute("SELECT * FROM audit_log")
        columns = [d[0] for d in cursor.description]
        await cursor.close()
        assert not any("private" in c for c in columns)
        assert {
            "decision_signature",
            "signature_key_id",
            "signature_algorithm",
            "signature_public_key",
        } <= set(columns)
    finally:
        await connection.close()


def _block_cryptography_and_import(modules: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    """Import ``modules`` in a child interpreter where ``cryptography`` is absent.

    Subprocess isolation is the point, for the same reason as
    ``tests/auth/test_mandatory_verification.py``: inside this suite's interpreter
    the modules are already loaded, so an in-process patch proves nothing.
    """
    statement = (
        "import sys\n"
        "_BLOCKED = ['cryptography']\n"
        "class _Blocked:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] in _BLOCKED:\n"
        "            raise ModuleNotFoundError(f'blocked: {name}', name=name)\n"
        "        return None\n"
        "sys.meta_path.insert(0, _Blocked())\n"
        + "".join(f"import {module}\n" for module in modules)
        + "print('IMPORTED')\n"
    )
    return subprocess.run(  # fixed argv, no shell
        [sys.executable, "-c", statement],
        capture_output=True,
        text=True,
        check=False,
    )


def test_record_types_do_not_make_crypto_an_import_time_dependency() -> None:
    """A mirrored ``AuditEntry`` carries the signature material, and those type
    modules are imported across the whole package graph — so they must not drag
    the Ed25519 backend in with them. Letting ``maistro.types.security`` import
    the sentinel implementation is what broke #856's guarantee that removing
    ``cryptography`` fails closed in the OIDC path with an actionable error."""
    result = _block_cryptography_and_import(
        (
            "maistro.types.security",
            "maistro.security._types",
            "maistro.security.integrity_types",
            "maistro.auth.oauth",
        )
    )
    assert result.returncode == 0, result.stderr
    assert "IMPORTED" in result.stdout


def test_signing_still_requires_the_crypto_backend() -> None:
    """Hiding the import from the type modules must not hide it from the signer:
    using it without the backend fails loudly, it never degrades to unsigned."""
    result = _block_cryptography_and_import(("maistro.security.sentinel.integrity",))
    assert result.returncode != 0
    assert "blocked: cryptography" in result.stderr or "cryptography" in result.stderr
    assert "IMPORTED" not in result.stdout


def test_verification_material_type_is_one_type_across_import_paths() -> None:
    """Re-exports must not fork the type, or ``isinstance`` checks and stores
    would disagree depending on how a caller got there."""
    from maistro.security.integrity_types import DecisionSignature as Leaf
    from maistro.security.sentinel import DecisionSignature as Package
    from maistro.types.security import DecisionSignature as TypesTwin

    assert Leaf is DecisionSignature is Package is TypesTwin


def test_reinstalling_the_active_key_does_not_destroy_the_signer() -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    signer = DecisionSigner(key)
    original = signer.active_key_id
    assert signer.rotate(key) == original
    entry = AuditEntry(user_id="u1")
    assert signer.verify(replace(entry, integrity=signer.sign(entry)))
    assert len(signer.verification_history) == 1


@pytest.mark.parametrize("invalid", ("depth", "cycle", "non_json"))
@pytest.mark.asyncio
async def test_rejected_arguments_do_not_crash_decision_signing(invalid: str) -> None:
    """The audit hash must not defeat the resource gate it is documenting."""
    if invalid == "non_json":
        args = {"value": object()}
    elif invalid == "cycle":
        args = {}
        args["self"] = args
    else:
        args = {}
        for _ in range(1200):
            args = {"nested": args}
    audit = _Audit()
    sentinel = _sentinel(audit)
    decision = await sentinel.pre_call(
        "deploy", args, AuthContext(user_id="u1", roles=frozenset({"admin"})), {}
    )
    assert not decision.allowed
    record = audit.entries[0]
    assert record.verdict == "denied" and record.violations
    assert record.inputs_hash == ""  # explicitly unavailable, not a fake digest
    assert verify_decision(record, trusted_keys=sentinel.verification_keyring)


@pytest.mark.parametrize("missing", ("key_id", "public_key", "signature"))
def test_missing_verification_material_never_verifies(signed_entry, missing: str) -> None:
    signer, entry = signed_entry
    damaged = replace(entry, integrity=replace(entry.integrity, **{missing: ""}))
    assert not verify_decision(damaged, trusted_keys=signer.keyring)


@pytest.mark.asyncio
async def test_real_pg_decisions_preserve_both_proofs_and_reject_all_mutations(pg_pool) -> None:
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    from maistro.persistence.pg_audit import PgAuditLog

    durable = PgAuditLog(pg_pool)
    signer = DecisionSigner()
    sentinel = Sentinel(
        warden=_CleanWarden(),
        permission_table={"deploy": frozenset({"admin"})},
        audit_log=durable,
        integrity_signer=signer,
    )
    allowed = await sentinel.authorize(
        "deploy", Principal("owner", "human", ("admin",)), args={"token": "never-store-this"}
    )
    denied = await sentinel.authorize("deploy", Principal("guest", "human", ("user",)))
    assert allowed.authorized and not denied.authorized
    stored = await durable.get_entries()
    assert {row.verdict for row in stored} == {"allowed", "denied"}
    for row in stored:
        assert durable.verify(row), "the pre-existing store proof must still verify"
        assert inspect_decision(row, trusted_keys=signer.keyring) is IntegrityStatus.VERIFIED
        for field in PROTECTED_FIELDS:
            assert not verify_decision(_tamper(row, field), trusted_keys=signer.keyring), field
    async with pg_pool.acquire() as conn:
        rows = await conn.fetch("SELECT row_to_json(audit_log)::text AS evidence FROM audit_log")
    assert "never-store-this" not in str(rows)
