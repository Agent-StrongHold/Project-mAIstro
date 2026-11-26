"""What `DurableApproval` refuses to be (#1196).

The store's tests build valid approvals and exercise the store. Nothing built
an *invalid* one, so every refusal in the model -- the checks that decide
whether a persisted human decision can be trusted at all -- was unexercised.
A validator nothing tests is a validator that can be deleted without a test
failing, which is the same as not having it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from maistro.capabilities.approval_store import (
    _IDENTITY_FIELDS,
    ApprovalStatus,
    DurableApproval,
    approval_request_digest,
)
from maistro.capabilities.slots.approval import ApprovalRequest

_RESOLVED_AT = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def _request(**params: object) -> ApprovalRequest:
    return ApprovalRequest(
        action="invoke:external_write",
        params=params or {"request": {"value": 1}},
        tier="policy",
        requester="node-run-1",
    )


def _fields(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "request": _request(),
        "workspace_id": "ws-1",
        "project_id": "project-1",
        "run_id": "run-1",
        "node_run_id": "node-run-1",
        "attempt_id": "attempt-1",
        "binding_id": "binding-1",
        "effect_key": "write:1",
    }
    return {**base, **overrides}


@pytest.mark.parametrize("field", _IDENTITY_FIELDS)
@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_correlation_field_is_refused(field: str, blank: str) -> None:
    """Every field an approval is *found by* must narrow the lookup.

    A blank one does not, so the row would answer for a different effect than
    the one it authorizes — an approval granted for one call reused by another.
    Whitespace counts as blank for the same reason.
    """
    with pytest.raises(ValidationError, match=f"{field} must be a non-empty string"):
        DurableApproval(**_fields(**{field: blank}))


def test_a_carried_digest_is_kept_rather_than_recomputed() -> None:
    """The params may carry the digest the requester computed; trust it."""
    carried = "sha256:deadbeef"
    approval = DurableApproval(
        **_fields(request=_request(request_digest=carried, request={"value": 1}))
    )

    assert approval.request_digest == carried


def test_an_absent_digest_is_derived_from_the_legacy_payload() -> None:
    """Older requests nest the payload under `request`; digest that, not the envelope."""
    approval = DurableApproval(**_fields(request=_request(request={"value": 1})))

    assert approval.request_digest == approval_request_digest({"value": 1})


def test_an_absent_digest_falls_back_to_the_whole_params() -> None:
    """With no `request` key the params *are* the payload."""
    payload = {"value": 7, "other": "x"}
    approval = DurableApproval(**_fields(request=_request(**payload)))

    assert approval.request_digest == approval_request_digest(payload)


def test_an_explicit_digest_overrides_derivation() -> None:
    approval = DurableApproval(**_fields(request_digest="sha256:explicit"))

    assert approval.request_digest == "sha256:explicit"


@pytest.mark.parametrize("status", [ApprovalStatus.APPROVED, ApprovalStatus.DENIED])
def test_a_resolved_approval_must_name_its_actor(status: ApprovalStatus) -> None:
    """Both terminal states, not just the approving one: a denial nobody signed
    is as unauditable as an approval nobody signed."""
    with pytest.raises(ValidationError, match="requires a non-empty actor"):
        DurableApproval(**_fields(status=status, resolved_at=_RESOLVED_AT))


@pytest.mark.parametrize("status", [ApprovalStatus.APPROVED, ApprovalStatus.DENIED])
def test_a_resolved_approval_must_say_when(status: ApprovalStatus) -> None:
    with pytest.raises(ValidationError, match="requires resolved_at"):
        DurableApproval(**_fields(status=status, actor="person-1"))


def test_a_pending_approval_cannot_claim_a_resolution_time() -> None:
    """The other half of the same invariant. Half a resolution is a row that
    reads as decided to one query and undecided to another."""
    with pytest.raises(ValidationError, match="pending approval cannot have resolved_at"):
        DurableApproval(**_fields(resolved_at=_RESOLVED_AT))


def test_a_well_formed_pending_and_resolved_approval_are_both_accepted() -> None:
    """The validators refuse halves, not wholes."""
    pending = DurableApproval(**_fields())
    assert pending.status is ApprovalStatus.PENDING
    assert pending.resolved_at is None
    assert pending.actor == ""

    resolved = DurableApproval(
        **_fields(status=ApprovalStatus.APPROVED, actor="person-1", resolved_at=_RESOLVED_AT)
    )
    assert resolved.status is ApprovalStatus.APPROVED
    assert resolved.effect_identity == ("run-1", "node-run-1", "binding-1", "write:1")
