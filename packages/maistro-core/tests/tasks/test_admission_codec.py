"""Contract tests for the admission row codec (#1893, B2).

These tests pin the decode/encode contract only: exact DTOs or typed
fail-closed errors, header evidence preserved across full-decode failures, no
inferred work identity, and byte-faithful snapshot round trips. Passing them
proves the codec contract, not any admission decision — the module takes no
clock, no request fingerprint, and makes no assessment or claim choice. The
database-level two-pool contrast (raw asyncpg vs ``_register_json_codecs``
pools against the real migrated schema) is B1/#1892-gated per the issue; the
pool-independence contract those tests will exercise is pinned here at the
value level.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from typing import Any

import pytest

from maistro.runs.admission_identity import (
    AdmissionBinding,
    AdmissionRecordV2,
    CanonicalJsonObject,
    LegacyAdmissionRecord,
    RootAdmissionEnvelope,
)
from maistro.tasks.admission_codec import (
    AdmissionDecodeCode,
    AdmissionRowDecodeError,
    AdmissionRowHeader,
    decode_admission_header,
    decode_admission_record,
    encode_admission_record,
)

_SCOPE = hashlib.sha256(b"scope-one").hexdigest()
_FINGERPRINT = hashlib.sha256(b"fingerprint-one").hexdigest()
_OTHER_FINGERPRINT = "ab" * 32  # valid hex64, unrelated to any snapshot bytes

_CREATED_US = 1_700_000_000_000_000
_EXPIRES_US = _CREATED_US + 86_400_000_000
_LEASE_US = _CREATED_US + 30_000_000

_GENERATION = uuid.uuid4()
_OWNER = uuid.uuid4()

#: Request snapshot carrying a permitted non-finite value inside
#: program_context, encoded with the existing evidence-json tag (#132).
_TAGGED_REQUEST: dict[str, Any] = {
    "task_id": "task-1",
    "program_context": {"readings": [1.5, {"__maistro_non_finite__": "nan"}]},
}
_REQUEST_TEXT = json.dumps(_TAGGED_REQUEST, sort_keys=True, separators=(",", ":"))
_RECEIPT_TEXT = json.dumps(
    {"receipt_id": "rcpt-1", "outcome": "created"}, sort_keys=True, separators=(",", ":")
)
_PROVENANCE_TEXT = json.dumps({"principal": "actor-1"}, sort_keys=True, separators=(",", ":"))


def _v2_record(**overrides: Any) -> AdmissionRecordV2:
    envelope = RootAdmissionEnvelope(
        scope_key=overrides.get("scope_key", _SCOPE),
        generation_id=overrides.get("generation_id", _GENERATION),
        fingerprint=overrides.get("fingerprint", _FINGERPRINT),
        workspace_id="ws-1",
        project_id="proj-1",
        origin_principal_id="origin-1",
        actor_principal_id="actor-1",
        action="create_run",
        created_at_us=overrides.get("created_at_us", _CREATED_US),
        expires_at_us=overrides.get("expires_at_us", _EXPIRES_US),
        receipt_id="rcpt-1",
        request_snapshot=CanonicalJsonObject(_REQUEST_TEXT),
        receipt_snapshot=CanonicalJsonObject(_RECEIPT_TEXT),
        provenance_snapshot=CanonicalJsonObject(_PROVENANCE_TEXT),
    )
    return AdmissionRecordV2(
        envelope=envelope,
        owner_token=overrides.get("owner_token", _OWNER),
        lease_expires_at_us=overrides.get("lease_expires_at_us", _LEASE_US),
        binding=overrides.get("binding"),
        acknowledged_at_us=overrides.get("acknowledged_at_us"),
    )


def _v2_row(**overrides: Any) -> dict[str, object]:
    row = encode_admission_record(_v2_record(**overrides))
    row.update(overrides.get("row_overrides", {}))
    return row


def _legacy_row(**overrides: Any) -> dict[str, object]:
    row: dict[str, object] = {
        "scope_key": _SCOPE,
        "format_version": 1,
        "fingerprint": overrides.pop("fingerprint", _FINGERPRINT),
        "created_at": overrides.pop("created_at", _CREATED_US),
        "expires_at": overrides.pop("expires_at", _EXPIRES_US),
        "lease_expires_at": overrides.pop("lease_expires_at", _LEASE_US),
        "request": overrides.pop("request", _REQUEST_TEXT),
        "task_id": None,
        "run_id": None,
    }
    row.update(overrides)
    return row


def _decode_full(row: dict[str, object]) -> Any:
    return decode_admission_record(row, header=decode_admission_header(row))


def _code_of(row: dict[str, object]) -> AdmissionRowDecodeError:
    with pytest.raises(AdmissionRowDecodeError) as excinfo:
        _decode_full(row)
    return excinfo.value


# --- the ten prospective contracts -----------------------------------------


def test_v2_round_trip_preserves_all_snapshot_bytes() -> None:
    row = _v2_row(binding=AdmissionBinding(run_id="run-1", receipt_id="rcpt-1"))
    record = decode_admission_record(row, header=decode_admission_header(row))
    reencoded = encode_admission_record(record)

    assert reencoded == row
    assert reencoded is not row
    assert record.envelope.request_snapshot.text == _REQUEST_TEXT
    assert record.envelope.receipt_snapshot.text == _RECEIPT_TEXT
    assert record.envelope.provenance_snapshot.text == _PROVENANCE_TEXT
    # The evidence tag survives verbatim: the codec must not decode tag
    # objects (a double decode would turn the tagged dict into a bare float).
    assert "request" in reencoded and "request_snapshot" not in reencoded
    reparsed = json.loads(reencoded["request"])
    assert reparsed["program_context"]["readings"][1] == {"__maistro_non_finite__": "nan"}
    assert record.format_version == 2 and record.admitted


def test_owner_token_is_hex_at_storage_only() -> None:
    record = _v2_record()
    row = encode_admission_record(record)

    assert row["claim_token"] == _OWNER.hex
    assert len(row["claim_token"]) == 32 and row["claim_token"] == row["claim_token"].lower()
    assert _OWNER.hex not in repr(record)
    assert _OWNER.hex not in json.dumps(list(row))

    # A non-canonical token form is rejected, never reinterpreted.
    for bad in (_OWNER.hex.upper(), str(_OWNER), f"{{{_OWNER.hex}}}"):
        broken = _v2_row(row_overrides={"claim_token": bad})
        error = _code_of(broken)
        assert error.code is AdmissionDecodeCode.INVALID_V2_RECORD
        assert bad not in str(error)


def test_legacy_binding_unbound_and_partial_are_distinct() -> None:
    unbound = _decode_full(_legacy_row())
    assert isinstance(unbound, LegacyAdmissionRecord)
    assert unbound.binding is None and unbound.admitted is False

    for partial in ({"task_id": "task-1"}, {"run_id": "run-1"}):
        error = _code_of(_legacy_row(**partial))
        assert error.code is AdmissionDecodeCode.PARTIAL_LEGACY_BINDING
        assert error.scope_key == _SCOPE

    bound = _decode_full(_legacy_row(task_id="task-1", run_id="run-1", receipt_id="rcpt-1"))
    assert bound.binding is not None
    assert (bound.binding.run_id, bound.binding.receipt_id) == ("run-1", "rcpt-1")
    assert bound.admitted is True


def test_expired_legacy_header_does_not_invent_missing_identity() -> None:
    row = _legacy_row(created_at=1000, expires_at=2000, lease_expires_at=1500)
    header = decode_admission_header(row)

    # No clock is taken: "expired" is the consumer's comparison, the codec
    # just preserves the scalars exactly.
    assert (header.created_at_us, header.expires_at_us, header.lease_expires_at_us) == (
        1000,
        2000,
        1500,
    )
    record = decode_admission_record(row, header=header)
    assert record.binding is None
    field_names = {field.name for field in type(record).__dataclass_fields__.values()}
    assert "task_id" not in field_names and "run_id" not in field_names
    assert not hasattr(record, "owner_token") and not hasattr(record, "envelope")


def test_header_preserves_expiry_even_when_legacy_snapshot_decode_fails() -> None:
    row = _legacy_row(request='{"created": 1, "created": 2}')
    header = decode_admission_header(row)
    assert header.expires_at_us == _EXPIRES_US
    assert header.created_at_us == _CREATED_US
    assert header.lease_expires_at_us == _LEASE_US

    error = _code_of(row)
    assert error.code is AdmissionDecodeCode.INVALID_SNAPSHOT
    # The header object is untouched by the record failure and still carries
    # the expiry evidence the consumer needs to order replacement first.
    assert header.expires_at_us == _EXPIRES_US
    assert decode_admission_header(row) == header


def test_header_preserves_fingerprint_even_when_legacy_binding_is_partial() -> None:
    row = _legacy_row(fingerprint=_OTHER_FINGERPRINT, task_id="task-1")
    header = decode_admission_header(row)
    assert header.fingerprint == _OTHER_FINGERPRINT

    error = _code_of(row)
    assert error.code is AdmissionDecodeCode.PARTIAL_LEGACY_BINDING
    assert header.fingerprint == _OTHER_FINGERPRINT


@pytest.mark.parametrize("bad_format", [3, 0, -1, None, "1", True, 1.0])
def test_unknown_format_cannot_be_reinterpreted_as_legacy(bad_format: object) -> None:
    row = _legacy_row()
    row["format_version"] = bad_format
    with pytest.raises(AdmissionRowDecodeError) as excinfo:
        decode_admission_header(row)
    assert excinfo.value.code is AdmissionDecodeCode.UNSUPPORTED_FORMAT

    # Even a hand-built supported header cannot launder the row: re-deriving
    # the header from the row fails closed on the unsupported format before
    # any legacy read, and two SUPPORTED but disagreeing formats are rejected
    # by structural header comparison — no legacy path is reachable either way.
    with pytest.raises(AdmissionRowDecodeError) as excinfo:
        decode_admission_record(row, header=decode_admission_header(_legacy_row()))
    assert excinfo.value.code is AdmissionDecodeCode.UNSUPPORTED_FORMAT

    v2_header = decode_admission_header(_v2_row())
    with pytest.raises(AdmissionRowDecodeError) as excinfo:
        decode_admission_record(_legacy_row(), header=v2_header)
    assert excinfo.value.code is AdmissionDecodeCode.INVALID_HEADER

    with pytest.raises(AdmissionRowDecodeError):
        AdmissionRowHeader(
            scope_key=_SCOPE,
            format_version=3,  # type: ignore[arg-type]
            fingerprint=_FINGERPRINT,
            created_at_us=_CREATED_US,
            expires_at_us=_EXPIRES_US,
            lease_expires_at_us=_LEASE_US,
        )


def test_tagged_nonfinite_snapshots_round_trip_without_fingerprint_change() -> None:
    for token in ("nan", "inf", "-inf"):
        tagged = {
            "program_context": {"v": [{"__maistro_non_finite__": token}]},
            "plain": "text",
        }
        row = _v2_row(
            fingerprint=_OTHER_FINGERPRINT,
            row_overrides={"request": json.dumps(tagged, sort_keys=True, separators=(",", ":"))},
        )
        header = decode_admission_header(row)
        assert header.fingerprint == _OTHER_FINGERPRINT
        record = decode_admission_record(row, header=header)
        assert record.envelope.fingerprint == _OTHER_FINGERPRINT
        assert encode_admission_record(record)["fingerprint"] == _OTHER_FINGERPRINT
        assert json.loads(record.envelope.request_snapshot.text)["program_context"]["v"] == [
            {"__maistro_non_finite__": token}
        ]


@pytest.mark.parametrize(
    "broken",
    [
        '{"a": 1, "a": 2}',  # duplicate keys
        "[1, 2]",  # non-object root
        '"scalar"',  # non-object root
        '{"a": NaN}',  # bare non-finite token
        '{"a": 1e999}',  # overflows to inf
        "not json at all",  # invalid JSON
        "",  # empty text
    ],
)
def test_invalid_and_duplicate_json_is_rejected(broken: str) -> None:
    row = _legacy_row(request=broken)
    header = decode_admission_header(row)  # header evidence survives
    with pytest.raises(AdmissionRowDecodeError) as excinfo:
        decode_admission_record(row, header=header)
    error = excinfo.value
    assert error.code is AdmissionDecodeCode.INVALID_SNAPSHOT
    assert error.scope_key == _SCOPE
    assert error.__suppress_context__ is True
    if broken:
        assert broken not in str(error)


def test_text_snapshots_reject_predecoded_values() -> None:
    # This is the value-level half of the real-pool contrast below: snapshots
    # are TEXT, so a value which a JSON codec had decoded must not be silently
    # accepted as though it were a storage TEXT value.
    row = _v2_row()
    assert isinstance(row["request"], str)

    as_read_by_raw_pool = row["request"]
    as_read_by_registered_pool = row["request"]
    assert as_read_by_raw_pool == as_read_by_registered_pool
    record = decode_admission_record(row, header=decode_admission_header(row))
    assert record.envelope.request_snapshot.text == as_read_by_raw_pool

    misdecoded = dict(row)
    misdecoded["request"] = json.loads(row["request"])
    with pytest.raises(AdmissionRowDecodeError) as excinfo:
        _decode_full(misdecoded)
    assert excinfo.value.code is AdmissionDecodeCode.INVALID_SNAPSHOT


@pytest.mark.asyncio
async def test_raw_and_production_pool_codecs_read_identical_text_snapshots(
    pg_pool: Any,
) -> None:
    """Read one migrated admission row through raw and production asyncpg pools.

    The production fixture registers ``_register_json_codecs``; the independent
    raw pool deliberately does not. The admission snapshots are TEXT rather
    than JSONB, so both readers must hand the codec the same strings. The two
    environment variables are separately required because they are the
    migration and asyncpg contracts for this real-database proof; comparing
    server identity makes a same-named database on another server insufficient.
    """
    dsn = os.getenv("MAISTRO_TEST_PG_DSN", "").strip()
    database_url = os.getenv("MAISTRO_TEST_DATABASE_URL", "").strip()
    if not dsn or not database_url:
        if os.getenv("MAISTRO_REQUIRE_PG_LEGS") == "1":
            pytest.fail(
                "MAISTRO_REQUIRE_PG_LEGS requires MAISTRO_TEST_PG_DSN and "
                "MAISTRO_TEST_DATABASE_URL for admission codec durability"
            )
        pytest.skip("set MAISTRO_TEST_PG_DSN and MAISTRO_TEST_DATABASE_URL")
    if pg_pool is None:
        pytest.fail("a configured admission codec durability test requires pg_pool")

    import asyncpg

    # Alembic commonly receives a SQLAlchemy driver URL, while asyncpg accepts
    # a normal PostgreSQL URL. Strip only the driver selector; credentials,
    # host, port, and database stay intact for the identity comparison below.
    raw_dsn = re.sub(r"^postgres(?:ql)?\+[a-zA-Z0-9_]+://", "postgresql://", database_url)
    raw_pool = await asyncpg.create_pool(raw_dsn, min_size=1, max_size=1)
    scope_key = hashlib.sha256(f"admission-codec-{uuid.uuid4().hex}".encode()).hexdigest()
    try:
        async with pg_pool.acquire() as production_conn, raw_pool.acquire() as raw_conn:
            production_identity = await production_conn.fetchrow(
                "SELECT current_database(), inet_server_addr()::text, inet_server_port()"
            )
            raw_identity = await raw_conn.fetchrow(
                "SELECT current_database(), inet_server_addr()::text, inet_server_port()"
            )
        assert production_identity is not None and raw_identity is not None
        assert tuple(production_identity) == tuple(raw_identity)

        encoded = encode_admission_record(_v2_record(scope_key=scope_key))
        columns = tuple(encoded)
        placeholders = ", ".join(f"${index}" for index in range(1, len(columns) + 1))
        async with pg_pool.acquire() as production_conn:
            await production_conn.execute(
                f"INSERT INTO task_idempotency ({', '.join(columns)}) VALUES ({placeholders})",
                *(encoded[column] for column in columns),
            )
            production_row = await production_conn.fetchrow(
                f"SELECT {', '.join(columns)} FROM task_idempotency WHERE scope_key = $1",
                scope_key,
            )
        async with raw_pool.acquire() as raw_conn:
            raw_row = await raw_conn.fetchrow(
                f"SELECT {', '.join(columns)} FROM task_idempotency WHERE scope_key = $1",
                scope_key,
            )

        assert production_row is not None and raw_row is not None
        production_mapping = dict(production_row)
        raw_mapping = dict(raw_row)
        assert production_mapping == raw_mapping == encoded
        for row in (production_mapping, raw_mapping):
            decoded = decode_admission_record(row, header=decode_admission_header(row))
            assert isinstance(decoded, AdmissionRecordV2)
            assert decoded.envelope.request_snapshot.text == _REQUEST_TEXT
            assert encode_admission_record(decoded) == encoded
    finally:
        async with pg_pool.acquire() as production_conn:
            await production_conn.execute(
                "DELETE FROM task_idempotency WHERE scope_key = $1", scope_key
            )
        await raw_pool.close()


# --- header / schema fail-closed contracts ---------------------------------


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("scope_key", _OTHER_FINGERPRINT),  # valid hex64, but a different value
        ("fingerprint", _SCOPE),
        ("created_at", _CREATED_US + 1),
        ("expires_at", _EXPIRES_US + 1),
        ("lease_expires_at", _LEASE_US + 1),
    ],
)
def test_header_scalar_mismatch_is_invalid_header(column: str, value: object) -> None:
    row = _v2_row()
    header = decode_admission_header(row)
    row[column] = value
    with pytest.raises(AdmissionRowDecodeError) as excinfo:
        decode_admission_record(row, header=header)
    assert excinfo.value.code is AdmissionDecodeCode.INVALID_HEADER
    assert excinfo.value.scope_key == _SCOPE


def test_missing_header_columns_is_unsupported_schema() -> None:
    row = _legacy_row()
    del row["format_version"]
    with pytest.raises(AdmissionRowDecodeError) as excinfo:
        decode_admission_header(row)
    assert excinfo.value.code is AdmissionDecodeCode.UNSUPPORTED_SCHEMA
    assert excinfo.value.scope_key is None  # scope not yet validated


@pytest.mark.parametrize(
    "column", ["generation_id", "claim_token", "request", "receipt_snapshot", "acknowledged_at"]
)
def test_missing_v2_columns_is_unsupported_schema(column: str) -> None:
    row = _v2_row()
    header = decode_admission_header(row)
    del row[column]
    with pytest.raises(AdmissionRowDecodeError) as excinfo:
        decode_admission_record(row, header=header)
    assert excinfo.value.code is AdmissionDecodeCode.UNSUPPORTED_SCHEMA


def test_missing_legacy_request_is_unsupported_schema() -> None:
    row = _legacy_row()
    header = decode_admission_header(row)
    del row["request"]

    with pytest.raises(AdmissionRowDecodeError) as excinfo:
        decode_admission_record(row, header=header)

    assert excinfo.value.code is AdmissionDecodeCode.UNSUPPORTED_SCHEMA
    assert excinfo.value.scope_key == _SCOPE


@pytest.mark.parametrize(
    ("column", "bad"),
    [
        ("scope_key", "AA" * 32),  # uppercase
        ("scope_key", "zz" * 32),  # not hex
        ("scope_key", _SCOPE[:-1]),  # 63 chars
        ("fingerprint", "short"),
        ("created_at", "not-an-int"),
        ("created_at", True),  # bool is an int subclass and loses
        ("expires_at", 2**63),  # outside signed 64-bit
        ("lease_expires_at", -(2**63) - 1),
    ],
)
def test_invalid_scalar_headers_fail_closed(column: str, bad: object) -> None:
    row = _legacy_row()
    row[column] = bad
    with pytest.raises(AdmissionRowDecodeError) as excinfo:
        decode_admission_header(row)
    assert excinfo.value.code is AdmissionDecodeCode.INVALID_HEADER


def test_decode_error_scope_key_is_only_a_validated_hash() -> None:
    row = _legacy_row()
    row["scope_key"] = "not-a-hash"
    error = _code_of(row)
    assert error.code is AdmissionDecodeCode.INVALID_HEADER
    assert error.scope_key is None

    ok = _legacy_row(request="broken")
    assert _code_of(ok).scope_key == _SCOPE


# --- v2 record fail-closed contracts ---------------------------------------


@pytest.mark.parametrize(
    "generation",
    [str(_GENERATION), _GENERATION.hex.upper(), _GENERATION.hex[:-1], uuid.UUID(int=0).hex],
)
def test_v2_generation_ids_are_strict_storage_hex(generation: str) -> None:
    error = _code_of(_v2_row(row_overrides={"generation_id": generation}))
    assert error.code is AdmissionDecodeCode.INVALID_V2_RECORD
    assert generation not in str(error)


@pytest.mark.parametrize(
    "column", ["workspace_id", "project_id", "actor_principal_id", "action", "receipt_id"]
)
def test_v2_identity_columns_must_be_strings(column: str) -> None:
    error = _code_of(_v2_row(row_overrides={column: None}))
    assert error.code is AdmissionDecodeCode.INVALID_V2_RECORD


def test_v2_task_without_run_is_corruption_not_unbound() -> None:
    error = _code_of(_v2_row(row_overrides={"task_id": "task-1"}))
    assert error.code is AdmissionDecodeCode.INVALID_V2_RECORD


def test_v2_bound_task_must_match_its_immutable_receipt_identity() -> None:
    row = _v2_row(
        binding=AdmissionBinding(run_id="run-1", receipt_id="rcpt-1"),
        row_overrides={"task_id": "another-receipt"},
    )
    error = _code_of(row)
    assert error.code is AdmissionDecodeCode.INVALID_V2_RECORD
    assert "another-receipt" not in str(error)


def test_v2_acknowledged_requires_bound_record() -> None:
    # The row is built from a valid unbound record, then the acknowledged_at
    # column is stamped on — the v2 constructor rejects the combination.
    row = _v2_row(binding=None, row_overrides={"acknowledged_at": _CREATED_US + 5})
    error = _code_of(row)
    assert error.code is AdmissionDecodeCode.INVALID_V2_RECORD


def test_v2_lease_must_sit_inside_the_window() -> None:
    row = _v2_row(row_overrides={"lease_expires_at": _EXPIRES_US + 1})
    error = _code_of(row)
    assert error.code is AdmissionDecodeCode.INVALID_V2_RECORD
    assert str(_OWNER) not in str(error) and _OWNER.hex not in str(error)


def test_v2_expiry_must_exceed_creation() -> None:
    row = _v2_row(row_overrides={"created_at": _EXPIRES_US})
    header = decode_admission_header(row)  # scalars are individually valid
    with pytest.raises(AdmissionRowDecodeError) as excinfo:
        decode_admission_record(row, header=header)
    assert excinfo.value.code is AdmissionDecodeCode.INVALID_V2_RECORD


def test_v2_acknowledged_before_creation_is_rejected() -> None:
    row = _v2_row(
        binding=AdmissionBinding(run_id="run-1", receipt_id="rcpt-1"),
        row_overrides={"acknowledged_at": _CREATED_US - 1},
    )
    assert _code_of(row).code is AdmissionDecodeCode.INVALID_V2_RECORD


def test_unacknowledged_unbound_v2_record_round_trips() -> None:
    row = _v2_row(binding=None)
    record = decode_admission_record(row, header=decode_admission_header(row))
    assert isinstance(record, AdmissionRecordV2)
    assert record.binding is None and record.acknowledged_at_us is None
    assert record.admitted is False
    assert encode_admission_record(record) == row


# --- legacy evidence contracts ---------------------------------------------


def test_legacy_receipt_only_row_is_partial_not_unbound() -> None:
    error = _code_of(_legacy_row(receipt_id="rcpt-1"))
    assert error.code is AdmissionDecodeCode.PARTIAL_LEGACY_BINDING


def test_legacy_bound_pair_without_receipt_is_partial_never_fabricated() -> None:
    error = _code_of(_legacy_row(task_id="task-1", run_id="run-1"))
    assert error.code is AdmissionDecodeCode.PARTIAL_LEGACY_BINDING


@pytest.mark.parametrize(
    "evidence", [{"task_id": 7}, {"run_id": 7}, {"receipt_id": 7}, {"task_id": ""}]
)
def test_legacy_unreadable_evidence_is_partial(evidence: dict[str, object]) -> None:
    error = _code_of(_legacy_row(**evidence))
    assert error.code is AdmissionDecodeCode.PARTIAL_LEGACY_BINDING


def test_legacy_scalar_inversion_is_invalid_header_not_a_record() -> None:
    row = _legacy_row(created_at=2000, expires_at=2000)
    header = decode_admission_header(row)  # header stays scalar-only
    assert (header.created_at_us, header.expires_at_us) == (2000, 2000)
    with pytest.raises(AdmissionRowDecodeError) as excinfo:
        decode_admission_record(row, header=header)
    assert excinfo.value.code is AdmissionDecodeCode.INVALID_HEADER


def test_legacy_completed_at_is_never_read() -> None:
    row = _legacy_row(completed_at=_EXPIRES_US + 5)
    record = _decode_full(row)
    assert record.binding is None  # completed_at granted no authority


# --- encode contracts -------------------------------------------------------


def test_encode_returns_a_fresh_flat_mapping() -> None:
    record = _v2_record(binding=AdmissionBinding(run_id="run-1", receipt_id="rcpt-1"))
    first = encode_admission_record(record)
    second = encode_admission_record(record)
    assert first is not second
    assert all(isinstance(key, str) for key in first)
    assert all(value is None or isinstance(value, (str, int)) for value in first.values())
    first["scope_key"] = "mutated"
    assert encode_admission_record(record)["scope_key"] == _SCOPE


def test_encode_rejects_non_v2_records() -> None:
    legacy = _decode_full(_legacy_row())
    with pytest.raises(TypeError):
        encode_admission_record(legacy)  # type: ignore[arg-type]
