"""I18: Flag Response — Flagged Response Builder — Hypothesis property-based tests."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, rule, invariant

from maistro.security.warden.flag_response import build_audit_payload, build_flagged_response


class FlagResponseMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.built_count = 0

    @rule(
        content=st.text(min_size=0, max_size=500),
        flags=st.lists(st.text(min_size=1, max_size=30), min_size=0, max_size=5),
        layer=st.sampled_from(["regex", "heuristic", "semantic", "llm"]),
    )
    def build_response(self, content, flags, layer):
        result = build_flagged_response(content, flags=flags, detection_layer=layer)
        assert content in result
        self.built_count += 1

    @invariant()
    def built_count_non_negative(self):
        assert self.built_count >= 0


TestFlagResponseMachine = FlagResponseMachine.TestCase


def test_output_contains_original_content():
    result = build_flagged_response("hello world", flags=["test_flag"], detection_layer="regex")
    assert "hello world" in result


def test_output_contains_warning_banner():
    result = build_flagged_response("content", flags=["flag"], detection_layer="regex")
    assert "WARNING SECURITY NOTICE" in result


def test_output_contains_reason():
    result = build_flagged_response("content", flags=["my_reason"], detection_layer="regex")
    assert "my_reason" in result


def test_output_contains_detection_layer():
    result = build_flagged_response("content", flags=["flag"], detection_layer="heuristic")
    assert "heuristic" in result


def test_audit_payload_event_type():
    payload = build_audit_payload(
        tool_name="test_tool",
        flags=["flag1"],
        detection_layer="regex",
        user_id="user1",
    )
    assert payload["event"] == "tool_result_flagged"


def test_content_preview_truncated():
    long_content = "x" * 500
    payload = build_audit_payload(
        tool_name="tool",
        flags=["f"],
        detection_layer="regex",
        user_id="u",
        content_preview=long_content,
    )
    assert len(payload["content_preview"]) <= 200


def test_empty_flags_default_reason():
    result = build_flagged_response("content", flags=[], detection_layer="regex")
    assert "suspicious content detected" in result


@given(
    content=st.text(min_size=0, max_size=200),
    flags=st.lists(st.text(min_size=1, max_size=30), min_size=1, max_size=5),
    layer=st.sampled_from(["regex", "heuristic", "semantic", "llm"]),
)
@settings(max_examples=50)
def test_output_always_contains_content(content, flags, layer):
    result = build_flagged_response(content, flags=flags, detection_layer=layer)
    assert content in result


@given(
    flags=st.lists(st.text(min_size=1, max_size=30), min_size=1, max_size=5),
)
@settings(max_examples=30)
def test_all_flags_in_output(flags):
    result = build_flagged_response("body", flags=flags, detection_layer="regex")
    for f in flags:
        assert f in result


@given(
    content_preview=st.text(min_size=0, max_size=500),
)
@settings(max_examples=30)
def test_audit_preview_truncated(content_preview):
    payload = build_audit_payload(
        tool_name="t",
        flags=["f"],
        detection_layer="regex",
        user_id="u",
        content_preview=content_preview,
    )
    assert len(payload["content_preview"]) <= 200


@given(
    tool_name=st.text(min_size=1, max_size=20),
    user_id=st.text(min_size=1, max_size=20),
)
@settings(max_examples=30)
def test_audit_payload_has_required_fields(tool_name, user_id):
    payload = build_audit_payload(
        tool_name=tool_name,
        flags=["flag"],
        detection_layer="regex",
        user_id=user_id,
    )
    assert "event" in payload
    assert "severity" in payload
    assert "tool_name" in payload
    assert "flags" in payload
    assert "detection_layer" in payload
    assert "user_id" in payload
    assert payload["tool_name"] == tool_name
    assert payload["user_id"] == user_id


def test_audit_payload_requires_review():
    payload = build_audit_payload(
        tool_name="t",
        flags=["f"],
        detection_layer="regex",
        user_id="u",
    )
    assert payload["requires_review"] is True


def test_audit_payload_action():
    payload = build_audit_payload(
        tool_name="t",
        flags=["f"],
        detection_layer="regex",
        user_id="u",
    )
    assert payload["action"] == "flagged_and_warned"
