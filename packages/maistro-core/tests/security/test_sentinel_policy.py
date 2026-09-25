"""Coverage for maistro.security.sentinel.policy (Sentinel pre_call/post_call pipeline)."""

from __future__ import annotations

import aiosqlite

from maistro.capabilities.bootstrap import default_capability_registry
from maistro.capabilities.types import FallbackPolicy, SlotSpec
from maistro.persistence.sqlite_audit import SqliteAuditLog
from maistro.security._types import (
    AuditEntry,
    AuthContext,
    WardenVerdict,
)
from maistro.security.sentinel.permission_source import (
    CapabilityPermissionSource,
    StaticPermissionSource,
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


def _auth(roles: frozenset[str] = frozenset({"user"}), *, org_id: str = "") -> AuthContext:
    return AuthContext(user_id="u1", org_id=org_id, team_id="t1", roles=roles)


# ─── check_permission ──────────────────────────────────────────────────────────


def test_check_permission_denies_when_tool_not_in_table():
    """Fail-closed default (ADR-072726-0d6b, #1165): a table miss is a denial.
    Mutation-kill: flipping the miss branch back to allow fails here, in the
    formal I6 amendment, and in the container wiring test."""
    assert check_permission(_auth(), "any_tool", {}) is False


def test_check_permission_allow_on_miss_compat_mode_allows():
    """The compatibility mode is explicit, never the default (issue #1165)."""
    assert check_permission(_auth(), "any_tool", {}, allow_on_miss=True) is True


def test_check_permission_compat_mode_still_honours_explicit_entries():
    """allow_on_miss widens only the miss branch; explicit decisions stand."""
    table = {"admin_tool": frozenset({"admin"})}
    assert (
        check_permission(_auth(roles=frozenset({"user"})), "admin_tool", table, allow_on_miss=True)
        is False
    )
    assert (
        check_permission(_auth(roles=frozenset({"admin"})), "admin_tool", table, allow_on_miss=True)
        is True
    )


def test_check_permission_denies_when_role_not_in_allowed_set():
    table = {"admin_tool": frozenset({"admin"})}
    assert check_permission(_auth(roles=frozenset({"user"})), "admin_tool", table) is False


def test_check_permission_allows_when_role_matches():
    table = {"admin_tool": frozenset({"admin"})}
    assert check_permission(_auth(roles=frozenset({"admin"})), "admin_tool", table) is True


# ─── Sentinel.pre_call ──────────────────────────────────────────────────────────


def _sentinel(warden=None, permission_table=None, audit_log=None) -> Sentinel:
    # COMPATIBILITY construction (issue #1165): the suites below exercise
    # schema validation/repair, audit plumbing and output processing, not
    # permission semantics, so they arm the explicit allow-on-miss mode rather
    # than granting tools they never use. Default-deny behavior is pinned by
    # the dedicated fail-closed tests above and below.
    return Sentinel(
        warden=warden or _StubWarden(),
        permission_table=permission_table or {},
        audit_log=audit_log,
        allow_on_miss=True,
    )


async def test_sentinel_writes_a_canonical_entry_to_sqlite() -> None:
    conn = await aiosqlite.connect(":memory:")
    try:
        audit = SqliteAuditLog(conn)
        await audit.ensure_schema()
        sentinel = _sentinel(audit_log=audit)

        verdict = await sentinel.pre_call("tool", {}, _auth(org_id="org-a"), schema={})

        assert verdict.allowed is True
        entries = await audit.get_entries(org_id="org-a")
        assert len(entries) == 1
        assert entries[0].boundary == "pre_call"
        assert entries[0].user_id == "u1"
        assert entries[0].org_id == "org-a"
        assert entries[0].timestamp is not None
    finally:
        await conn.close()


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


# ─── Fail-closed defaults (ADR-072726-0d6b, issue #1165) ─────────────────────


async def test_pre_call_denies_unknown_tool_on_empty_table():
    """The previously-allow-all case: an empty table denies everything.
    Mutation-kill: reverting the miss branch to allow flips this verdict."""
    sentinel = Sentinel(warden=_StubWarden(), permission_table={})
    verdict = await sentinel.pre_call("never_configured_tool", {}, _auth(), schema={})
    assert verdict.allowed is False
    assert verdict.violations[0].rule == "permission_denied"


async def test_pre_call_denies_unknown_tool_on_governed_production_table():
    """Unknown tools are denied even when a real governed table is armed."""
    from maistro.security.permission_policy import build_permission_table

    table = build_permission_table(preset="dangerous_tools_admin")
    sentinel = Sentinel(warden=_StubWarden(), permission_table=table)
    verdict = await sentinel.pre_call("tool_not_in_any_preset", {}, _auth(), schema={})
    assert verdict.allowed is False


async def test_pre_call_allows_explicitly_permitted_tool_on_governed_table():
    """Explicit allow survives the fail-closed default: a listed tool for a
    role the table names is allowed; the same tool for an unlisted role is not."""
    from maistro.security.permission_policy import build_permission_table

    table = build_permission_table(preset="dangerous_tools_admin")
    sentinel = Sentinel(warden=_StubWarden(), permission_table=table)
    dangerous = sorted(table)[0]
    allowed = await sentinel.pre_call(dangerous, {}, _auth(roles=frozenset({"admin"})), schema={})
    assert allowed.allowed is True
    denied = await sentinel.pre_call(dangerous, {}, _auth(roles=frozenset({"user"})), schema={})
    assert denied.allowed is False


async def test_authorize_denies_action_on_empty_table():
    """The authorize (tier-ladder) path fails closed on a missing decision too."""
    from maistro.security.sentinel.authz_types import Principal

    sentinel = Sentinel(warden=_StubWarden(), permission_table={})
    decision = await sentinel.authorize("unlisted_action", Principal(id="p1", kind="human"))
    assert decision.authorized is False
    assert "lacks capability" in decision.reason


async def test_authorize_allows_explicitly_permitted_action():
    from maistro.security.sentinel.authz_types import Principal

    sentinel = Sentinel(warden=_StubWarden(), permission_table={"deploy": frozenset({"admin"})})
    decision = await sentinel.authorize(
        "deploy", Principal(id="p1", kind="human", roles=("admin",))
    )
    assert decision.authorized is True


async def test_allow_on_miss_mode_allows_unknown_tool_and_warns(caplog):
    """The compatibility mode is real, but loud: arming it logs a warning so a
    permissive construction cannot pass unnoticed."""
    import logging

    sentinel = Sentinel(warden=_StubWarden(), permission_table={}, allow_on_miss=True)
    verdict = await sentinel.pre_call("tool_absent_from_table", {}, _auth(), schema={})
    assert verdict.allowed is True
    assert any(
        "allow-on-miss" in r.message and r.levelno == logging.WARNING for r in caplog.records
    )


async def test_allow_on_miss_mode_denies_regardless_of_role_when_entry_exists():
    """Compat mode widens only the miss branch: an explicit entry with an
    empty role set still denies everyone, including admins."""
    sentinel = Sentinel(
        warden=_StubWarden(),
        permission_table={"hard_denied": frozenset()},
        allow_on_miss=True,
    )
    verdict = await sentinel.pre_call("hard_denied", {}, _auth(), schema={})
    assert verdict.allowed is False


# ─── Live permission source (#1165): canonical reconciliation + runtime revoke ─


def _registry_with(slot: str):

    registry = default_capability_registry()
    if slot not in registry.slots():
        registry.define(SlotSpec(name=slot, fallback_policy=FallbackPolicy.SAFE_NOOP))
    return registry


class _UnavailableSource:
    """A policy store that is down: no decision is available."""

    async def current_table(self):
        raise RuntimeError("policy store down")


async def test_sentinel_with_source_allows_explicit_entry_and_denies_miss():
    """A wired source is the authority: its explicit entries allow, its
    misses deny -- exactly the static table's fail-closed semantics."""
    sentinel = Sentinel(
        warden=_StubWarden(),
        permission_table={},
        permission_source=StaticPermissionSource({"deploy": frozenset({"admin"})}),
    )
    allowed = await sentinel.pre_call("deploy", {}, _auth(roles=frozenset({"admin"})), schema={})
    assert allowed.allowed is True
    denied = await sentinel.pre_call("unlisted", {}, _auth(roles=frozenset({"admin"})), schema={})
    assert denied.allowed is False
    assert denied.violations[0].rule == "permission_denied"


async def test_pre_call_reflects_post_initialization_capability_revoke():
    """Criterion 5 (#1165): disabling a canonical capability slot revokes the
    matching tool at the very next decision, with no process restart."""
    registry = _registry_with("deploy")
    sentinel = Sentinel(
        warden=_StubWarden(),
        permission_table={},
        permission_source=CapabilityPermissionSource(
            base={"deploy": frozenset({"admin"})}, capabilities=registry
        ),
    )
    auth = _auth(roles=frozenset({"admin"}))
    assert (await sentinel.pre_call("deploy", {}, auth, schema={})).allowed is True

    registry.set_enabled("deploy", False)  # the runtime revoke gesture

    revoked = await sentinel.pre_call("deploy", {}, auth, schema={})
    assert revoked.allowed is False
    assert revoked.violations[0].rule == "permission_denied"

    registry.set_enabled("deploy", True)
    assert (await sentinel.pre_call("deploy", {}, auth, schema={})).allowed is True


async def test_authorize_reflects_post_initialization_capability_revoke():
    from maistro.security.sentinel.authz_types import Principal

    registry = _registry_with("deploy")
    sentinel = Sentinel(
        warden=_StubWarden(),
        permission_table={},
        permission_source=CapabilityPermissionSource(
            base={"deploy": frozenset({"admin"})}, capabilities=registry
        ),
    )
    principal = Principal(id="p1", kind="human", roles=("admin",))
    assert (await sentinel.authorize("deploy", principal)).authorized is True

    registry.set_enabled("deploy", False)

    decision = await sentinel.authorize("deploy", principal)
    assert decision.authorized is False
    assert "lacks capability" in decision.reason


async def test_pre_call_denies_when_permission_source_is_unavailable():
    """A source that cannot decide is not rescued by the static table: a
    stale snapshot must not outvote a revoke, so the decision fails closed."""
    sentinel = Sentinel(
        warden=_StubWarden(),
        permission_table={"deploy": frozenset({"admin"})},
        permission_source=_UnavailableSource(),
    )
    verdict = await sentinel.pre_call("deploy", {}, _auth(roles=frozenset({"admin"})), schema={})
    assert verdict.allowed is False
    assert verdict.violations[0].rule == "permission_denied"
    assert verdict.violations[0].detail == "Permission source unavailable; denied fail-closed"


async def test_authorize_denies_when_permission_source_is_unavailable():
    from maistro.security.sentinel.authz_types import Principal

    sentinel = Sentinel(
        warden=_StubWarden(),
        permission_table={"deploy": frozenset({"admin"})},
        permission_source=_UnavailableSource(),
    )
    decision = await sentinel.authorize(
        "deploy", Principal(id="p1", kind="human", roles=("admin",))
    )
    assert decision.authorized is False
    assert "unavailable" in decision.reason


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


async def test_post_call_pii_match_value_is_masked_on_product_path():
    from maistro.security.sentinel.pii_filter import scan_for_pii

    secret = "AKIAIOSFODNN7EXAMPLE"
    result = await _sentinel().post_call("tool", f"key={secret}", _auth())
    matches = scan_for_pii(f"key={secret}")

    assert secret not in result
    assert len(matches) == 1
    assert matches[0].pii_type == "aws_key"
    assert secret not in matches[0].value
    assert matches[0].value.startswith("AKIA")
    assert matches[0].value.endswith("(20 chars)")


async def test_post_call_real_warden_times_out_pathological_regex(monkeypatch):
    """The production output gate must inherit Warden's ReDoS timeout."""
    import time

    import regex

    import maistro.security.warden.detector as detector
    from maistro.security.warden.detector import Warden

    monkeypatch.setattr(
        detector,
        "REJECT_PATTERNS",
        [(regex.compile(r"(a+)+$"), "pathological test rule")],
    )

    started = time.monotonic()
    result = await _sentinel(warden=Warden()).post_call("tool", "a" * 40_000 + "b", _auth())

    assert result == "[Tool result blocked by Warden -- contained injection attempt]"
    assert time.monotonic() - started < 10


async def test_post_call_real_warden_windows_pathological_reject_input(monkeypatch):
    """The hot path bounds reject-pattern input before the fallback times out."""
    import regex

    import maistro.security.warden.detector as detector
    from maistro.security.warden.detector import Warden

    monkeypatch.setattr(
        detector,
        "REJECT_PATTERNS",
        [(regex.compile(r"(a+)+b$"), "pathological test rule")],
    )
    lengths: list[int] = []
    original = detector._scan_reject_patterns

    def record_window(text: str):
        lengths.append(len(text))
        return original(text)

    monkeypatch.setattr(detector, "_scan_reject_patterns", record_window)
    # Keep the first window cheap, then put the pathological suffix in the
    # next overlapping window so the test proves both windowing and timeout.
    text = "x" * detector._SCAN_WINDOW_CHARS + "a" * detector._SCAN_WINDOW_CHARS + "b"
    outcome = await _sentinel(warden=Warden()).process_output("tool", text, _auth())

    assert outcome.blocked is True
    assert outcome.warden_verdict is not None
    assert outcome.warden_verdict.flags == ("regex_error:pathological test rule",)
    assert len(lengths) > 1
    assert max(lengths) <= detector._SCAN_WINDOW_CHARS


async def test_post_call_real_warden_windows_large_fallback_input(monkeypatch):
    """The hot path never hands a fallback heuristic pass more than one window."""
    import re

    import maistro.security.warden._regex as regex_module
    import maistro.security.warden.detector as detector
    import maistro.security.warden.heuristics as heuristics
    from maistro.security.warden.detector import Warden

    # Rebuild the two live heuristic patterns after disabling RE2. This keeps
    # the test on the supported stdlib fallback path rather than merely
    # changing the accelerator availability flag after import.
    monkeypatch.setattr(regex_module, "_RE2_AVAILABLE", False)
    monkeypatch.setattr(
        heuristics,
        "_INSTRUCTION_TOKENS",
        regex_module.compile_pattern(heuristics._INSTRUCTION_TOKENS.pattern, re.IGNORECASE),
    )
    monkeypatch.setattr(
        heuristics,
        "_BASE64_PATTERN",
        regex_module.compile_pattern(heuristics._BASE64_PATTERN.pattern),
    )

    lengths: list[int] = []
    original = detector.heuristic_scan

    def record_window(text: str):
        lengths.append(len(text))
        return original(text)

    monkeypatch.setattr(detector, "heuristic_scan", record_window)
    text = "the quick brown fox jumps over the lazy dog. " * 3_000
    result = await _sentinel(warden=Warden()).post_call("tool", text, _auth())

    assert result.endswith("[... truncated, full result available in trace]")
    assert len(lengths) > 1
    assert max(lengths) <= detector._SCAN_WINDOW_CHARS


async def test_post_call_real_warden_windows_semantic_fallback_input(monkeypatch):
    """Layer 2.5 gets the same one-window bound on the stdlib fallback.

    The semantic patterns also compile through `_regex.compile_pattern`, so
    with RE2 unavailable the `capture`-verb search over an unwindowed body is
    the same unbounded-fallback hazard the heuristic tier covers above. The
    filler repeats capture verbs with no full-conversation suffix: benign
    enough to keep Layers 1-2 quiet, but it makes the semantic phase run its
    searches to completion over every window.
    """
    import re

    import maistro.security.warden._regex as regex_module
    import maistro.security.warden.detector as detector
    import maistro.security.warden.semantic as semantic
    from maistro.security.warden.detector import Warden

    monkeypatch.setattr(regex_module, "_RE2_AVAILABLE", False)
    for name in (
        "_DANGEROUS_ACTIONS",
        "_SENSITIVE_OBJECTS",
        "_CAPTURE_ACTIONS",
        "_FULL_CONVERSATION_OBJECTS",
        "_PRESCRIPTIVE_PATTERNS",
    ):
        monkeypatch.setattr(
            semantic,
            name,
            [
                regex_module.compile_pattern(p.pattern, re.IGNORECASE)
                for p in getattr(semantic, name)
            ],
        )

    lengths: list[int] = []

    def record_window(fn):
        def wrapper(text: str):
            lengths.append(len(text))
            return fn(text)

        return wrapper

    monkeypatch.setattr(
        detector,
        "semantic_tool_poisoning_signals",
        record_window(semantic.semantic_tool_poisoning_signals),
    )
    monkeypatch.setattr(
        detector,
        "semantic_tool_poisoning_capture_signals",
        record_window(semantic.semantic_tool_poisoning_capture_signals),
    )
    text = "capture export include report " * 2_500
    result = await _sentinel(warden=Warden()).post_call("tool", text, _auth())

    assert result.endswith("[... truncated, full result available in trace]")
    assert len(lengths) > 1
    assert max(lengths) <= detector._SCAN_WINDOW_CHARS


async def test_post_call_real_warden_preserves_padded_semantic_signal():
    """Product output scanning must not lose a semantic action across windows."""
    from maistro.security.warden.detector import Warden

    # The action and target are deliberately separated by more than one scan
    # window. The bounded semantic scanner must retain their relationship
    # without passing the padded body to one fallback regex search.
    text = "You should capture " + ("padding " * 7_000) + "full conversation"
    outcome = await _sentinel(warden=Warden()).process_output("tool", text, _auth())

    assert outcome.blocked is True
    assert outcome.warden_verdict is not None
    assert outcome.warden_verdict.clean is False
    assert "prescriptive_instruction+dangerous_action" in outcome.warden_verdict.flags


async def test_post_call_real_warden_preserves_capture_ordering():
    """A complete object before the capture verb is not the legacy attack."""
    from maistro.security.warden.detector import Warden

    texts = (
        "The full conversation should capture the entire record.",
        "The full conversation " + ("padding " * 7_000) + "should capture the entire record.",
    )
    for text in texts:
        outcome = await _sentinel(warden=Warden()).process_output("tool", text, _auth())

        assert outcome.blocked is False
        assert outcome.warden_verdict is not None
        assert outcome.warden_verdict.clean is True
        assert outcome.warden_verdict.flags == ()
    assert outcome.sanitized_text.endswith("[... truncated, full result available in trace]")


async def test_post_call_real_warden_windows_large_fallback_semantic_input(monkeypatch):
    """Layer 2.5 also stays inside the fallback regex window."""
    import re

    import maistro.security.warden._regex as regex_module
    import maistro.security.warden.detector as detector
    import maistro.security.warden.semantic as semantic
    from maistro.security.warden.detector import Warden

    monkeypatch.setattr(regex_module, "_RE2_AVAILABLE", False)
    for name in (
        "_DANGEROUS_ACTIONS",
        "_SENSITIVE_OBJECTS",
        "_CAPTURE_ACTIONS",
        "_FULL_CONVERSATION_OBJECTS",
        "_PRESCRIPTIVE_PATTERNS",
    ):
        patterns = getattr(semantic, name)
        monkeypatch.setattr(
            semantic,
            name,
            [regex_module.compile_pattern(pattern.pattern, re.IGNORECASE) for pattern in patterns],
        )

    lengths: list[int] = []
    original = detector.semantic_tool_poisoning_signals

    def record_window(text: str):
        lengths.append(len(text))
        return original(text)

    monkeypatch.setattr(detector, "semantic_tool_poisoning_signals", record_window)
    text = "the quick brown fox jumps over the lazy dog. " * 3_000
    result = await _sentinel(warden=Warden()).post_call("tool", text, _auth())

    assert result.endswith("[... truncated, full result available in trace]")
    assert len(lengths) > 1
    assert max(lengths) <= detector._SCAN_WINDOW_CHARS


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
