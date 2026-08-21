"""Coverage for security/warden/flag_response.py."""

from __future__ import annotations

from maistro.security.warden.flag_response import build_audit_payload, build_flagged_response


def test_build_flagged_response_joins_flags_with_semicolons() -> None:
    result = build_flagged_response(
        "original content",
        flags=["flag_a", "flag_b"],
        detection_layer="Layer 2 (Heuristic)",
        flag_id="flag-1",
    )
    assert result.startswith("original content")
    assert "Reason: flag_a; flag_b" in result
    assert "Detection: Layer 2 (Heuristic)" in result
    assert "security@maistro.local" in result
    assert "flag-1" in result


def test_build_flagged_response_defaults_reason_when_no_flags() -> None:
    result = build_flagged_response("content", flags=[], detection_layer="Layer 1 (Pattern)")
    assert "Reason: suspicious content detected" in result


def test_build_flagged_response_uses_custom_escalation_url_when_provided() -> None:
    result = build_flagged_response(
        "content",
        flags=["x"],
        detection_layer="Layer 1 (Pattern)",
        escalation_url="https://custom.example/escalate",
    )
    assert "https://custom.example/escalate" in result
    assert "mailto:" not in result


def test_build_flagged_response_default_escalation_url_uses_custom_admin_email() -> None:
    result = build_flagged_response(
        "content",
        flags=["x"],
        detection_layer="Layer 1 (Pattern)",
        admin_email="admin@custom.org",
    )
    assert "mailto:admin%40custom.org" in result or "admin@custom.org" in result


def test_build_flagged_response_default_escalation_url_uses_unknown_flag_id_when_missing() -> None:
    result = build_flagged_response("content", flags=["x"], detection_layer="Layer 1 (Pattern)")
    assert "Flag%20ID%3A%20unknown" in result


def test_build_flagged_response_url_encodes_reason_spaces() -> None:
    result = build_flagged_response(
        "content", flags=["flag one", "flag two"], detection_layer="Layer 1 (Pattern)"
    )
    assert "flag%20one;%20flag%20two" in result


def test_build_audit_payload_returns_exact_structure() -> None:
    payload = build_audit_payload(
        tool_name="search",
        flags=["flag_a"],
        detection_layer="Layer 3 (LLM)",
        user_id="u1",
        content_preview="some preview text",
        llm_classification={"label": "suspicious"},
    )
    assert payload == {
        "event": "tool_result_flagged",
        "severity": "warning",
        "tool_name": "search",
        "flags": ["flag_a"],
        "detection_layer": "Layer 3 (LLM)",
        "user_id": "u1",
        "content_preview": "some preview text",
        "llm_classification": {"label": "suspicious"},
        "action": "flagged_and_warned",
        "requires_review": True,
    }


def test_build_audit_payload_truncates_content_preview_to_200_chars() -> None:
    long_preview = "y" * 500
    payload = build_audit_payload(
        tool_name="t",
        flags=[],
        detection_layer="Layer 1 (Pattern)",
        user_id="u1",
        content_preview=long_preview,
    )
    assert payload["content_preview"] == long_preview[:200]
    assert len(payload["content_preview"]) == 200


def test_build_audit_payload_defaults_llm_classification_to_none() -> None:
    payload = build_audit_payload(
        tool_name="t", flags=[], detection_layer="Layer 1 (Pattern)", user_id="u1"
    )
    assert payload["llm_classification"] is None
    assert payload["content_preview"] == ""
