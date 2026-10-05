"""Pure replay-generation classifier for root admissions (#1852, parent #1845).

This module is an **inactive contract leaf**: nothing in production imports
it, and it must not be wired into the live claim loop by anything except a
later, separately reviewed integration change. It deliberately lives at its
own exact module path so that importing it cannot activate new result
variants in today's live four-variant claim loop
(:mod:`maistro.tasks.idempotency`), which is untouched here.

:func:`_assess` classifies one existing admission row — generation-fenced v2
or pre-generation legacy — for one arriving submission. It is the read-side
half of a future admission protocol: it never acquires a claim, never
authorizes a write, and never decides the absent-row INSERT case (that
belongs to the backend acquisition function). Every return value only tells a
future transaction what to recheck under lock; the backend must read/lock the
persisted row and revalidate all current predicates, including generation and
owner fencing where applicable, before acting.

Two distinct end-of-window outcomes:

- :attr:`AdmissionAssessment.REPLACE_EXPIRED` — the replay window is over, so
  a future transaction may acquire a *new* generation/candidate/deadline
  after rechecking expiry. This is why expiry is evaluated first and is
  inclusive: exactly at the stored deadline the key is free again, preserving
  the existing key-free-after-expiry contract even when the payload differs,
  a binding exists, a pending lease is old, or a legacy identity is
  unresolved.
- :attr:`AdmissionAssessment.TAKEOVER` — inside an unexpired, matching
  window, an unbound v2 lease whose short pending lease has lapsed may have
  *only its owner fence rotated*, preserving the original generation,
  request/receipt/provenance snapshots, and replay deadline.

An unbound legacy row inside its window is :attr:`AdmissionAssessment.
LEGACY_UNRESOLVED`, never takeover-eligible: the old two-commit gap cannot
prove whether a Run exists, so inventing a takeover could double-admit.

A populated canonical binding wins over lease status and the optional
acknowledgement within an unexpired matching window.
``acknowledged_at_us`` is deliberately not read: a failed ``complete`` must
not turn a committed admission into fresh work.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from maistro.runs.admission_identity import (
    AdmissionAssessment,
    AdmissionRecordV2,
    LegacyAdmissionRecord,
)

#: Incoming fingerprints are lowercase ASCII SHA-256 hex digests, same shape
#: the identity module enforces on stored ones. Validated here only; never
#: recomputed.
_FINGERPRINT_RE = re.compile(r"[0-9a-f]{64}")

_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1


def _assess(
    record: AdmissionRecordV2 | LegacyAdmissionRecord,
    *,
    fingerprint: str,
    now_us: int,
) -> AdmissionAssessment:
    """Classify an existing admission row for one arriving submission.

    Pure: reads only its arguments, never the current clock, a store, or any
    module state; generates nothing; logs nothing; mutates nothing; raises
    nothing but :class:`ValueError` for malformed input. ``MISMATCH`` is an
    assessment, not the live flow's :class:`IdempotencyKeyMismatch` — the
    existing exception/HTTP mapping stays where it is until integration.

    Args:
        record: One exact admission record class — an
            :class:`AdmissionRecordV2` (fields read through its envelope) or
            a :class:`LegacyAdmissionRecord` (top-level fields). ``None``,
            raw database rows, receipt-only shapes, and mutable dictionaries
            are rejected.
        fingerprint: The arriving submission's lowercase ``[0-9a-f]{64}``
            payload fingerprint.
        now_us: The caller's observation instant in microseconds, signed
            64-bit. ``bool`` is rejected although it is an ``int`` subclass.

    Returns:
        The :class:`AdmissionAssessment` for the row, decided in exactly this
        order: expiry (inclusive) first; then payload mismatch; then a
        populated binding (replayed); then an unbound legacy row
        (unresolved); then v2 lease state (takeover or pending).

    Raises:
        ValueError: If ``record`` is neither exact record class, or
            ``fingerprint``/``now_us`` is malformed.
    """
    if not isinstance(record, (AdmissionRecordV2, LegacyAdmissionRecord)):
        raise ValueError(
            "record must be an AdmissionRecordV2 or LegacyAdmissionRecord, "
            f"not {type(record).__name__}"
        )
    if not isinstance(fingerprint, str) or _FINGERPRINT_RE.fullmatch(fingerprint) is None:
        raise ValueError("fingerprint must match lowercase [0-9a-f]{64} exactly")
    # ``bool`` is an ``int`` subclass and is rejected; the range check is
    # short-circuit-safe because ``or`` only reaches it for real ints.
    if (
        isinstance(now_us, bool)
        or not isinstance(now_us, int)
        or not _INT64_MIN <= now_us <= _INT64_MAX
    ):
        raise ValueError(f"now_us must be a signed 64-bit int, not {type(now_us).__name__}")

    if isinstance(record, AdmissionRecordV2):
        expires_at_us = record.envelope.expires_at_us
        stored_fingerprint = record.envelope.fingerprint
    else:
        expires_at_us = record.expires_at_us
        stored_fingerprint = record.fingerprint

    # The fixed decision order as data: rows evaluated top to bottom, first
    # match wins, so the issue's branch order is the tuple's row order and
    # each row's predicate is the one comparison the branch performs. Every
    # predicate is deferred (a zero-argument callable read at match time),
    # which keeps short-circuiting exact: the v2-only lease comparison in the
    # last row is never evaluated for a legacy row, because the row above it
    # matches first and returns. Nothing past this table reads a record.
    decision_order: tuple[tuple[Callable[[], bool], AdmissionAssessment], ...] = (
        # Expiry is inclusive and wins over everything: exactly at the stored
        # deadline the replay window is over and the key is free, whatever the
        # payload, binding, lease, or legacy ambiguity says.
        (lambda: expires_at_us <= now_us, AdmissionAssessment.REPLACE_EXPIRED),
        (lambda: stored_fingerprint != fingerprint, AdmissionAssessment.MISMATCH),
        (lambda: record.binding is not None, AdmissionAssessment.REPLAYED),
        (lambda: isinstance(record, LegacyAdmissionRecord), AdmissionAssessment.LEGACY_UNRESOLVED),
        (lambda: record.lease_expires_at_us <= now_us, AdmissionAssessment.TAKEOVER),
    )
    for matches, outcome in decision_order:
        if matches():
            return outcome
    return AdmissionAssessment.PENDING
