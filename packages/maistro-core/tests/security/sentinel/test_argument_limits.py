"""Resource-boundary coverage for Sentinel tool-call arguments."""

from __future__ import annotations

import base64
from typing import Any

import pytest

from maistro.constants import TOOL_ARGUMENT_MAX_BYTES, TOOL_ARGUMENT_MAX_DEPTH
from maistro.security._types import AuditEntry, AuthContext, WardenVerdict
from maistro.security.sentinel.argument_limits import ToolArgumentLimits, check_argument_limits
from maistro.security.sentinel.policy import Sentinel


class _StubWarden:
    async def scan(self, text: str, boundary: str) -> WardenVerdict:
        return WardenVerdict(clean=True)


class _AuditLog:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    async def log(self, entry: AuditEntry) -> None:
        self.entries.append(entry)


def _auth() -> AuthContext:
    return AuthContext(user_id="u1", roles=frozenset({"user"}))


def _nested(depth: int) -> dict[str, Any]:
    value: dict[str, Any] = {"leaf": "ok"}
    for _ in range(depth - 1):
        value = {"child": value}
    return value


def test_ordinary_arguments_are_within_default_limits() -> None:
    assert (
        check_argument_limits(
            {"query": "hello", "page": 2, "filters": ["a", "b"]},
            limits=ToolArgumentLimits(),
        )
        is None
    )


@pytest.mark.ac("SPEC-082126-7a31/AC-3")
def test_nested_objects_over_depth_limit_are_rejected_before_serialization(
    monkeypatch: Any,
) -> None:
    import maistro.security.sentinel.argument_limits as limits_module

    def _must_not_serialize(*args: Any, **kwargs: Any) -> str:
        raise AssertionError("depth gate must run before JSON serialization")

    monkeypatch.setattr(limits_module.json, "dumps", _must_not_serialize)
    violation = check_argument_limits(
        _nested(6),
        limits=ToolArgumentLimits(max_bytes=10_000, max_depth=4),
    )
    assert violation is not None
    assert violation.rule == "tool_argument_depth_limit"
    assert "configured maximum 4" in violation.detail


def test_nested_arrays_count_toward_structural_depth() -> None:
    args: dict[str, Any] = {"items": [[[[["x"]]]]]}
    violation = check_argument_limits(
        args,
        limits=ToolArgumentLimits(max_bytes=10_000, max_depth=4),
    )
    assert violation is not None
    assert violation.rule == "tool_argument_depth_limit"


def test_huge_string_is_rejected_by_utf8_json_byte_limit() -> None:
    violation = check_argument_limits(
        {"payload": "x" * 200},
        limits=ToolArgumentLimits(max_bytes=100, max_depth=8),
    )
    assert violation is not None
    assert violation.rule == "tool_argument_size_limit"
    assert "100" in violation.detail


@pytest.mark.ac("SPEC-082126-7a31/AC-4")
def test_encoded_payload_does_not_bypass_byte_limit() -> None:
    encoded = base64.b64encode(b"A" * 256).decode("ascii")
    violation = check_argument_limits(
        {"payload": encoded},
        limits=ToolArgumentLimits(max_bytes=200, max_depth=8),
    )
    assert violation is not None
    assert violation.rule == "tool_argument_size_limit"


def test_utf8_bytes_not_python_character_count_are_limited() -> None:
    violation = check_argument_limits(
        {"payload": "🙂" * 30},
        limits=ToolArgumentLimits(max_bytes=100, max_depth=8),
    )
    assert violation is not None
    assert violation.rule == "tool_argument_size_limit"


@pytest.mark.ac("SPEC-082126-7a31/AC-6")
def test_non_json_arguments_fail_closed() -> None:
    violation = check_argument_limits(
        {"bad": {1, 2, 3}},
        limits=ToolArgumentLimits(max_bytes=10_000, max_depth=8),
    )
    assert violation is not None
    assert violation.rule == "tool_argument_not_json"


@pytest.mark.ac("SPEC-082126-7a31/AC-5")
def test_environment_overrides_may_tighten_without_unsafe_policy(monkeypatch: Any) -> None:
    monkeypatch.delenv("ALLOW_UNSAFE_RESOURCE_OVERRIDES", raising=False)
    monkeypatch.setenv("MAISTRO_TOOL_ARGUMENT_MAX_BYTES", "2048")
    monkeypatch.setenv("MAISTRO_TOOL_ARGUMENT_MAX_DEPTH", "12")
    limits = ToolArgumentLimits.from_environment()
    assert limits == ToolArgumentLimits(max_bytes=2048, max_depth=12)


@pytest.mark.ac("SPEC-082126-7a31/AC-5")
@pytest.mark.parametrize(
    ("name", "value", "baseline"),
    [
        ("MAISTRO_TOOL_ARGUMENT_MAX_BYTES", str(TOOL_ARGUMENT_MAX_BYTES + 1), TOOL_ARGUMENT_MAX_BYTES),
        ("MAISTRO_TOOL_ARGUMENT_MAX_DEPTH", str(TOOL_ARGUMENT_MAX_DEPTH + 1), TOOL_ARGUMENT_MAX_DEPTH),
    ],
)
def test_weaker_environment_limit_requires_explicit_unsafe_policy(
    monkeypatch: Any,
    name: str,
    value: str,
    baseline: int,
) -> None:
    monkeypatch.delenv("ALLOW_UNSAFE_RESOURCE_OVERRIDES", raising=False)
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=f"declared security baseline of {baseline}"):
        ToolArgumentLimits.from_environment()


@pytest.mark.ac("SPEC-082126-7a31/AC-5")
def test_explicit_unsafe_policy_allows_weaker_environment_limits(monkeypatch: Any) -> None:
    monkeypatch.setenv("ALLOW_UNSAFE_RESOURCE_OVERRIDES", "true")
    monkeypatch.setenv("MAISTRO_TOOL_ARGUMENT_MAX_BYTES", str(TOOL_ARGUMENT_MAX_BYTES * 2))
    monkeypatch.setenv("MAISTRO_TOOL_ARGUMENT_MAX_DEPTH", str(TOOL_ARGUMENT_MAX_DEPTH * 2))
    limits = ToolArgumentLimits.from_environment()
    assert limits == ToolArgumentLimits(
        max_bytes=TOOL_ARGUMENT_MAX_BYTES * 2,
        max_depth=TOOL_ARGUMENT_MAX_DEPTH * 2,
    )


def test_invalid_environment_policy_fails_loudly(monkeypatch: Any) -> None:
    monkeypatch.setenv("MAISTRO_TOOL_ARGUMENT_MAX_BYTES", "not-a-number")
    with pytest.raises(ValueError, match="MAISTRO_TOOL_ARGUMENT_MAX_BYTES"):
        ToolArgumentLimits.from_environment()


def test_invalid_unsafe_override_flag_fails_loudly(monkeypatch: Any) -> None:
    monkeypatch.setenv("ALLOW_UNSAFE_RESOURCE_OVERRIDES", "sometimes")
    with pytest.raises(ValueError, match="ALLOW_UNSAFE_RESOURCE_OVERRIDES"):
        ToolArgumentLimits.from_environment()


@pytest.mark.ac("SPEC-082126-7a31/AC-2")
async def test_sentinel_denies_and_audits_oversized_arguments() -> None:
    audit = _AuditLog()
    sentinel = Sentinel(
        warden=_StubWarden(),
        permission_table={},
        audit_log=audit,
        argument_limits=ToolArgumentLimits(max_bytes=80, max_depth=8),
    )
    verdict = await sentinel.pre_call(
        "tool",
        {"payload": "x" * 100},
        _auth(),
        schema={},
    )
    assert verdict.allowed is False
    assert verdict.violations[0].rule == "tool_argument_size_limit"
    assert audit.entries[0].verdict == "denied"
    assert "configured maximum 80" in audit.entries[0].detail


@pytest.mark.ac("SPEC-082126-7a31/AC-1")
async def test_sentinel_preserves_normal_valid_tool_call_behavior() -> None:
    audit = _AuditLog()
    sentinel = Sentinel(
        warden=_StubWarden(),
        permission_table={},
        audit_log=audit,
        argument_limits=ToolArgumentLimits(max_bytes=1024, max_depth=8),
    )
    verdict = await sentinel.pre_call(
        "tool",
        {"query": "normal"},
        _auth(),
        schema={},
    )
    assert verdict.allowed is True
    assert audit.entries[0].verdict == "allowed"
