"""Tests for maistro.observability.tiers — SensitivityTier and PIIDetector."""

from __future__ import annotations

from typing import Any

import pytest

from maistro.observability.tiers import (
    PIIDetector,
    SensitivityTier,
    UnexpectedPIIError,
    pii_unexpected_match_total,
)

EMAIL_PAYLOAD = {"request": {"prompt": "mail me at alice@example.com please"}, "response": {}}
AWS_PAYLOAD = {"request": {"note": "key is AKIAIOSFODNN7EXAMPLE"}, "response": {}}
CLEAN_PAYLOAD = {"request": {"prompt": "summarize the weekly report"}, "response": {"ok": True}}


class TestSensitivityTier:
    def test_values(self) -> None:
        assert SensitivityTier.NORMAL == "normal"
        assert SensitivityTier.SENSITIVE == "sensitive"
        assert SensitivityTier.SECRET == "secret"


class TestPIIDetector:
    def test_clean_payload_passes_through_unchanged(self) -> None:
        detector = PIIDetector(mode="dev")
        assert detector.inspect(CLEAN_PAYLOAD) is CLEAN_PAYLOAD

    @pytest.mark.ac("SPEC-070226-2b70/AC-7")
    def test_dev_mode_raises_on_email(self) -> None:
        detector = PIIDetector(mode="dev")
        with pytest.raises(UnexpectedPIIError) as exc_info:
            detector.inspect(EMAIL_PAYLOAD)
        assert "email" in exc_info.value.pii_types

    @pytest.mark.ac("SPEC-070226-2b70/AC-7")
    def test_dev_mode_raises_on_secret_shaped_token(self) -> None:
        detector = PIIDetector(mode="dev")
        with pytest.raises(UnexpectedPIIError) as exc_info:
            detector.inspect(AWS_PAYLOAD)
        assert "aws_key" in exc_info.value.pii_types

    @pytest.mark.ac("SPEC-070226-2b70/AC-7")
    def test_prod_mode_redacts_and_emits(self) -> None:
        emitted: list[tuple[str, dict[str, Any]]] = []
        detector = PIIDetector(mode="prod", emit=lambda name, attrs: emitted.append((name, attrs)))
        before = sum(v["value"] for v in pii_unexpected_match_total.collect()) or 0.0

        result = detector.inspect(EMAIL_PAYLOAD)

        assert "alice@example.com" not in str(result)
        assert "[REDACTED:email]" in result["request"]["prompt"]
        assert emitted == [("pii.unexpected_match", {"pii_types": ["email"]})]
        after = sum(v["value"] for v in pii_unexpected_match_total.collect())
        assert after == before + 1

    @pytest.mark.ac("SPEC-070226-2b70/AC-7")
    def test_prod_mode_does_not_mutate_original(self) -> None:
        detector = PIIDetector(mode="prod")
        detector.inspect(EMAIL_PAYLOAD)
        assert "alice@example.com" in EMAIL_PAYLOAD["request"]["prompt"]

    def test_register_pattern_extension_hook(self) -> None:
        detector = PIIDetector(mode="prod")
        detector.register_pattern("employee_id", r"EMP-\d{6}")
        payload = {"request": {"who": "EMP-123456"}, "response": {}}
        result = detector.inspect(payload)
        assert result["request"]["who"] == "[REDACTED:employee_id]"

    def test_register_pattern_dev_mode_raises(self) -> None:
        detector = PIIDetector(mode="dev")
        detector.register_pattern("employee_id", r"EMP-\d{6}")
        with pytest.raises(UnexpectedPIIError) as exc_info:
            detector.inspect({"x": "EMP-654321"})
        assert "employee_id" in exc_info.value.pii_types

    @pytest.mark.ac("SPEC-070226-2b70/AC-7")
    def test_scans_nested_lists_and_keys(self) -> None:
        detector = PIIDetector(mode="dev")
        with pytest.raises(UnexpectedPIIError):
            detector.inspect({"items": [{"deep": ["bob@example.org"]}]})

    def test_invalid_mode_rejected(self) -> None:
        with pytest.raises(ValueError):
            PIIDetector(mode="staging")
