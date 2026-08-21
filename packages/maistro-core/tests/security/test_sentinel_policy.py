"""Coverage for maistro.security.sentinel.policy (Sentinel pre_call/post_call pipeline)."""

from __future__ import annotations

from maistro.security._types import (
    AuditEntry,
    AuthContext,
    WardenVerdict,
)
from maistro.security.sentinel.policy import Sentinel, _detection_layer, check_permission


class _StubWarden:
    def __init__(self, verdict: WardenVerdict | None = None):
        self.verdict = verdict or WardenVerdict(clean=True)
        self.calls: list[tuple[str, str]] = []

    async def scan(self, text: str, boundary: str) -> WardenVerdict:
        self.calls.append((text, boundary))
        return self.verdict


class _StubAuditLog:
    def __init__(self, raise_on_log: bool = False):
        self.entries: list[AuditEntry] = []
        self.raise_on_log = raise_on_log

    async def log(self, entry: AuditEntry) -> None:
        if self.raise_on_log:
            raise RuntimeError("audit backend down")
        self.entries.append(entry)


def _auth(roles: frozenset[str] = frozenset({"user"})) -> AuthContext:
    return AuthContext(user_id="u1", team_id="t1", roles=roles)


# ─── check_permission ──────────────────────────────────────────────────────────


def test_check_permission_allows_when_tool_not_in_table():
    assert check_permission(_auth(), "any_tool", {}) is True


def test_check_permission_denies_when_role_not_in_allowed_set():
    table = {"admin_tool": frozenset({"admin"})}
    assert check_permission(_auth(roles=frozenset({"user"})), "admin_tool", table) is False


def test_check_permission_allows_when_role_matches():
    table = {"admin_tool": frozenset({"admin"})}
    assert check_permission(_auth(roles=frozenset({"admin"})), "admin_tool", table) is True


# ─── Sentinel.pre_call ──────────────────────────────────────────────────────────


def _sentinel(warden=None, permission_table=None, audit_log=None) -> Sentinel:
    return Sentinel(
        warden=warden or _StubWarden(),
        permission_table=permission_table or {},
        audit_log=audit_log,
    )


async def test_pre_call_permission_denied_short_circuits_before_schema_check():
    audit = _StubAuditLog()
    sentinel = _sentinel(permission_table={"locked_tool": frozenset({"admin"})}, audit_log=audit)
    verdict = await sentinel.pre_call(
        "locked_tool", {"bad": "args"}, _auth(), schema={"required": ["x"]}
    )
    assert verdict.allowed is False
    assert len(verdict.violations) == 1
    assert verdict.violations[0].rule == "permission_denied"
    assert verdict.repaired_data is None
    assert audit.entries[0].verdict == "denied"


async def test_pre_call_allowed_with_clean_schema():
    audit = _StubAuditLog()
    sentinel = _sentinel(audit_log=audit)
    verdict = await sentinel.pre_call("tool", {"name": "x"}, _auth(), schema={})
    assert verdict.allowed is True
    assert verdict.repaired is False
    assert audit.entries[0].verdict == "allowed"


async def test_pre_call_allowed_with_repairable_schema_issue():
    audit = _StubAuditLog()
    sentinel = _sentinel(audit_log=audit)
    schema = {"properties": {"count": {"type": "integer"}}}
    verdict = await sentinel.pre_call("tool", {"count": "5"}, _auth(), schema=schema)
    assert verdict.allowed is True
    assert verdict.repaired is True
    assert verdict.repaired_data == {"count": 5}
    assert audit.entries[0].detail == "repaired=True"
    assert audit.entries[0].verdict == "allowed"


# ─── Sentinel.post_call ─────────────────────────────────────────────────────────


async def test_post_call_clean_result_passes_through_unchanged():
    audit = _StubAuditLog()
    sentinel = _sentinel(warden=_StubWarden(WardenVerdict(clean=True)), audit_log=audit)
    result = await sentinel.post_call("tool", "just a normal result", _auth())
    assert result == "just a normal result"
    assert audit.entries[0].verdict == "clean"


async def test_post_call_dirty_warden_verdict_blocks_result():
    audit = _StubAuditLog()
    dirty = WardenVerdict(clean=False, flags=("high_instruction_density",))
    sentinel = _sentinel(warden=_StubWarden(dirty), audit_log=audit)
    result = await sentinel.post_call("tool", "malicious payload", _auth())
    assert result == "[Tool result blocked by Warden -- contained injection attempt]"
    assert audit.entries[0].verdict == "flagged"


async def test_post_call_pii_detected_is_redacted_and_flagged():
    audit = _StubAuditLog()
    sentinel = _sentinel(audit_log=audit)
    result = await sentinel.post_call("tool", "contact me at bob@example.com", _auth())
    assert "bob@example.com" not in result
    assert "[REDACTED:email]" in result
    assert audit.entries[0].verdict == "flagged"


async def test_post_call_both_warden_dirty_and_pii_produces_single_audit_call():
    audit = _StubAuditLog()
    dirty = WardenVerdict(clean=False, flags=("x",))
    sentinel = _sentinel(warden=_StubWarden(dirty), audit_log=audit)
    result = await sentinel.post_call("tool", "contact bob@example.com", _auth())
    assert result == "[Tool result blocked by Warden -- contained injection attempt]"
    assert len(audit.entries) == 1
    assert audit.entries[0].verdict == "flagged"


async def test_post_call_long_result_is_optimized():
    audit = _StubAuditLog()
    sentinel = _sentinel(audit_log=audit)
    long_result = "x" * 5000
    result = await sentinel.post_call("tool", long_result, _auth())
    assert len(result) < len(long_result)
    assert result.endswith("[... truncated, full result available in trace]")


# ─── Sentinel._log_audit ────────────────────────────────────────────────────────


async def test_log_audit_noop_when_no_audit_log_configured():
    sentinel = _sentinel(audit_log=None)
    # Should not raise even though there's nothing to log to.
    await sentinel.post_call("tool", "clean result", _auth())


async def test_log_audit_swallows_exception_from_failing_audit_backend():
    audit = _StubAuditLog(raise_on_log=True)
    sentinel = _sentinel(audit_log=audit)
    # Must not propagate the RuntimeError raised inside audit.log().
    result = await sentinel.post_call("tool", "clean result", _auth())
    assert result == "clean result"
    assert audit.entries == []  # log() raised before appending


async def test_log_audit_explicit_detail_from_pre_call_repair():
    captured: list[AuditEntry] = []

    class _CapturingAuditLog:
        async def log(self, entry: AuditEntry) -> None:
            captured.append(entry)

    sentinel = _sentinel(audit_log=_CapturingAuditLog())
    schema = {"properties": {"count": {"type": "integer"}}}
    await sentinel.pre_call("tool", {"count": "5"}, _auth(), schema=schema)
    # pre_call always passes a non-empty `detail` alongside `repaired_data`, so the
    # `repaired_data_keys=...` auto-population branch in _log_audit (only triggered
    # when repaired_data is set but detail is empty) is unreachable via this caller.
    assert captured[0].detail == "repaired=True"


# ─── _detection_layer ──────────────────────────────────────────────────────────


def test_detection_layer_llm_classification_flag():
    verdict = WardenVerdict(flags=("llm_classification_suspicious",))
    assert _detection_layer(verdict) == "Layer 3 (LLM)"


def test_detection_layer_prescriptive_flag():
    verdict = WardenVerdict(flags=("prescriptive_language",))
    assert _detection_layer(verdict) == "Layer 2.5 (Semantic)"


def test_detection_layer_high_instruction_flag():
    verdict = WardenVerdict(flags=("high_instruction_density",))
    assert _detection_layer(verdict) == "Layer 2 (Heuristic)"


def test_detection_layer_encoded_flag():
    verdict = WardenVerdict(flags=("encoded_payload",))
    assert _detection_layer(verdict) == "Layer 2 (Heuristic)"


def test_detection_layer_no_matching_prefix_defaults_to_layer_1():
    verdict = WardenVerdict(flags=("some_unrecognized_flag",))
    assert _detection_layer(verdict) == "Layer 1 (Pattern)"


def test_detection_layer_empty_flags_defaults_to_layer_1():
    assert _detection_layer(WardenVerdict(flags=())) == "Layer 1 (Pattern)"


def test_detection_layer_first_matching_flag_wins_in_iteration_order():
    # "prescriptive_" appears before "llm_classification" in iteration order,
    # so the loop returns on the first flag that matches any branch.
    verdict = WardenVerdict(flags=("prescriptive_language", "llm_classification_x"))
    assert _detection_layer(verdict) == "Layer 2.5 (Semantic)"
