"""Contract tests for the inactive #1852 admission-generation classifier.

Every decision-order row of the #1852 matrix is exercised at its exact
boundary and +/-1 microsecond where meaningful, with a fixed ``now_us``: no
sleeps, no free-running clocks, and no database fixtures. The unchanged live
four-variant flow in :mod:`maistro.tasks.idempotency` is called alongside the
new classifier to prove the separate module path activated nothing there.
"""

from __future__ import annotations

import contextlib
import logging
import time
import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import get_args

import pytest

from maistro.runs.admission_identity import (
    AdmissionAssessment,
    AdmissionBinding,
    AdmissionRecordV2,
    CanonicalJsonObject,
    LegacyAdmissionRecord,
    RootAdmissionEnvelope,
)
from maistro.tasks import admission_generation, idempotency

FP = "a" * 64
FP_OTHER = "b" * 64

CREATED_AT_US = 1_000_000_000_000_000
REPLAY_WINDOW_US = 3_600_000_000  # one hour, microseconds
EXPIRES_AT_US = CREATED_AT_US + REPLAY_WINDOW_US
#: A typical mid-window observation instant (1s after creation).
MID_US = CREATED_AT_US + 1_000_000
#: The unbound v2 pending lease (~live ``PENDING_LEASE`` style short lease).
PENDING_LEASE_US = CREATED_AT_US + 60_000_000

_GENERATION_ID = uuid.UUID(int=0x11111111111111111111111111111111)
_OWNER_TOKEN = uuid.UUID(int=0x22222222222222222222222222222222)
_RECEIPT_ID = "receipt-1"


def _envelope(fingerprint: str = FP) -> RootAdmissionEnvelope:
    return RootAdmissionEnvelope(
        scope_key="c" * 64,
        generation_id=_GENERATION_ID,
        fingerprint=fingerprint,
        workspace_id="ws-1",
        project_id="proj-1",
        origin_principal_id="principal-origin",
        actor_principal_id="principal-actor",
        action="task.create",
        created_at_us=CREATED_AT_US,
        expires_at_us=EXPIRES_AT_US,
        receipt_id=_RECEIPT_ID,
        request_snapshot=CanonicalJsonObject('{"kind":"request"}'),
        receipt_snapshot=CanonicalJsonObject('{"kind":"receipt"}'),
        provenance_snapshot=CanonicalJsonObject('{"kind":"provenance"}'),
    )


def _binding() -> AdmissionBinding:
    return AdmissionBinding(run_id="run-1", receipt_id=_RECEIPT_ID)


def _v2(
    *,
    fingerprint: str = FP,
    lease_expires_at_us: int = PENDING_LEASE_US,
    bound: bool = False,
    acknowledged: bool = False,
) -> AdmissionRecordV2:
    """Build a v2 record; ``lease_expires_at_us`` is clamped to the window."""
    lease = min(max(lease_expires_at_us, CREATED_AT_US), EXPIRES_AT_US)
    return AdmissionRecordV2(
        envelope=_envelope(fingerprint),
        owner_token=_OWNER_TOKEN,
        lease_expires_at_us=lease,
        binding=_binding() if bound else None,
        acknowledged_at_us=CREATED_AT_US + 500 if acknowledged else None,
    )


def _legacy(
    *,
    fingerprint: str = FP,
    lease_expires_at_us: int = PENDING_LEASE_US,
    bound: bool = False,
) -> LegacyAdmissionRecord:
    """Build a legacy row; its lease is type/range-validated only."""
    return LegacyAdmissionRecord(
        fingerprint=fingerprint,
        request_snapshot=CanonicalJsonObject('{"kind":"request"}'),
        created_at_us=CREATED_AT_US,
        expires_at_us=EXPIRES_AT_US,
        lease_expires_at_us=lease_expires_at_us,
        binding=_binding() if bound else None,
    )


# ---------------------------------------------------------------------------
# Input validation: ValueError, never anything else.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "record",
    [
        None,
        {},
        {"fingerprint": FP, "expires_at_us": EXPIRES_AT_US},
        SimpleNamespace(fingerprint=FP, expires_at_us=EXPIRES_AT_US),
        object(),
        # The live flow's record type is a raw-row stand-in, not one of the
        # two exact record classes: it must not sneak past the classifier.
        idempotency.AdmissionRecord(
            fingerprint=FP,
            request="{}",
            task_id=None,
            run_id=None,
            created_at_us=CREATED_AT_US,
            expires_at_us=EXPIRES_AT_US,
            lease_expires_at_us=PENDING_LEASE_US,
        ),
    ],
)
def test_rejects_non_record_inputs(record: object) -> None:
    with pytest.raises(ValueError, match="record must be"):
        admission_generation._assess(record, fingerprint=FP, now_us=MID_US)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "fingerprint",
    [None, 123, "", "A" * 64, "a" * 63, "a" * 65, "g" * 64, FP.upper(), "a" * 32 + "A" * 32],
)
def test_rejects_malformed_fingerprints(fingerprint: object) -> None:
    with pytest.raises(ValueError, match="fingerprint"):
        admission_generation._assess(
            _v2(),  # type: ignore[arg-type]
            fingerprint=fingerprint,  # type: ignore[arg-type]
            now_us=MID_US,
        )


@pytest.mark.parametrize(
    "now_us",
    [None, True, False, 1.0, "1", MID_US + 0.5, -(2**63) - 1, 2**63],
)
def test_rejects_malformed_now_us(now_us: object) -> None:
    with pytest.raises(ValueError, match="now_us"):
        admission_generation._assess(
            _v2(),  # type: ignore[arg-type]
            fingerprint=FP,
            now_us=now_us,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("factory", [_v2, _legacy])
def test_accepts_signed_int64_boundary_now_us(factory: type) -> None:
    expired_row = factory()
    assert (
        admission_generation._assess(expired_row, fingerprint=FP, now_us=2**63 - 1)
        == AdmissionAssessment.REPLACE_EXPIRED
    )
    fresh_row = factory(lease_expires_at_us=CREATED_AT_US + 60_000_000)
    expected = (
        AdmissionAssessment.PENDING if factory is _v2 else AdmissionAssessment.LEGACY_UNRESOLVED
    )
    assert admission_generation._assess(fresh_row, fingerprint=FP, now_us=-(2**63)) == expected


# ---------------------------------------------------------------------------
# Decision row: v2, unexpired, different fingerprint, any valid state.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("now_us", [MID_US, EXPIRES_AT_US - 1])
@pytest.mark.parametrize(
    "record",
    [
        _v2(bound=True, acknowledged=True),
        _v2(bound=True),
        _v2(bound=False, lease_expires_at_us=PENDING_LEASE_US),
        _v2(bound=False, lease_expires_at_us=MID_US),
        _v2(bound=False, lease_expires_at_us=CREATED_AT_US),
    ],
    ids=["bound-ack", "bound-unack", "unbound-live-lease", "unbound-lease-now", "unbound-lapsed"],
)
def test_v2_mismatch_inside_window(record: AdmissionRecordV2, now_us: int) -> None:
    assert (
        admission_generation._assess(record, fingerprint=FP_OTHER, now_us=now_us)
        == AdmissionAssessment.MISMATCH
    )


# ---------------------------------------------------------------------------
# Decision row: v2, unexpired, same fingerprint, bound (ack read or not).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("acknowledged", [True, False])
@pytest.mark.parametrize(
    "lease_expires_at_us",
    [PENDING_LEASE_US, MID_US, CREATED_AT_US],
    ids=["live-lease", "lease-now", "lapsed-lease"],
)
def test_v2_binding_wins_over_lease_and_acknowledgement(
    acknowledged: bool, lease_expires_at_us: int
) -> None:
    record = _v2(bound=True, acknowledged=acknowledged, lease_expires_at_us=lease_expires_at_us)
    for now_us in (MID_US, EXPIRES_AT_US - 1):
        assert (
            admission_generation._assess(record, fingerprint=FP, now_us=now_us)
            == AdmissionAssessment.REPLAYED
        )


def test_v2_acknowledgement_is_deliberately_unread() -> None:
    """Only the ack flag differs; the assessment cannot tell them apart."""
    unacknowledged = _v2(bound=True, acknowledged=False)
    acknowledged = _v2(bound=True, acknowledged=True)
    assert unacknowledged.acknowledged_at_us is None
    assert acknowledged.acknowledged_at_us is not None
    for record in (unacknowledged, acknowledged):
        assert (
            admission_generation._assess(record, fingerprint=FP, now_us=MID_US)
            == AdmissionAssessment.REPLAYED
        )


# ---------------------------------------------------------------------------
# Decision rows: v2, unexpired, same fingerprint, unbound — lease boundaries.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("now_us", "expected"),
    [
        (PENDING_LEASE_US - 1, AdmissionAssessment.PENDING),
        (PENDING_LEASE_US, AdmissionAssessment.TAKEOVER),
        (PENDING_LEASE_US + 1, AdmissionAssessment.TAKEOVER),
    ],
    ids=["one-us-before-lease", "exactly-at-lease", "one-us-after-lease"],
)
def test_v2_unbound_lease_boundaries(now_us: int, expected: AdmissionAssessment) -> None:
    record = _v2(bound=False, lease_expires_at_us=PENDING_LEASE_US)
    assert admission_generation._assess(record, fingerprint=FP, now_us=now_us) == expected


# ---------------------------------------------------------------------------
# Decision rows: legacy, unexpired.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bound", [True, False])
@pytest.mark.parametrize("now_us", [MID_US, EXPIRES_AT_US - 1])
def test_legacy_mismatch_inside_window(bound: bool, now_us: int) -> None:
    record = _legacy(bound=bound)
    assert (
        admission_generation._assess(record, fingerprint=FP_OTHER, now_us=now_us)
        == AdmissionAssessment.MISMATCH
    )


def test_legacy_bound_replays_inside_window() -> None:
    record = _legacy(bound=True)
    for now_us in (MID_US, EXPIRES_AT_US - 1):
        assert (
            admission_generation._assess(record, fingerprint=FP, now_us=now_us)
            == AdmissionAssessment.REPLAYED
        )


@pytest.mark.parametrize(
    ("now_us", "lease_expires_at_us"),
    [
        (PENDING_LEASE_US - 1, PENDING_LEASE_US),
        (PENDING_LEASE_US, PENDING_LEASE_US),
        (PENDING_LEASE_US + 1, PENDING_LEASE_US),
        # Legacy rows never clamped the lease to the replay window; an
        # out-of-window lease is still just "unbound legacy" inside it.
        (MID_US, EXPIRES_AT_US + 60_000_000),
    ],
    ids=["before-lease", "at-lease", "after-lease", "lease-beyond-window"],
)
def test_legacy_unbound_is_never_takeover_eligible(now_us: int, lease_expires_at_us: int) -> None:
    record = _legacy(bound=False, lease_expires_at_us=lease_expires_at_us)
    assert now_us < EXPIRES_AT_US
    assert (
        admission_generation._assess(record, fingerprint=FP, now_us=now_us)
        == AdmissionAssessment.LEGACY_UNRESOLVED
    )


# ---------------------------------------------------------------------------
# Decision row: either record, expired or exactly at the deadline, any
# fingerprint, any valid state — the key is free again.
# ---------------------------------------------------------------------------


def _all_valid_rows() -> list[tuple[str, AdmissionRecordV2 | LegacyAdmissionRecord]]:
    return [
        ("v2-bound-ack", _v2(bound=True, acknowledged=True)),
        ("v2-bound-unack", _v2(bound=True)),
        ("v2-unbound-live-lease", _v2(bound=False)),
        ("v2-unbound-lapsed", _v2(bound=False, lease_expires_at_us=CREATED_AT_US)),
        ("legacy-bound", _legacy(bound=True)),
        ("legacy-unbound", _legacy(bound=False)),
        (
            "legacy-unbound-beyond-window",
            _legacy(bound=False, lease_expires_at_us=EXPIRES_AT_US + 1),
        ),
    ]


@pytest.mark.parametrize("fingerprint", [FP, FP_OTHER])
@pytest.mark.parametrize(
    "now_us", [EXPIRES_AT_US, EXPIRES_AT_US + 1], ids=["at-deadline", "past-deadline"]
)
@pytest.mark.parametrize(
    ["name", "record"],
    [(name, record) for name, record in _all_valid_rows()],
    ids=[name for name, _ in _all_valid_rows()],
)
def test_expiry_is_inclusive_and_wins_over_everything(
    name: str, record: AdmissionRecordV2 | LegacyAdmissionRecord, now_us: int, fingerprint: str
) -> None:
    assert (
        admission_generation._assess(record, fingerprint=fingerprint, now_us=now_us)
        == AdmissionAssessment.REPLACE_EXPIRED
    )


# ---------------------------------------------------------------------------
# The one-microsecond flips around the inclusive expiry boundary.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ["record", "fingerprint", "inside", "at_deadline"],
    [
        # Changed payload: visible MISMATCH one microsecond before expiry —
        # even with a lapsed pending lease, or against a legacy pending row —
        # swallowed by REPLACE_EXPIRED exactly at the deadline.
        (
            _v2(bound=False, lease_expires_at_us=CREATED_AT_US),
            FP_OTHER,
            AdmissionAssessment.MISMATCH,
            AdmissionAssessment.REPLACE_EXPIRED,
        ),
        (
            _legacy(bound=False),
            FP_OTHER,
            AdmissionAssessment.MISMATCH,
            AdmissionAssessment.REPLACE_EXPIRED,
        ),
        # Bound matching row: REPLAYED inside, free at the deadline.
        (
            _v2(bound=True, acknowledged=True),
            FP,
            AdmissionAssessment.REPLAYED,
            AdmissionAssessment.REPLACE_EXPIRED,
        ),
        # Unresolved legacy row: never takeover-eligible inside, free at the
        # deadline.
        (
            _legacy(bound=False, lease_expires_at_us=CREATED_AT_US),
            FP,
            AdmissionAssessment.LEGACY_UNRESOLVED,
            AdmissionAssessment.REPLACE_EXPIRED,
        ),
    ],
    ids=["v2-lapsed-mismatch", "legacy-mismatch", "v2-bound", "legacy-unresolved"],
)
def test_expiry_boundary_flips_at_exactly_expires_at_us(
    record: AdmissionRecordV2 | LegacyAdmissionRecord,
    fingerprint: str,
    inside: AdmissionAssessment,
    at_deadline: AdmissionAssessment,
) -> None:
    assert (
        admission_generation._assess(record, fingerprint=fingerprint, now_us=EXPIRES_AT_US - 1)
        == inside
    )
    assert (
        admission_generation._assess(record, fingerprint=fingerprint, now_us=EXPIRES_AT_US)
        == at_deadline
    )


def test_replace_expired_is_distinct_from_takeover_at_the_same_instant() -> None:
    """A lapsed pending lease inside the window asks for owner-fence rotation
    (TAKEOVER); the very same row at the replay deadline asks for a new
    generation (REPLACE_EXPIRED)."""
    record = _v2(bound=False, lease_expires_at_us=PENDING_LEASE_US)
    assert (
        admission_generation._assess(record, fingerprint=FP, now_us=PENDING_LEASE_US)
        == AdmissionAssessment.TAKEOVER
    )
    assert (
        admission_generation._assess(record, fingerprint=FP, now_us=EXPIRES_AT_US)
        == AdmissionAssessment.REPLACE_EXPIRED
    )
    assert AdmissionAssessment.TAKEOVER != AdmissionAssessment.REPLACE_EXPIRED


# ---------------------------------------------------------------------------
# Purity: no clock, no sleep, no logging, no mutation.
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _forbidden_clock_and_sleep() -> Iterator[None]:
    """Forbid ``time.*`` only while the context is held: pytest's own runner
    timestamps the test with ``time.monotonic`` and must keep working once the
    assessment call has returned, so restoration happens inside the test
    body, never at teardown."""

    def _raise(name: str):
        def _boom(*args: object, **kwargs: object) -> None:
            raise AssertionError(f"_assess must not call time.{name}")

        return _boom

    forbidden = (
        "time",
        "time_ns",
        "monotonic",
        "monotonic_ns",
        "perf_counter",
        "perf_counter_ns",
        "sleep",
    )
    originals = {name: getattr(time, name) for name in forbidden}
    for name in forbidden:
        setattr(time, name, _raise(name))
    try:
        yield
    finally:
        for name, original in originals.items():
            setattr(time, name, original)


@pytest.mark.parametrize("factory", [_v2, _legacy])
def test_pure_against_clock_sleep_and_logs(factory: type, caplog: pytest.LogCaptureFixture) -> None:
    record = factory(bound=True)
    with caplog.at_level(logging.DEBUG), _forbidden_clock_and_sleep():
        assessment = admission_generation._assess(record, fingerprint=FP, now_us=MID_US)
    assert assessment == AdmissionAssessment.REPLAYED
    assert caplog.records == []


@pytest.mark.parametrize("factory", [_v2, _legacy])
def test_never_mutates_the_record(factory: type) -> None:
    kwargs: dict[str, object] = {"bound": True}
    record = factory(**kwargs)  # type: ignore[arg-type]
    pristine = factory(**kwargs)  # type: ignore[arg-type]
    assert record == pristine
    admission_generation._assess(record, fingerprint=FP, now_us=MID_US)
    admission_generation._assess(record, fingerprint=FP_OTHER, now_us=EXPIRES_AT_US)
    assert record == pristine


# ---------------------------------------------------------------------------
# The unchanged live four-variant flow (called, not edited).
# ---------------------------------------------------------------------------


def _live_record(
    *,
    fingerprint: str = FP,
    admitted: bool = False,
    expired: bool = False,
    lease_past: bool = False,
) -> idempotency.AdmissionRecord:
    return idempotency.AdmissionRecord(
        fingerprint=fingerprint,
        request="{}",
        task_id="task-1" if admitted else None,
        run_id="run-1" if admitted else None,
        created_at_us=CREATED_AT_US,
        expires_at_us=MID_US if expired else EXPIRES_AT_US,
        lease_expires_at_us=CREATED_AT_US if lease_past else PENDING_LEASE_US,
    )


def test_live_flow_still_has_exactly_four_variants() -> None:
    assert get_args(idempotency._AssessmentKind) == (
        "mismatch",
        "replayed",
        "pending",
        "takeover",
    )


@pytest.mark.parametrize(
    ("record", "now_us", "expected"),
    [
        (_live_record(admitted=True), MID_US, "replayed"),
        (_live_record(), MID_US, "pending"),
        (_live_record(lease_past=True), MID_US, "takeover"),
        (_live_record(expired=True), MID_US, "takeover"),
        (_live_record(fingerprint=FP_OTHER), MID_US, "mismatch"),
        (_live_record(fingerprint=FP_OTHER, expired=True), MID_US, "takeover"),
    ],
    ids=["admitted", "pending", "lease-past", "expired", "mismatch", "expired-mismatch"],
)
def test_live_flow_answers_are_unchanged(
    record: idempotency.AdmissionRecord, now_us: int, expected: str
) -> None:
    assert idempotency._assess(record, fingerprint=FP, now_us=now_us) == expected


@pytest.mark.parametrize(
    ("record", "now_us", "expected"),
    [
        (_live_record(expired=True), MID_US, True),
        (_live_record(lease_past=True), MID_US, True),
        (_live_record(admitted=True), MID_US, False),
        (_live_record(), MID_US, False),
    ],
    ids=["expired", "lease-past", "admitted", "pending"],
)
def test_live_takeover_guard_is_unchanged(
    record: idempotency.AdmissionRecord, now_us: int, expected: bool
) -> None:
    assert idempotency._takeover_guard_holds(record, now_us) is expected


def test_new_variants_exist_only_on_the_new_path() -> None:
    """At the same instant on the same story, the live flow still answers its
    four-variant ``"takeover"`` where the new classifier distinguishes
    ``REPLACE_EXPIRED``; and the live flow still answers ``"takeover"`` for an
    expired *mismatched* payload where the new classifier puts expiry first."""
    live_expired_match = _live_record(expired=True)
    live_expired_mismatch = _live_record(fingerprint=FP_OTHER, expired=True)
    assert idempotency._assess(live_expired_match, fingerprint=FP, now_us=MID_US) == "takeover"
    assert idempotency._assess(live_expired_mismatch, fingerprint=FP, now_us=MID_US) == "takeover"

    v2_expired_match = _v2(bound=False)
    legacy_expired_mismatch = _legacy(fingerprint=FP_OTHER, bound=False)
    assert (
        admission_generation._assess(v2_expired_match, fingerprint=FP, now_us=EXPIRES_AT_US)
        == AdmissionAssessment.REPLACE_EXPIRED
    )
    assert (
        admission_generation._assess(legacy_expired_mismatch, fingerprint=FP, now_us=EXPIRES_AT_US)
        == AdmissionAssessment.REPLACE_EXPIRED
    )


def test_replay_vs_legacy_split_on_identical_facts() -> None:
    """With matching payloads and no binding, v2 lease state decides while a
    legacy row stays unresolved — the two record classes diverge only there."""
    v2_unbound = _v2(bound=False, lease_expires_at_us=PENDING_LEASE_US)
    legacy_unbound = _legacy(bound=False, lease_expires_at_us=PENDING_LEASE_US)
    assert (
        admission_generation._assess(v2_unbound, fingerprint=FP, now_us=PENDING_LEASE_US)
        == AdmissionAssessment.TAKEOVER
    )
    assert (
        admission_generation._assess(legacy_unbound, fingerprint=FP, now_us=PENDING_LEASE_US)
        == AdmissionAssessment.LEGACY_UNRESOLVED
    )
    v2_bound = _v2(bound=True)
    legacy_bound = _legacy(bound=True)
    for record in (v2_bound, legacy_bound):
        assert (
            admission_generation._assess(record, fingerprint=FP, now_us=MID_US)
            == AdmissionAssessment.REPLAYED
        )
