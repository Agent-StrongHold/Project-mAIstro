"""Violation.detail is redacted AT CONSTRUCTION (#1159).

Two Violation classes ride security evidence:

- ``maistro.security._types.Violation`` — the Sentinel pipeline's violation;
  its ``detail`` interpolates rejected tool-call material (the invalid-enum
  message carries the rejected value verbatim), and ``SentinelVerdict`` /
  ``AuditEntry`` carry the tuple toward any AuditLog implementation.
- ``maistro.types.security.Violation`` — frozen, rides the persisted
  ``AuditEntry`` in ``persistence/``.

The shipped audit stores happen not to serialize the violations tuple, but
the #1159 stop condition forbids resting the invariant on that omission: the
redaction must happen before any store can persist, i.e. in ``__post_init__``,
so a future store that starts persisting violations inherits redacted text
for free. These tests pin construction-time redaction for both classes — the
persistence boundary can never see the raw value.
"""

from __future__ import annotations

from maistro.security._types import AuditEntry as SentinelAuditEntry
from maistro.security._types import Violation as SentinelViolation
from maistro.types.security import AuditEntry as TypedAuditEntry
from maistro.types.security import Violation as TypedViolation


class TestSentinelViolationDetailRedaction:
    def test_api_key_shaped_detail_is_redacted_at_construction(self) -> None:
        key = "sk-" + "FAKEVALUE1234567890"
        violation = SentinelViolation(
            boundary="tool",
            rule="arg_enum",
            severity="error",
            detail=f"invalid enum value '{key}' for argument 'api_key'",
        )
        assert "[REDACTED_API_KEY]" in violation.detail
        assert key not in violation.detail
        # The fact and type of the violation survive.
        assert "invalid enum value" in violation.detail
        assert violation.rule == "arg_enum"

    def test_secret_assignment_detail_is_redacted_at_construction(self) -> None:
        violation = SentinelViolation(
            boundary="tool",
            rule="schema",
            severity="error",
            detail="my_secret = 'hunter2pass' failed validation",
        )
        assert "hunter2pass" not in violation.detail
        assert "[REDACTED_SECRET_ASSIGNMENT]" in violation.detail
        assert "my_secret" in violation.detail

    def test_redaction_happens_before_any_persistence(self) -> None:
        """The AuditEntry a store receives already carries redacted detail."""
        key = "xoxb-FAKEVALUE123456"
        entry = SentinelAuditEntry(
            boundary="tool",
            user_id="u1",
            tool_name="slack_post",
            verdict="denied",
            violations=(
                SentinelViolation(
                    boundary="tool",
                    rule="dangerous",
                    severity="error",
                    detail=f"token {key} rejected",
                ),
            ),
        )
        assert entry.violations[0].detail == "token [REDACTED_API_KEY] rejected"

    def test_ordinary_detail_passes_through_undestroyed(self) -> None:
        detail = "argument 'count' must be an integer between 1 and 10"
        violation = SentinelViolation(
            boundary="tool", rule="schema", severity="error", detail=detail
        )
        assert violation.detail == detail


class TestTypedViolationDetailRedaction:
    def test_frozen_violation_redacts_detail_at_construction(self) -> None:
        key = "sk-" + "FAKEVALUE9876543210"
        violation = TypedViolation(
            boundary="tool",
            rule="arg_enum",
            detail=f"rejected value '{key}'",
        )
        assert key not in violation.detail
        assert "[REDACTED_API_KEY]" in violation.detail

    def test_frozen_instance_is_not_mutated_by_post_init(self) -> None:
        violation = TypedViolation(
            boundary="tool",
            rule="r",
            detail="my_secret = 'hunter2pass' leaked",
        )
        assert "[REDACTED_SECRET_ASSIGNMENT]" in violation.detail
        # The frozen contract still holds: no attribute write succeeds.
        try:
            violation.detail = "rewritten"  # type: ignore[misc]  deliberate: pins frozenness
            raised = False
        except AttributeError:
            raised = True
        assert raised, "frozen Violation must reject attribute writes"

    def test_audit_entry_rides_redacted_violations(self) -> None:
        key = "wJalr" + "XUtnFEMI/K7MDENG/bPxRfiCY" + "EXAMPLEKEY"
        violation = TypedViolation(
            boundary="tool", rule="exfil", detail=f"aws secret {key} in args"
        )
        entry = TypedAuditEntry(boundary="tool", verdict="denied", violations=(violation,))
        assert "[REDACTED_AWS_SECRET_KEY]" in entry.violations[0].detail
        assert key not in entry.violations[0].detail
        # And the redaction is idempotent down a serialize/redact round trip.
        assert (
            TypedViolation(boundary="tool", rule="exfil", detail=entry.violations[0].detail).detail
            == entry.violations[0].detail
        )

    def test_default_detail_is_empty_and_untouched(self) -> None:
        assert TypedViolation(boundary="tool", rule="r").detail == ""
