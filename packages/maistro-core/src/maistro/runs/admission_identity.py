"""Immutable root-admission identity types (#1851, parent #1845).

This module is an **inactive contract leaf**. Nothing in production imports it
yet; a later, separately reviewed integration lands the runtime consumer
(prospective C2 classifier and backend wiring) before these types become
reachable. It defines, and only defines, the typed vocabulary a future
admission backend needs so it never has to import task models into RunStore or
guess field semantics:

- an admission *generation* (``AdmissionTicket.generation_id``) fenced from its
  *lease owner* (``owner_token``) — two independently generated UUIDs with two
  independent identity roles;
- immutable canonical JSON snapshots of the original request, receipt, and
  provenance (``CanonicalJsonObject``), so no mutable dict or mutable ``Run``
  model crosses a trust boundary;
- explicit claim/mutation results, so a stale lease can never be encoded as a
  truthy boolean — callers discriminate by variant type.

The canonical execution model (``Goal -> Graph -> Run -> NodeRun -> Attempt``)
and the accepted security signature of #1841 (``require_admitted_actor``,
``RunStore.get_run(..., principal_id=...)``, the admitted-actor guard on
``create_run``/``claim_run_by_effect``) are untouched here. This module
authorizes nothing: constructing a DTO is not admission, and ``owns`` is a pure
fencing comparison, not permission.

Fencing is exactly the conjunction::

    record.envelope.scope_key == ticket.scope_key
    AND record.envelope.generation_id == ticket.generation_id
    AND record.owner_token == ticket.owner_token

Both persisted identity roles are compared against their ticket fields; the
generation and owner values are never compared to each other, and scope
equality alone authorizes nothing. Future backends must repeat these
predicates against the locked persisted row inside their own transaction.

Owner tokens are omitted from generated ``repr`` output and must stay out of
Run provenance, HTTP payloads, and diagnostics. UUIDs serialize to lowercase
32-character ``.hex`` only at future storage boundaries, outside this leaf.
"""

from __future__ import annotations

import json
import math
import re
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

__all__ = [
    "Acknowledged",
    "AdmissionAssessment",
    "AdmissionBinding",
    "AdmissionRecordV2",
    "AdmissionTicket",
    "AlreadyAcknowledged",
    "AlreadyBound",
    "BindingMismatch",
    "CanonicalJsonObject",
    "ClaimResult",
    "Claimed",
    "CompletionResult",
    "LegacyAdmissionRecord",
    "LegacyUnresolved",
    "Pending",
    "ReleaseResult",
    "Released",
    "Replayed",
    "RootAdmissionEnvelope",
    "RootAdmissionResult",
    "StaleOwner",
]

#: Scope keys and fingerprints are lowercase ASCII SHA-256 hex digests. This
#: module validates their shape only; it neither recomputes nor redefines the
#: live scope/fingerprint algorithms.
_HEX64_RE = re.compile(r"[0-9a-f]{64}")

_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1


def _require_hex64(value: object, name: str) -> None:
    """Require a lowercase ``[0-9a-f]{64}`` string."""
    if not isinstance(value, str) or _HEX64_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must match lowercase [0-9a-f]{{64}} exactly")


def _require_non_nil_uuid(value: object, name: str) -> None:
    """Require an actual non-nil :class:`uuid.UUID`; strings are not parsed."""
    if not isinstance(value, UUID):
        raise ValueError(f"{name} must be a uuid.UUID instance, not {type(value).__name__}")
    if value == uuid.UUID(int=0):
        raise ValueError(f"{name} must not be the nil UUID")


def _require_identity_string(value: object, name: str) -> None:
    """Require a nonempty string with no leading/trailing whitespace."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be a nonempty string equal to its own strip()")


def _require_microseconds(value: object, name: str) -> None:
    """Require a signed 64-bit int; ``bool`` is an ``int`` subclass and is rejected."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an int, not {type(value).__name__}")
    if not _INT64_MIN <= value <= _INT64_MAX:
        raise ValueError(f"{name} must fit in signed 64-bit range")


def _require_optional_microseconds(value: object, name: str) -> None:
    if value is not None:
        _require_microseconds(value, name)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """``object_pairs_hook`` that rejects duplicate keys at any nesting depth."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate object key in JSON: {key!r}")
        result[key] = value
    return result


def _reject_non_finite_constant(raw: str) -> float:
    """``parse_constant`` hook: JSON ``NaN``/``Infinity`` literals are invalid."""
    raise ValueError(f"non-finite JSON constant is not allowed: {raw}")


def _parse_finite_float(raw: str) -> float:
    """``parse_float`` hook: reject values that overflow to inf (e.g. ``1e999``)."""
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError(f"non-finite JSON number is not allowed: {raw}")
    return value


@dataclass(frozen=True, slots=True)
class CanonicalJsonObject:
    """An immutable, canonicalized JSON object held as a single string.

    The constructor accepts exactly one JSON object as text. It rejects
    invalid JSON, a non-object root, duplicate object keys at any nesting
    depth, non-finite numbers, and non-string input, all with ``ValueError``.
    Harmless whitespace and key-order differences normalize away: the stored
    ``text`` is always ``json.dumps(parsed, sort_keys=True, separators=(",", ":"),
    ensure_ascii=False, allow_nan=False)`` of the parsed object. String values
    are never altered and no request-fingerprint rule is applied here.

    The parsed temporary object is discarded; only the canonical string is
    retained. There is deliberately no parsed-object accessor and no dict-
    accepting constructor: callers with a Python object serialize it first.
    """

    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise ValueError(
                f"CanonicalJsonObject.text must be a str, not {type(self.text).__name__}"
            )
        try:
            parsed = json.loads(
                self.text,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_non_finite_constant,
                parse_float=_parse_finite_float,
            )
            if not isinstance(parsed, dict):
                raise ValueError("JSON root must be an object, not a scalar or array")
            canonical = json.dumps(
                parsed,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
        except (RecursionError, UnicodeEncodeError, ValueError) as exc:
            raise ValueError(f"CanonicalJsonObject requires one JSON object: {exc}") from exc
        object.__setattr__(self, "text", canonical)


@dataclass(frozen=True, slots=True)
class AdmissionTicket:
    """A claim ticket naming a scope, its admission generation, and lease owner.

    ``generation_id`` and ``owner_token`` are two independently generated
    UUIDs with independent identity roles; nothing here generates, equates, or
    compares them to each other. ``owner_token`` is excluded from ``repr``.
    """

    scope_key: str
    generation_id: UUID
    owner_token: UUID = field(repr=False)

    def __post_init__(self) -> None:
        _require_hex64(self.scope_key, "scope_key")
        _require_non_nil_uuid(self.generation_id, "generation_id")
        _require_non_nil_uuid(self.owner_token, "owner_token")


@dataclass(frozen=True, slots=True)
class RootAdmissionEnvelope:
    """The immutable identity facts of one root admission decision."""

    scope_key: str
    generation_id: UUID
    fingerprint: str
    workspace_id: str
    project_id: str
    origin_principal_id: str
    actor_principal_id: str
    action: str
    created_at_us: int
    expires_at_us: int
    receipt_id: str
    request_snapshot: CanonicalJsonObject
    receipt_snapshot: CanonicalJsonObject
    provenance_snapshot: CanonicalJsonObject

    def __post_init__(self) -> None:
        _require_hex64(self.scope_key, "scope_key")
        _require_non_nil_uuid(self.generation_id, "generation_id")
        _require_hex64(self.fingerprint, "fingerprint")
        _require_identity_string(self.workspace_id, "workspace_id")
        _require_identity_string(self.project_id, "project_id")
        _require_identity_string(self.origin_principal_id, "origin_principal_id")
        _require_identity_string(self.actor_principal_id, "actor_principal_id")
        _require_identity_string(self.action, "action")
        _require_identity_string(self.receipt_id, "receipt_id")
        _require_microseconds(self.created_at_us, "created_at_us")
        _require_microseconds(self.expires_at_us, "expires_at_us")
        if self.expires_at_us <= self.created_at_us:
            raise ValueError("expires_at_us must be strictly greater than created_at_us")
        for snapshot_name in ("request_snapshot", "receipt_snapshot", "provenance_snapshot"):
            if not isinstance(getattr(self, snapshot_name), CanonicalJsonObject):
                raise ValueError(f"{snapshot_name} must be a CanonicalJsonObject")


@dataclass(frozen=True, slots=True)
class AdmissionBinding:
    """The committed pairing of an admitted receipt to its canonical Run."""

    run_id: str
    receipt_id: str

    def __post_init__(self) -> None:
        _require_identity_string(self.run_id, "run_id")
        _require_identity_string(self.receipt_id, "receipt_id")


@dataclass(frozen=True, slots=True)
class AdmissionRecordV2:
    """A generation-fenced admission record with a separately fenced owner.

    The lease may lie in the past relative to a later observation; no DTO ever
    reads the current clock. ``owns`` is the pure fencing conjunction from the
    module docstring — a comparison helper, not an atomic mutation or
    permission to admit.
    """

    envelope: RootAdmissionEnvelope
    owner_token: UUID = field(repr=False)
    lease_expires_at_us: int
    binding: AdmissionBinding | None = None
    acknowledged_at_us: int | None = None
    format_version: Literal[2] = field(default=2, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.envelope, RootAdmissionEnvelope):
            raise ValueError(
                f"envelope must be a RootAdmissionEnvelope, not {type(self.envelope).__name__}"
            )
        _require_non_nil_uuid(self.owner_token, "owner_token")
        _require_microseconds(self.lease_expires_at_us, "lease_expires_at_us")
        if not (
            self.envelope.created_at_us <= self.lease_expires_at_us <= self.envelope.expires_at_us
        ):
            raise ValueError(
                "lease_expires_at_us must satisfy created_at_us <= lease <= expires_at_us"
            )
        if self.binding is not None:
            if not isinstance(self.binding, AdmissionBinding):
                raise ValueError(
                    f"binding must be an AdmissionBinding, not {type(self.binding).__name__}"
                )
            if self.binding.receipt_id != self.envelope.receipt_id:
                raise ValueError("binding.receipt_id must equal envelope.receipt_id")
        _require_optional_microseconds(self.acknowledged_at_us, "acknowledged_at_us")
        if self.acknowledged_at_us is not None:
            if self.binding is None:
                raise ValueError("acknowledged_at_us requires an existing binding")
            if self.acknowledged_at_us < self.envelope.created_at_us:
                raise ValueError("acknowledged_at_us cannot precede envelope creation")

    @property
    def admitted(self) -> bool:
        """Exactly ``binding is not None``."""
        return self.binding is not None

    def owns(self, ticket: AdmissionTicket) -> bool:
        """Pure fencing conjunction: scope AND generation AND owner token."""
        return (
            self.envelope.scope_key == ticket.scope_key
            and self.envelope.generation_id == ticket.generation_id
            and self.owner_token == ticket.owner_token
        )


@dataclass(frozen=True, slots=True)
class LegacyAdmissionRecord:
    """A pre-generation canonical admission row.

    Intentionally carries no generation ID, owner token, or fabricated
    candidate receipt. ``binding=None`` means the old row is unbound or
    ambiguous — it does not prove no Run committed. Legacy rows never clamped
    the pending lease to a replay window, so ``lease_expires_at_us`` here is
    validated for type and range only.
    """

    fingerprint: str
    request_snapshot: CanonicalJsonObject
    created_at_us: int
    expires_at_us: int
    lease_expires_at_us: int
    binding: AdmissionBinding | None = None
    format_version: Literal[1] = field(default=1, init=False)

    def __post_init__(self) -> None:
        _require_hex64(self.fingerprint, "fingerprint")
        if not isinstance(self.request_snapshot, CanonicalJsonObject):
            raise ValueError(
                f"request_snapshot must be a CanonicalJsonObject, not {type(self.request_snapshot).__name__}"
            )
        _require_microseconds(self.created_at_us, "created_at_us")
        _require_microseconds(self.expires_at_us, "expires_at_us")
        _require_microseconds(self.lease_expires_at_us, "lease_expires_at_us")
        if self.expires_at_us <= self.created_at_us:
            raise ValueError("expires_at_us must be strictly greater than created_at_us")
        if self.binding is not None and not isinstance(self.binding, AdmissionBinding):
            raise ValueError(
                f"binding must be an AdmissionBinding, not {type(self.binding).__name__}"
            )

    @property
    def admitted(self) -> bool:
        """Exactly ``binding is not None``."""
        return self.binding is not None


@dataclass(frozen=True, slots=True)
class RootAdmissionResult:
    """The outcome of a root admission: the bound identity plus a frozen Run.

    ``run_snapshot`` freezes what an earlier proposal carried as a mutable
    ``Run`` field. A later caller materializes a fresh Run from
    ``run_snapshot.text`` through the accepted canonical decoder when it needs
    one; full canonical Run/provenance validation remains the store's
    obligation. The constructor only verifies snapshot/run-id agreement.
    """

    run_id: str
    receipt_id: str
    run_snapshot: CanonicalJsonObject
    created: bool

    def __post_init__(self) -> None:
        _require_identity_string(self.run_id, "run_id")
        _require_identity_string(self.receipt_id, "receipt_id")
        if not isinstance(self.run_snapshot, CanonicalJsonObject):
            raise ValueError(
                f"run_snapshot must be a CanonicalJsonObject, not {type(self.run_snapshot).__name__}"
            )
        if not isinstance(self.created, bool):
            raise ValueError("created must be an actual bool, not an integer")
        snapshot = json.loads(self.run_snapshot.text)
        if not isinstance(snapshot, dict) or snapshot.get("run_id") != self.run_id:
            raise ValueError("run_snapshot must be an object whose run_id equals the result run_id")


@dataclass(frozen=True, slots=True)
class Claimed:
    """A fresh admission: the caller now holds this generation's lease."""

    ticket: AdmissionTicket
    record: AdmissionRecordV2

    def __post_init__(self) -> None:
        if not isinstance(self.ticket, AdmissionTicket):
            raise ValueError(f"ticket must be an AdmissionTicket, not {type(self.ticket).__name__}")
        if not isinstance(self.record, AdmissionRecordV2):
            raise ValueError(
                f"record must be an AdmissionRecordV2, not {type(self.record).__name__}"
            )
        if self.record.binding is not None:
            raise ValueError("Claimed requires a record with no binding")
        if not self.record.owns(self.ticket):
            raise ValueError("Claimed requires the record to own the ticket")


@dataclass(frozen=True, slots=True)
class Replayed:
    """An already-bound admission was asked for again; the binding is returned.

    A v2 binding is replayable even when it has not been acknowledged yet.
    """

    record: AdmissionRecordV2 | LegacyAdmissionRecord

    def __post_init__(self) -> None:
        if not isinstance(self.record, (AdmissionRecordV2, LegacyAdmissionRecord)):
            raise ValueError(
                f"record must be an AdmissionRecordV2 or LegacyAdmissionRecord, "
                f"not {type(self.record).__name__}"
            )
        if self.record.binding is None:
            raise ValueError("Replayed requires a record with an existing binding")


@dataclass(frozen=True, slots=True)
class Pending:
    """A live unbound v2 lease blocks this claim; the classifier, not this
    constructor, evaluates lease time."""

    record: AdmissionRecordV2

    def __post_init__(self) -> None:
        if not isinstance(self.record, AdmissionRecordV2):
            raise ValueError(
                f"record must be an AdmissionRecordV2, not {type(self.record).__name__}"
            )
        if self.record.binding is not None:
            raise ValueError("Pending requires an unbound v2 record")


@dataclass(frozen=True, slots=True)
class LegacyUnresolved:
    """An unbound legacy row leaves the claim ambiguous; nothing is invented."""

    record: LegacyAdmissionRecord

    def __post_init__(self) -> None:
        if not isinstance(self.record, LegacyAdmissionRecord):
            raise ValueError(
                f"record must be a LegacyAdmissionRecord, not {type(self.record).__name__}"
            )
        if self.record.binding is not None:
            raise ValueError("LegacyUnresolved requires an unbound legacy record")


#: Discriminated union of claim outcomes. Discriminate by variant type; none
#: of these overrides truthiness.
ClaimResult = Claimed | Replayed | Pending | LegacyUnresolved


@dataclass(frozen=True, slots=True)
class Released:
    """The lease was released by its owner."""


@dataclass(frozen=True, slots=True)
class AlreadyBound:
    """Release refused: the admission already committed a binding."""

    binding: AdmissionBinding

    def __post_init__(self) -> None:
        if not isinstance(self.binding, AdmissionBinding):
            raise ValueError(
                f"binding must be an AdmissionBinding, not {type(self.binding).__name__}"
            )


@dataclass(frozen=True, slots=True)
class StaleOwner:
    """The presented owner token no longer fences the persisted lease."""


@dataclass(frozen=True, slots=True)
class Acknowledged:
    """The binding was acknowledged for the first time."""


@dataclass(frozen=True, slots=True)
class AlreadyAcknowledged:
    """The binding was already acknowledged; the deadline is unchanged."""


@dataclass(frozen=True, slots=True)
class BindingMismatch:
    """The presented binding does not match the persisted binding."""


#: Discriminated union of release outcomes.
ReleaseResult = Released | AlreadyBound | StaleOwner | LegacyUnresolved

#: Discriminated union of acknowledgement outcomes.
CompletionResult = Acknowledged | AlreadyAcknowledged | StaleOwner | BindingMismatch


class AdmissionAssessment(StrEnum):
    """Prospective classifier values for the not-yet-wired C2 assessor.

    These do not replace the live ``_AssessmentKind`` values in
    :mod:`maistro.tasks.idempotency` in this leaf; nothing consumes them yet.
    """

    MISMATCH = "mismatch"
    REPLAYED = "replayed"
    PENDING = "pending"
    TAKEOVER = "takeover"
    REPLACE_EXPIRED = "replace_expired"
    LEGACY_UNRESOLVED = "legacy_unresolved"
