"""Decode immutable admission rows into exact typed records (#1893, B2).

One outcome, no guessing: a row of the forward admission table becomes either
an exact immutable DTO from :mod:`maistro.runs.admission_identity` (#1851) or
a typed :class:`AdmissionRowDecodeError` carrying *why* the row cannot be
canonicalized. The codec never infers work identity: an unbound legacy row
stays unbound, incomplete binding evidence stays a typed
``partial_legacy_binding`` disposition, and no task id, run id or receipt is
ever fabricated to make a row fit a DTO.

Layering (parent #1845): the header decoder is the minimal supported-row
evidence — format/version, scope, scalar timestamps, fingerprint — and the
record decoder builds the full DTO. The prospective C consumer orders *valid
header* → *inclusive expiry* → *unexpired fingerprint mismatch* → *full
snapshot/binding decoding*; that is why header decoding deliberately does not
enforce cross-field timestamp ordering and why header evidence survives even
when full decoding fails. This module implements no assessment, no expiry
decision and no claim mutation: it takes no clock, no incoming request
fingerprint, and recalculates no fingerprint — the stored ``fingerprint``
column is passed through exactly as stored.

Corruption is fail-closed. Unknown ``format_version`` values can never be
reinterpreted as legacy (``unsupported_format`` precedes every format-specific
read), rows missing the columns a format requires are ``unsupported_schema``,
snapshot TEXT that is not exactly one canonical JSON object (duplicate keys,
non-object roots, bare non-finite tokens, overflowing numbers) is
``invalid_snapshot``, and a header that disagrees with its row's scalars is
``invalid_header``.

Error hygiene: :class:`AdmissionRowDecodeError` messages name the failing
column and failure class but never quote raw snapshot bytes or owner tokens,
and parsing exceptions are suppressed (``raise … from None``) so an unsafe
chain is not exposed to callers or logs. The ``scope_key`` attribute carries
only a validated lowercase hex digest, or ``None`` before the scope has
validated.

Binding shapes (#1851 vocabulary, no task models): a legacy row with both
``task_id`` and ``run_id`` is bound — and only then — because the canonical
:class:`AdmissionBinding` also requires the row's receipt identity; a bound
pair without receipt evidence cannot be canonicalized without fabricating a
receipt, so it is ``partial_legacy_binding``, like a one-sided pair and a
receipt-only compatibility row. Neither-set with no receipt evidence is
plainly unbound. The optional legacy ``completed_at`` column is read by
nothing here: it is legacy evidence, never admission authority. For v2 rows
both binding columns must be absent or present together, and a bound
``task_id`` must equal the immutable ``receipt_id`` (migration 055).
The task-agnostic DTO needs no separate bookkeeping identity: encoding uses
the existing binding's receipt identity, never a newly inferred identifier.

No SQL mutation, no HTTP mapping, no queue change: this module reads
``Mapping`` rows and returns mappings. Nothing in production consumes it yet —
the C consumer leaf wires it — so its public surface is contract, not
behavior.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, TypeGuard
from uuid import UUID

from maistro.runs.admission_identity import (
    AdmissionBinding,
    AdmissionRecordV2,
    CanonicalJsonObject,
    LegacyAdmissionRecord,
    RootAdmissionEnvelope,
)

__all__ = [
    "AdmissionDecodeCode",
    "AdmissionRecordV2",
    "AdmissionRowDecodeError",
    "AdmissionRowHeader",
    "LegacyAdmissionRecord",
    "RootAdmissionEnvelope",
    "decode_admission_header",
    "decode_admission_record",
    "encode_admission_record",
]

#: Scope keys and fingerprints are lowercase ASCII SHA-256 hex digests. Same
#: shape rule #1851 validates; the codec never recomputes either value.
_HEX64_RE = re.compile(r"[0-9a-f]{64}")

_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1

#: The validated header columns, by storage name. The forward representation
#: keeps the legacy timestamp column names and the physical ``request`` TEXT
#: column. ``request_snapshot`` is the DTO field it maps to (#1845 mapping).
_HEADER_COLUMNS = (
    "scope_key",
    "format_version",
    "fingerprint",
    "created_at",
    "expires_at",
    "lease_expires_at",
)

#: Columns only a v2 row carries, by storage name. ``generation_id`` and
#: ``claim_token`` are UUID ``.hex`` at storage; the three snapshots and the
#: envelope identities complete the immutable envelope.
_V2_COLUMNS = (
    "generation_id",
    "claim_token",
    "workspace_id",
    "project_id",
    "origin_principal_id",
    "actor_principal_id",
    "action",
    "receipt_id",
    "request",
    "receipt_snapshot",
    "provenance_snapshot",
    "task_id",
    "run_id",
    "acknowledged_at",
)


class AdmissionDecodeCode(StrEnum):
    """Why a row could not become an exact DTO. Every value is fail-closed."""

    UNSUPPORTED_SCHEMA = "unsupported_schema"
    UNSUPPORTED_FORMAT = "unsupported_format"
    INVALID_HEADER = "invalid_header"
    INVALID_SNAPSHOT = "invalid_snapshot"
    INVALID_V2_RECORD = "invalid_v2_record"
    PARTIAL_LEGACY_BINDING = "partial_legacy_binding"


class AdmissionRowDecodeError(ValueError):
    """A row could not be decoded; ``code`` says why, never the raw bytes.

    ``scope_key`` carries the row's scope only once it has validated as a
    lowercase hex digest — before that it is ``None``, because an unvalidated
    scope must not travel as if it were identity. Messages name the failing
    column and failure class only; parsing-exception chains are suppressed by
    every raiser.
    """

    def __init__(self, message: str, *, code: AdmissionDecodeCode, scope_key: str | None) -> None:
        super().__init__(message)
        self.code = code
        if scope_key is not None and _HEX64_RE.fullmatch(scope_key) is None:
            scope_key = None
        self.scope_key = scope_key


@dataclass(frozen=True, slots=True)
class AdmissionRowHeader:
    """The minimal supported-row evidence: format, scope, scalars, fingerprint.

    Validated scalar-by-scalar only. Cross-field timestamp ordering is
    deliberately *not* enforced here — the C consumer decides expiry from
    these scalars before any full decode, so a row with odd scalars must
    still expose them exactly as stored. ``format_version`` is guarded to
    ``1``/``2`` so an unknown format can never be smuggled into a header.
    """

    scope_key: str
    format_version: Literal[1, 2]
    fingerprint: str
    created_at_us: int
    expires_at_us: int
    lease_expires_at_us: int

    def __post_init__(self) -> None:
        scope_key = self.scope_key if _hex64(self.scope_key) else None
        if scope_key is None:
            raise AdmissionRowDecodeError(
                "scope_key must match lowercase [0-9a-f]{64} exactly",
                code=AdmissionDecodeCode.INVALID_HEADER,
                scope_key=None,
            )
        if (
            not isinstance(self.format_version, int)
            or isinstance(self.format_version, bool)
            or self.format_version not in (1, 2)
        ):
            raise AdmissionRowDecodeError(
                "format_version must be exactly 1 or 2",
                code=AdmissionDecodeCode.INVALID_HEADER,
                scope_key=scope_key,
            )
        if not _hex64(self.fingerprint):
            raise AdmissionRowDecodeError(
                "fingerprint must match lowercase [0-9a-f]{64} exactly",
                code=AdmissionDecodeCode.INVALID_HEADER,
                scope_key=scope_key,
            )
        for name in ("created_at_us", "expires_at_us", "lease_expires_at_us"):
            if not _int64(getattr(self, name)):
                raise AdmissionRowDecodeError(
                    f"{name} must be a signed 64-bit int",
                    code=AdmissionDecodeCode.INVALID_HEADER,
                    scope_key=scope_key,
                )


def decode_admission_header(row: Mapping[str, object]) -> AdmissionRowHeader:
    """Decode the minimal supported row header, or fail closed and typed.

    Missing header columns mean the row does not even carry the forward
    representation (``unsupported_schema``); an unknown or NULL
    ``format_version`` is ``unsupported_format`` and can never fall through to
    a legacy interpretation; scalar shape failures are ``invalid_header``.
    """
    _require_columns(row, _HEADER_COLUMNS, scope_key=None)

    format_version = _coerce_format_version(row["format_version"])
    scope_key = _require_hex(row, "scope_key", scope_key=None)
    fingerprint = _require_hex(row, "fingerprint", scope_key=scope_key)

    return AdmissionRowHeader(
        scope_key=scope_key,
        format_version=format_version,
        fingerprint=fingerprint,
        created_at_us=_scalar_timestamp(row["created_at"], "created_at", scope_key),
        expires_at_us=_scalar_timestamp(row["expires_at"], "expires_at", scope_key),
        lease_expires_at_us=_scalar_timestamp(
            row["lease_expires_at"], "lease_expires_at", scope_key
        ),
    )


def decode_admission_record(
    row: Mapping[str, object], *, header: AdmissionRowHeader
) -> AdmissionRecordV2 | LegacyAdmissionRecord:
    """Decode the full immutable record under an already-validated header.

    The header is checked against the row's scalar fields first: the header is
    re-derived from the row under the same strict validation as
    :func:`decode_admission_header` — so unsupported schemas and formats fail
    closed before any format-specific read — and any disagreement with the
    given header is ``invalid_header``. Structural comparison, not ``==`` on
    raw values: Python's ``True == 1`` and ``1.0 == 1`` must never launder a
    non-scalar column into a supported format. Only then does the format
    branch run, so an unknown format can never be reinterpreted as legacy.
    """
    derived = decode_admission_header(row)
    if derived != header:
        raise AdmissionRowDecodeError(
            "header does not match the row's scalar fields",
            code=AdmissionDecodeCode.INVALID_HEADER,
            scope_key=header.scope_key,
        ) from None

    if header.format_version == 2:
        return _decode_v2_record(row, header)
    return _decode_legacy_record(row, header)


def encode_admission_record(record: AdmissionRecordV2) -> dict[str, object]:
    """A fresh flat SQL-parameter mapping for one v2 record.

    Every value is a bound scalar: snapshots go out as their canonical TEXT,
    UUIDs as lowercase ``.hex`` (the owner token becomes ``claim_token`` — hex
    at storage only, nowhere else), timestamps as the legacy-named columns.
    The forward schema represents a binding as ``task_id = receipt_id`` plus
    ``run_id``; both columns are NULL for an unbound record.
    """
    if not isinstance(record, AdmissionRecordV2):
        raise TypeError(f"expected AdmissionRecordV2, not {type(record).__name__}")
    envelope = record.envelope
    binding = record.binding
    return {
        "scope_key": envelope.scope_key,
        "format_version": 2,
        "fingerprint": envelope.fingerprint,
        "created_at": envelope.created_at_us,
        "expires_at": envelope.expires_at_us,
        "lease_expires_at": record.lease_expires_at_us,
        "generation_id": envelope.generation_id.hex,
        "claim_token": record.owner_token.hex,
        "workspace_id": envelope.workspace_id,
        "project_id": envelope.project_id,
        "origin_principal_id": envelope.origin_principal_id,
        "actor_principal_id": envelope.actor_principal_id,
        "action": envelope.action,
        "receipt_id": envelope.receipt_id,
        "request": envelope.request_snapshot.text,
        "receipt_snapshot": envelope.receipt_snapshot.text,
        "provenance_snapshot": envelope.provenance_snapshot.text,
        "task_id": binding.receipt_id if binding is not None else None,
        "run_id": binding.run_id if binding is not None else None,
        "acknowledged_at": record.acknowledged_at_us,
    }


def _hex64(value: object) -> TypeGuard[str]:
    """Exactly a lowercase ``[0-9a-f]{64}`` string."""
    return isinstance(value, str) and _HEX64_RE.fullmatch(value) is not None


def _coerce_format_version(value: object) -> Literal[1, 2]:
    """Exactly the ``int`` 1 or 2; ``bool`` is an ``int`` subclass and loses.

    Any other value — including NULL — is ``unsupported_format`` and can
    never fall through to a legacy interpretation.
    """
    if isinstance(value, int) and not isinstance(value, bool):
        if value == 1:
            return 1
        if value == 2:
            return 2
    raise AdmissionRowDecodeError(
        "format_version must be exactly 1 or 2",
        code=AdmissionDecodeCode.UNSUPPORTED_FORMAT,
        scope_key=None,
    ) from None


def _require_hex(row: Mapping[str, object], column: str, *, scope_key: str | None) -> str:
    """One header digest column: exactly lowercase ``[0-9a-f]{64}``, or fail."""
    value = row[column]
    if _hex64(value):
        return value
    raise AdmissionRowDecodeError(
        f"{column} must match lowercase [0-9a-f]{64} exactly",
        code=AdmissionDecodeCode.INVALID_HEADER,
        scope_key=scope_key,
    ) from None


def _int64(value: object) -> bool:
    """Exactly a signed 64-bit int; ``bool`` is an ``int`` subclass and loses."""
    return (
        isinstance(value, int) and not isinstance(value, bool) and _INT64_MIN <= value <= _INT64_MAX
    )


def _require_columns(
    row: Mapping[str, object], columns: tuple[str, ...], *, scope_key: str | None
) -> None:
    missing = [name for name in columns if name not in row]
    if missing:
        raise AdmissionRowDecodeError(
            f"row is missing required admission columns: {', '.join(missing)}",
            code=AdmissionDecodeCode.UNSUPPORTED_SCHEMA,
            scope_key=scope_key,
        ) from None


def _scalar_timestamp(value: object, column: str, scope_key: str) -> int:
    """A signed 64-bit int exactly; ``bool`` is an ``int`` subclass and loses."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise AdmissionRowDecodeError(
            f"{column} must be a signed 64-bit int",
            code=AdmissionDecodeCode.INVALID_HEADER,
            scope_key=scope_key,
        ) from None
    if not _INT64_MIN <= value <= _INT64_MAX:
        raise AdmissionRowDecodeError(
            f"{column} must fit in signed 64-bit range",
            code=AdmissionDecodeCode.INVALID_HEADER,
            scope_key=scope_key,
        ) from None
    return value


def _parse_snapshot(row: Mapping[str, object], column: str, scope_key: str) -> CanonicalJsonObject:
    """Snapshots are TEXT columns: exactly one canonical JSON object, or fail.

    Rejects non-text values too — a pool that registered JSON codecs over
    these columns would hand back a decoded object, and silently accepting it
    would make decoding depend on how somebody else built the pool.
    Duplicate keys, non-object roots, bare non-finite tokens and overflowing
    numbers are all rejected by the :class:`CanonicalJsonObject` constructor;
    the underlying parse exception is suppressed, never exposed.
    """
    value = row[column]
    if not isinstance(value, str):
        raise AdmissionRowDecodeError(
            f"{column} must be TEXT, not {type(value).__name__}",
            code=AdmissionDecodeCode.INVALID_SNAPSHOT,
            scope_key=scope_key,
        ) from None
    try:
        return CanonicalJsonObject(value)
    except ValueError:
        raise AdmissionRowDecodeError(
            f"{column} is not exactly one canonical JSON object",
            code=AdmissionDecodeCode.INVALID_SNAPSHOT,
            scope_key=scope_key,
        ) from None


def _storage_uuid(value: object, column: str, scope_key: str) -> UUID:
    """Strict storage decoding: exactly 32 lowercase hex digits, round-tripped.

    ``uuid.UUID`` leniently accepts hyphenated, braced and URN forms and
    uppercase digits; requiring ``parsed.hex == value`` admits exactly the
    canonical storage encoding and nothing else.
    """
    if isinstance(value, str) and len(value) == 32:
        try:
            parsed = UUID(value)
        except ValueError:
            parsed = None
        if parsed is not None and parsed.hex == value:
            return parsed
    raise AdmissionRowDecodeError(
        f"{column} must be stored as lowercase UUID .hex",
        code=AdmissionDecodeCode.INVALID_V2_RECORD,
        scope_key=scope_key,
    ) from None


def _v2_identities(row: Mapping[str, object], scope_key: str) -> dict[str, str]:
    """The envelope's identity strings, exactly as stored or fail-closed."""
    identities: dict[str, str] = {}
    for name in (
        "workspace_id",
        "project_id",
        "origin_principal_id",
        "actor_principal_id",
        "action",
        "receipt_id",
    ):
        value = row[name]
        if not isinstance(value, str):
            raise AdmissionRowDecodeError(
                f"{name} must be a nonempty identity string",
                code=AdmissionDecodeCode.INVALID_V2_RECORD,
                scope_key=scope_key,
            ) from None
        identities[name] = value
    return identities


def _v2_binding(
    row: Mapping[str, object], *, receipt_id: str, scope_key: str
) -> AdmissionBinding | None:
    """The optional v2 binding, present exactly when ``run_id`` is stored.

    The v2 binding write is one statement setting both columns, so either
    one-sided pair is corruption (``invalid_v2_record``), never a binding or
    an unbound row. The forward-table constraint also binds ``task_id`` to this
    row's immutable receipt identity. The DTO deliberately does not carry the
    queue bookkeeping identifier, but decoding must validate it before
    dropping it so corrupt storage cannot be silently re-described as a valid
    canonical binding.
    """
    raw_task_id = row["task_id"]
    raw_run_id = row["run_id"]
    if (raw_task_id is None) != (raw_run_id is None):
        raise AdmissionRowDecodeError(
            "task_id and run_id must both be present or both NULL for v2",
            code=AdmissionDecodeCode.INVALID_V2_RECORD,
            scope_key=scope_key,
        ) from None
    if raw_task_id is not None:
        if not isinstance(raw_task_id, str):
            raise AdmissionRowDecodeError(
                "task_id must be TEXT or NULL",
                code=AdmissionDecodeCode.INVALID_V2_RECORD,
                scope_key=scope_key,
            ) from None
        if raw_task_id != receipt_id:
            raise AdmissionRowDecodeError(
                "task_id must equal the v2 receipt identity when bound",
                code=AdmissionDecodeCode.INVALID_V2_RECORD,
                scope_key=scope_key,
            ) from None
    if raw_run_id is None:
        return None
    if not isinstance(raw_run_id, str):
        raise AdmissionRowDecodeError(
            "run_id must be TEXT or NULL",
            code=AdmissionDecodeCode.INVALID_V2_RECORD,
            scope_key=scope_key,
        ) from None
    try:
        return AdmissionBinding(run_id=raw_run_id, receipt_id=receipt_id)
    except ValueError:
        raise AdmissionRowDecodeError(
            "row's binding does not satisfy the canonical binding contract",
            code=AdmissionDecodeCode.INVALID_V2_RECORD,
            scope_key=scope_key,
        ) from None


def _v2_acknowledged_at(row: Mapping[str, object], scope_key: str) -> int | None:
    raw = row["acknowledged_at"]
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int) or not _INT64_MIN <= raw <= _INT64_MAX:
        raise AdmissionRowDecodeError(
            "acknowledged_at must be a signed 64-bit int or NULL",
            code=AdmissionDecodeCode.INVALID_V2_RECORD,
            scope_key=scope_key,
        ) from None
    return raw


def _decode_v2_record(row: Mapping[str, object], header: AdmissionRowHeader) -> AdmissionRecordV2:
    scope_key = header.scope_key
    _require_columns(row, _V2_COLUMNS, scope_key=scope_key)

    generation_id = _storage_uuid(row["generation_id"], "generation_id", scope_key)
    owner_token = _storage_uuid(row["claim_token"], "claim_token", scope_key)

    identities = _v2_identities(row, scope_key)
    request_snapshot = _parse_snapshot(row, "request", scope_key)
    receipt_snapshot = _parse_snapshot(row, "receipt_snapshot", scope_key)
    provenance_snapshot = _parse_snapshot(row, "provenance_snapshot", scope_key)

    try:
        envelope = RootAdmissionEnvelope(
            scope_key=scope_key,
            generation_id=generation_id,
            fingerprint=header.fingerprint,
            workspace_id=identities["workspace_id"],
            project_id=identities["project_id"],
            origin_principal_id=identities["origin_principal_id"],
            actor_principal_id=identities["actor_principal_id"],
            action=identities["action"],
            created_at_us=header.created_at_us,
            expires_at_us=header.expires_at_us,
            receipt_id=identities["receipt_id"],
            request_snapshot=request_snapshot,
            receipt_snapshot=receipt_snapshot,
            provenance_snapshot=provenance_snapshot,
        )
    except ValueError:
        raise AdmissionRowDecodeError(
            "row does not satisfy the v2 admission envelope contract",
            code=AdmissionDecodeCode.INVALID_V2_RECORD,
            scope_key=scope_key,
        ) from None

    binding = _v2_binding(row, receipt_id=identities["receipt_id"], scope_key=scope_key)
    acknowledged_at_us = _v2_acknowledged_at(row, scope_key)

    try:
        return AdmissionRecordV2(
            envelope=envelope,
            owner_token=owner_token,
            lease_expires_at_us=header.lease_expires_at_us,
            binding=binding,
            acknowledged_at_us=acknowledged_at_us,
        )
    except ValueError:
        raise AdmissionRowDecodeError(
            "row does not satisfy the v2 admission record contract",
            code=AdmissionDecodeCode.INVALID_V2_RECORD,
            scope_key=scope_key,
        ) from None


def _decode_legacy_record(
    row: Mapping[str, object], header: AdmissionRowHeader
) -> LegacyAdmissionRecord:
    """A pre-generation row: fingerprint + request scalars, binding evidence.

    Legacy evidence columns are optional and read leniently by name — the old
    table carried none of ``receipt_id``/``completed_at``. Binding
    classification never guesses: both ids with receipt identity is bound,
    neither id without receipt evidence is unbound, and everything else —
    one-sided pairs, receipt-only compatibility rows, unreadable evidence —
    is ``partial_legacy_binding`` rather than an invented disposition. The
    optional legacy ``completed_at`` column is deliberately not read.
    """
    scope_key = header.scope_key
    # ``request`` is the legacy row's only mandatory full-record column.
    # Reading it by subscription below must not leak a raw ``KeyError`` when a
    # malformed pre-forward schema row omits it.
    _require_columns(row, ("request",), scope_key=scope_key)

    task_id = _legacy_evidence(row.get("task_id"), "task_id", scope_key)
    run_id = _legacy_evidence(row.get("run_id"), "run_id", scope_key)
    receipt_id = _legacy_evidence(row.get("receipt_id"), "receipt_id", scope_key)

    binding: AdmissionBinding | None = None
    if (task_id is None) != (run_id is None):
        raise AdmissionRowDecodeError(
            "legacy binding evidence is partial: exactly one of task_id/run_id is present",
            code=AdmissionDecodeCode.PARTIAL_LEGACY_BINDING,
            scope_key=scope_key,
        ) from None
    if run_id is not None:
        if receipt_id is None:
            # A canonical binding needs the row's receipt identity; none is
            # stored, and fabricating one is exactly what this codec forbids.
            raise AdmissionRowDecodeError(
                "legacy binding evidence is partial: bound pair without receipt identity",
                code=AdmissionDecodeCode.PARTIAL_LEGACY_BINDING,
                scope_key=scope_key,
            ) from None
        try:
            binding = AdmissionBinding(run_id=run_id, receipt_id=receipt_id)
        except ValueError:
            raise AdmissionRowDecodeError(
                "legacy binding evidence is not a canonical binding",
                code=AdmissionDecodeCode.PARTIAL_LEGACY_BINDING,
                scope_key=scope_key,
            ) from None
    elif receipt_id is not None:
        # Receipt-only compatibility row: a receipt exists but no binding
        # landed. The codec reports the disposition; the cause stays unknown.
        raise AdmissionRowDecodeError(
            "legacy binding evidence is partial: receipt without bound pair",
            code=AdmissionDecodeCode.PARTIAL_LEGACY_BINDING,
            scope_key=scope_key,
        ) from None

    request_snapshot = _parse_snapshot(row, "request", scope_key)

    try:
        return LegacyAdmissionRecord(
            fingerprint=header.fingerprint,
            request_snapshot=request_snapshot,
            created_at_us=header.created_at_us,
            expires_at_us=header.expires_at_us,
            lease_expires_at_us=header.lease_expires_at_us,
            binding=binding,
        )
    except ValueError:
        # Every scalar already passed header validation and the snapshot is a
        # parsed CanonicalJsonObject, so the only reachable failure is the
        # record-level scalar contract (expiry must exceed creation): the
        # row's header facts are mutually inconsistent.
        raise AdmissionRowDecodeError(
            "legacy row scalars violate the record contract",
            code=AdmissionDecodeCode.INVALID_HEADER,
            scope_key=scope_key,
        ) from None


def _legacy_evidence(value: object, column: str, scope_key: str) -> str | None:
    """Read one optional legacy evidence column, or fail partial — never guess.

    ``None`` means absent. Anything present that is not a nonempty string is
    unreadable evidence: the row can be neither trusted as unbound nor
    canonicalized as bound, which is exactly a ``partial_legacy_binding``
    disposition and nothing more.
    """
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise AdmissionRowDecodeError(
            f"legacy {column} evidence is unreadable",
            code=AdmissionDecodeCode.PARTIAL_LEGACY_BINDING,
            scope_key=scope_key,
        ) from None
    return value
