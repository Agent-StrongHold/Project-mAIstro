"""Contract tests for the inactive root-admission identity types (#1851).

These tests pin the DTO contract only: canonical JSON snapshots, fencing
conjunctions, variant validation, and repr hygiene. Passing them proves the
type contract, not atomicity, wiring, or resolution of the parent #1845
admission design — the module has no runtime consumer in this leaf.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import FrozenInstanceError, fields

import pytest

import maistro.runs.admission_identity as admission_identity
from maistro.runs.admission_identity import (
    Acknowledged,
    AdmissionBinding,
    AdmissionRecordV2,
    AdmissionTicket,
    AlreadyBound,
    CanonicalJsonObject,
    Claimed,
    LegacyAdmissionRecord,
    LegacyUnresolved,
    Pending,
    Replayed,
    RootAdmissionEnvelope,
    RootAdmissionResult,
    StaleOwner,
)

_SCOPE = "aa" * 32
_OTHER_SCOPE = "bb" * 32
_FINGERPRINT = "cc" * 32

_CREATED_US = 1_700_000_000_000_000
_EXPIRES_US = _CREATED_US + 86_400_000_000  # 24h replay window
_LEASE_US = _CREATED_US + 30_000_000  # 30s pending lease

_GENERATION = uuid.UUID("11111111-1111-2111-8111-111111111111")
_OWNER = uuid.UUID("22222222-2222-3222-9222-222222222222")


def _ticket(
    *,
    scope_key: str = _SCOPE,
    generation_id: uuid.UUID = _GENERATION,
    owner_token: uuid.UUID = _OWNER,
) -> AdmissionTicket:
    return AdmissionTicket(
        scope_key=scope_key, generation_id=generation_id, owner_token=owner_token
    )


def _envelope(**overrides: object) -> RootAdmissionEnvelope:
    values: dict[str, object] = {
        "scope_key": _SCOPE,
        "generation_id": _GENERATION,
        "fingerprint": _FINGERPRINT,
        "workspace_id": "w1",
        "project_id": "p1",
        "origin_principal_id": "origin-principal",
        "actor_principal_id": "actor-principal",
        "action": "create_root",
        "created_at_us": _CREATED_US,
        "expires_at_us": _EXPIRES_US,
        "receipt_id": "receipt-1",
        "request_snapshot": CanonicalJsonObject(text='{"task": {"name": "root"}}'),
        "receipt_snapshot": CanonicalJsonObject(text='{"receipt_id": "receipt-1"}'),
        "provenance_snapshot": CanonicalJsonObject(text='{"source": "api"}'),
    }
    values.update(overrides)
    return RootAdmissionEnvelope(**values)  # type: ignore[arg-type]


def _record(**overrides: object) -> AdmissionRecordV2:
    values: dict[str, object] = {
        "envelope": _envelope(),
        "owner_token": _OWNER,
        "lease_expires_at_us": _LEASE_US,
    }
    values.update(overrides)
    return AdmissionRecordV2(**values)  # type: ignore[arg-type]


def _binding(receipt_id: str = "receipt-1", run_id: str = "run-1") -> AdmissionBinding:
    return AdmissionBinding(run_id=run_id, receipt_id=receipt_id)


def _legacy(**overrides: object) -> LegacyAdmissionRecord:
    values: dict[str, object] = {
        "fingerprint": _FINGERPRINT,
        "request_snapshot": CanonicalJsonObject(text='{"task": {"name": "root"}}'),
        "created_at_us": _CREATED_US,
        "expires_at_us": _EXPIRES_US,
        "lease_expires_at_us": _LEASE_US,
    }
    values.update(overrides)
    return LegacyAdmissionRecord(**values)  # type: ignore[arg-type]


def _run_snapshot(run_id: str = "run-1") -> CanonicalJsonObject:
    return CanonicalJsonObject(text=json.dumps({"run_id": run_id, "status": "pending"}))


# --- module-local API ------------------------------------------------------


def test_module_exports_exact_contract_and_assessment_values() -> None:
    assert len(admission_identity.__all__) == 21
    assert set(admission_identity.__all__) == {
        "CanonicalJsonObject",
        "AdmissionTicket",
        "RootAdmissionEnvelope",
        "AdmissionBinding",
        "AdmissionRecordV2",
        "LegacyAdmissionRecord",
        "RootAdmissionResult",
        "Claimed",
        "Replayed",
        "Pending",
        "LegacyUnresolved",
        "ClaimResult",
        "Released",
        "AlreadyBound",
        "StaleOwner",
        "Acknowledged",
        "AlreadyAcknowledged",
        "BindingMismatch",
        "ReleaseResult",
        "CompletionResult",
        "AdmissionAssessment",
    }
    assert tuple(
        (member.name, member.value) for member in admission_identity.AdmissionAssessment
    ) == (
        ("MISMATCH", "mismatch"),
        ("REPLAYED", "replayed"),
        ("PENDING", "pending"),
        ("TAKEOVER", "takeover"),
        ("REPLACE_EXPIRED", "replace_expired"),
        ("LEGACY_UNRESOLVED", "legacy_unresolved"),
    )


# --- canonical JSON snapshots ---------------------------------------------


def test_canonical_json_normalizes_without_retaining_mutable_objects() -> None:
    loose = CanonicalJsonObject(text='{\n  "b" : 2,  "a": "1"\n}')
    tight = CanonicalJsonObject(text='{"a":"1","b":2}')
    assert loose.text == tight.text == '{"a":"1","b":2}'

    # String values are never altered by normalization.
    spaced = CanonicalJsonObject(text='{"k": "  padded  "}')
    assert spaced.text == '{"k":"  padded  "}'

    # Non-ASCII survives unescaped (ensure_ascii=False) and round-trips.
    unicode_obj = CanonicalJsonObject(text='{"k": "café"}')
    assert unicode_obj.text == '{"k":"café"}'
    assert json.loads(unicode_obj.text) == {"k": "café"}

    # Only the canonical string is stored: the temporary parsed object is gone,
    # there is no mutable parsed-object accessor, and the field is a plain str.
    assert type(loose.text) is str
    declared = {f.name for f in fields(CanonicalJsonObject)}
    assert declared == {"text"}
    for attr in ("object", "parsed", "value", "data", "to_object", "as_object", "json"):
        assert not hasattr(loose, attr), attr


@pytest.mark.parametrize(
    "bad_text",
    [
        pytest.param('{"a": 1, "a": 2}', id="duplicate-key-top-level"),
        pytest.param('{"o": {"k": 1, "k": 2}}', id="duplicate-key-nested"),
        pytest.param('[{"x": 1}, {"x": 2, "x": 3}]', id="duplicate-key-in-array"),
        pytest.param('{"x": NaN}', id="nan-literal"),
        pytest.param('{"x": Infinity}', id="infinity-literal"),
        pytest.param('{"x": -Infinity}', id="negative-infinity-literal"),
        pytest.param('{"x": 1e999}', id="float-overflow-to-inf"),
        pytest.param("[1, 2]", id="array-root"),
        pytest.param('"just a string"', id="string-root"),
        pytest.param("42", id="int-root"),
        pytest.param("null", id="null-root"),
        pytest.param("{", id="invalid-json"),
        pytest.param("", id="empty-input"),
        pytest.param('{"a": 1} trailing', id="extra-data-after-object"),
    ],
)
def test_canonical_json_rejects_duplicate_keys_nonfinite_and_nonobject_roots(
    bad_text: str,
) -> None:
    with pytest.raises(ValueError):
        CanonicalJsonObject(text=bad_text)


@pytest.mark.parametrize(
    "bad_input",
    [
        pytest.param({"a": 1}, id="dict-input"),
        pytest.param(["a"], id="list-input"),
        pytest.param(b'{"a": 1}', id="bytes-input"),
        pytest.param(42, id="int-input"),
        pytest.param(None, id="none-input"),
    ],
)
def test_canonical_json_rejects_non_string_constructor_input(bad_input: object) -> None:
    with pytest.raises(ValueError):
        CanonicalJsonObject(text=bad_input)  # type: ignore[arg-type]


# --- immutability ----------------------------------------------------------


def test_identity_dtos_are_frozen_and_snapshot_fields_are_immutable() -> None:
    snap = CanonicalJsonObject(text='{"a": 1}')
    with pytest.raises(FrozenInstanceError):
        snap.text = "{}"  # type: ignore[misc]

    ticket = _ticket()
    with pytest.raises(FrozenInstanceError):
        ticket.scope_key = _OTHER_SCOPE  # type: ignore[misc]

    binding = _binding()
    with pytest.raises(FrozenInstanceError):
        binding.run_id = "run-2"  # type: ignore[misc]

    envelope = _envelope()
    with pytest.raises(FrozenInstanceError):
        envelope.fingerprint = "dd" * 32  # type: ignore[misc]

    record = _record()
    with pytest.raises(FrozenInstanceError):
        record.lease_expires_at_us = _LEASE_US + 1  # type: ignore[misc]

    legacy = _legacy()
    with pytest.raises(FrozenInstanceError):
        legacy.fingerprint = "dd" * 32  # type: ignore[misc]

    result = RootAdmissionResult(
        run_id="run-1", receipt_id="receipt-1", run_snapshot=_run_snapshot(), created=True
    )
    with pytest.raises(FrozenInstanceError):
        result.created = False  # type: ignore[misc]

    # Mutating the frozen snapshot object cannot leak into a holder DTO.
    holder = _record()
    with pytest.raises(FrozenInstanceError):
        holder.envelope.request_snapshot = CanonicalJsonObject(text="{}")  # type: ignore[misc]


# --- fencing ----------------------------------------------------------------


def test_ticket_ownership_requires_scope_generation_and_owner() -> None:
    record = _record()
    assert record.owns(_ticket()) is True
    assert record.admitted is False

    same_owner_new_generation = uuid.UUID("33333333-3333-4333-8333-333333333333")
    assert (
        record.owns(_ticket(generation_id=same_owner_new_generation, owner_token=_OWNER)) is False
    )
    assert record.owns(_ticket(generation_id=_GENERATION, owner_token=_GENERATION)) is False
    assert record.owns(_ticket(scope_key=_OTHER_SCOPE)) is False


def test_generation_and_owner_are_not_compared_to_each_other() -> None:
    # The two roles may coincide; a matching ticket still wins because each
    # role is compared only against its own ticket field.
    single = uuid.UUID("44444444-4444-5444-8444-444444444444")
    coincide_record = _record(envelope=_envelope(generation_id=single), owner_token=single)
    coincide_ticket = _ticket(generation_id=single, owner_token=single)
    assert coincide_record.owns(coincide_ticket) is True

    # They may also differ; the comparison never relates them to each other.
    distinct_record = _record()
    assert distinct_record.owns(_ticket()) is True
    assert distinct_record.envelope.generation_id != distinct_record.owner_token

    # A ticket whose owner token equals the record's generation id does not
    # own the lease: the owner role is checked against the owner role only.
    assert distinct_record.owns(_ticket(owner_token=_GENERATION)) is False


# --- binding and acknowledgement --------------------------------------------


def test_binding_preserves_original_receipt_identity() -> None:
    record = _record(binding=_binding(receipt_id="receipt-1", run_id="run-9"))
    assert record.binding is not None
    assert record.binding.receipt_id == "receipt-1"
    assert record.binding.run_id == "run-9"
    assert record.envelope.receipt_id == "receipt-1"

    with pytest.raises(ValueError, match="receipt_id"):
        _record(binding=_binding(receipt_id="other-receipt"))


def test_bound_unacknowledged_record_is_admitted() -> None:
    bound = _record(binding=_binding())
    assert bound.admitted is True
    assert bound.acknowledged_at_us is None
    assert bound.format_version == 2

    unbound = _record()
    assert unbound.admitted is False

    # A v2 binding is replayable without an acknowledgement.
    replay = Replayed(record=bound)
    assert replay.record.admitted is True


def test_acknowledgement_requires_binding_and_does_not_change_deadline() -> None:
    with pytest.raises(ValueError, match="binding"):
        _record(acknowledged_at_us=_CREATED_US + 5)

    with pytest.raises(ValueError, match="creation"):
        _record(binding=_binding(), acknowledged_at_us=_CREATED_US - 1)

    acknowledged = _record(binding=_binding(), acknowledged_at_us=_CREATED_US + 10)
    assert acknowledged.acknowledged_at_us == _CREATED_US + 10
    # Acknowledgement neither changes nor extends the recorded deadlines.
    assert acknowledged.envelope.expires_at_us == _EXPIRES_US
    assert acknowledged.lease_expires_at_us == _LEASE_US


# --- legacy records -----------------------------------------------------------


def test_legacy_pending_record_has_no_invented_identity() -> None:
    legacy = _legacy()
    assert legacy.format_version == 1
    assert legacy.admitted is False
    assert not hasattr(legacy, "generation_id")
    assert not hasattr(legacy, "owner_token")
    assert not hasattr(legacy, "envelope")
    assert not hasattr(legacy, "receipt_id")

    unresolved = LegacyUnresolved(record=legacy)
    assert unresolved.record.binding is None

    # Old rows did not clamp the pending lease to the replay window.
    unclamped = _legacy(lease_expires_at_us=_EXPIRES_US + 12345)
    assert unclamped.lease_expires_at_us > unclamped.expires_at_us

    # A legacy row with a binding replays; its binding keeps both identities.
    bound_legacy = _legacy(binding=_binding(receipt_id="old-task-id", run_id="old-run-id"))
    assert bound_legacy.admitted is True
    assert bound_legacy.binding is not None
    assert bound_legacy.binding.receipt_id == "old-task-id"
    assert Replayed(record=bound_legacy).record.format_version == 1


# --- validation rejections ----------------------------------------------------


@pytest.mark.parametrize(
    "builder",
    [
        pytest.param(
            lambda: AdmissionTicket(
                scope_key="AA" * 32, generation_id=_GENERATION, owner_token=_OWNER
            ),
            id="scope-uppercase",
        ),
        pytest.param(
            lambda: AdmissionTicket(
                scope_key="aa" * 31 + "zz", generation_id=_GENERATION, owner_token=_OWNER
            ),
            id="scope-not-hex",
        ),
        pytest.param(
            lambda: AdmissionTicket(
                scope_key="aa" * 31, generation_id=_GENERATION, owner_token=_OWNER
            ),
            id="scope-too-short",
        ),
        pytest.param(
            lambda: AdmissionTicket(scope_key=1, generation_id=_GENERATION, owner_token=_OWNER),
            id="scope-not-str",
        ),
        pytest.param(
            lambda: AdmissionTicket(
                scope_key=_SCOPE, generation_id="not-a-uuid", owner_token=_OWNER
            ),
            id="generation-string",
        ),
        pytest.param(
            lambda: AdmissionTicket(
                scope_key=_SCOPE, generation_id=uuid.UUID(int=0), owner_token=_OWNER
            ),
            id="generation-nil",
        ),
        pytest.param(
            lambda: AdmissionTicket(
                scope_key=_SCOPE, generation_id=_GENERATION, owner_token=uuid.UUID(int=0)
            ),
            id="owner-nil",
        ),
        pytest.param(lambda: _envelope(fingerprint="CC" * 32), id="fingerprint-uppercase"),
        pytest.param(lambda: _envelope(workspace_id=" w1"), id="workspace-padded"),
        pytest.param(lambda: _envelope(project_id=""), id="project-empty"),
        pytest.param(lambda: _envelope(origin_principal_id="origin\n"), id="origin-newline"),
        pytest.param(lambda: _envelope(actor_principal_id="  "), id="actor-whitespace"),
        pytest.param(lambda: _envelope(action=""), id="action-empty"),
        pytest.param(lambda: _envelope(receipt_id=None), id="receipt-none"),
        pytest.param(
            lambda: _envelope(created_at_us=True, expires_at_us=_EXPIRES_US), id="created-bool"
        ),
        pytest.param(
            lambda: _envelope(created_at_us=1.0, expires_at_us=_EXPIRES_US), id="created-float"
        ),
        pytest.param(lambda: _envelope(expires_at_us=_CREATED_US), id="expires-equals-created"),
        pytest.param(lambda: _envelope(expires_at_us=_CREATED_US - 1), id="expires-before-created"),
        pytest.param(lambda: _envelope(created_at_us=2**63), id="created-out-of-int64"),
        pytest.param(lambda: _envelope(request_snapshot={"a": 1}), id="request-snapshot-dict"),
        pytest.param(lambda: _envelope(receipt_snapshot="{}"), id="receipt-snapshot-str"),
        pytest.param(lambda: _envelope(provenance_snapshot=None), id="provenance-snapshot-none"),
        pytest.param(
            lambda: _record(lease_expires_at_us=_CREATED_US - 1), id="lease-before-created"
        ),
        pytest.param(lambda: _record(lease_expires_at_us=_EXPIRES_US + 1), id="lease-after-expiry"),
        pytest.param(lambda: _record(lease_expires_at_us=False), id="lease-bool"),
        pytest.param(lambda: _record(envelope="envelope"), id="record-envelope-str"),
        pytest.param(
            lambda: _record(owner_token="22222222-2222-3222-9222-222222222222"),
            id="record-owner-string",
        ),
        pytest.param(lambda: _record(binding="binding"), id="record-binding-str"),
        pytest.param(lambda: _legacy(fingerprint="short"), id="legacy-fingerprint-short"),
        pytest.param(lambda: _legacy(request_snapshot={}), id="legacy-snapshot-dict"),
        pytest.param(
            lambda: _legacy(expires_at_us=_CREATED_US), id="legacy-expiry-not-after-creation"
        ),
        pytest.param(lambda: _legacy(binding="binding"), id="legacy-binding-str"),
        pytest.param(
            lambda: Claimed(ticket=_ticket(), record=_record(binding=_binding())),
            id="claimed-with-bound-record",
        ),
        pytest.param(
            lambda: Claimed(ticket=_ticket(scope_key=_OTHER_SCOPE), record=_record()),
            id="claimed-with-foreign-scope",
        ),
        pytest.param(
            lambda: Claimed(ticket=_ticket(owner_token=_GENERATION), record=_record()),
            id="claimed-with-wrong-owner",
        ),
        pytest.param(lambda: Claimed(ticket=_record(), record=_record()), id="claimed-non-ticket"),
        pytest.param(lambda: Replayed(record=_record()), id="replayed-unbound-v2"),
        pytest.param(lambda: Replayed(record=_legacy()), id="replayed-unbound-legacy"),
        pytest.param(lambda: Replayed(record="record"), id="replayed-non-record"),
        pytest.param(
            lambda: Pending(record=_record(binding=_binding())), id="pending-bound-record"
        ),
        pytest.param(lambda: Pending(record=_legacy()), id="pending-legacy-record"),
        pytest.param(
            lambda: LegacyUnresolved(record=_legacy(binding=_binding())),
            id="legacy-unresolved-bound",
        ),
        pytest.param(lambda: LegacyUnresolved(record=_record()), id="legacy-unresolved-v2"),
        pytest.param(lambda: AlreadyBound(binding="binding"), id="already-bound-str"),
    ],
)
def test_invalid_ids_timestamps_and_variant_combinations_are_rejected(
    builder: object,
) -> None:
    assert callable(builder)
    with pytest.raises(ValueError):
        builder()


# --- admission result ---------------------------------------------------------


def test_result_snapshot_must_match_run_id_and_created_is_boolean() -> None:
    result = RootAdmissionResult(
        run_id="run-1", receipt_id="receipt-1", run_snapshot=_run_snapshot("run-1"), created=True
    )
    assert result.created is True
    assert result.run_snapshot.text == json.dumps(
        json.loads(result.run_snapshot.text), sort_keys=True, separators=(",", ":")
    )

    with pytest.raises(ValueError, match="run_id"):
        RootAdmissionResult(
            run_id="run-2",
            receipt_id="receipt-1",
            run_snapshot=_run_snapshot("run-1"),
            created=True,
        )

    with pytest.raises(ValueError, match="run_id"):
        RootAdmissionResult(
            run_id="run-1",
            receipt_id="receipt-1",
            run_snapshot=CanonicalJsonObject(text='{"other": 1}'),
            created=True,
        )

    for not_a_bool in (0, 1, "true", None):
        with pytest.raises(ValueError, match="bool"):
            RootAdmissionResult(
                run_id="run-1",
                receipt_id="receipt-1",
                run_snapshot=_run_snapshot(),
                created=not_a_bool,  # type: ignore[arg-type]
            )


# --- repr hygiene ----------------------------------------------------------------


def test_owner_token_field_is_absent_from_generated_representations() -> None:
    single = uuid.UUID("55555555-5555-6555-8555-555555555555")
    for record in (
        _record(),
        _record(owner_token=single),
        _record(envelope=_envelope(generation_id=single), owner_token=single),
    ):
        assert "owner_token=" not in repr(record)

    assert "owner_token=" not in repr(_ticket())

    # Field omission, not blanket absence of the UUID text: when the two roles
    # coincide, the independently printable generation id still shows the value.
    coincide = _record(envelope=_envelope(generation_id=single), owner_token=single)
    assert str(single) in repr(coincide.envelope)
    assert "owner_token=" not in repr(coincide)

    assert StaleOwner()  # empty variants keep default truthiness (always true)
    assert not hasattr(StaleOwner, "__bool__")
    assert not hasattr(Acknowledged, "__bool__")
