"""Coverage for maistro.security.gate.Gate (input processing pipeline)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from maistro.security._types import AuthContext, WardenVerdict
from maistro.security.gate import Gate
from maistro.security.strikes import InMemoryStrikeTracker


class _StubWarden:
    def __init__(self, verdict: WardenVerdict | None = None):
        self.verdict = verdict or WardenVerdict(clean=True)
        self.scanned_texts: list[str] = []

    async def scan(self, text: str, boundary: str) -> WardenVerdict:
        self.scanned_texts.append(text)
        return self.verdict


def _auth(user_id: str = "u1") -> AuthContext:
    return AuthContext(user_id=user_id)


# ─── Locked-account short-circuit ───────────────────────────────────────────────


async def test_disabled_account_blocks_before_warden_scan():
    warden = _StubWarden()
    tracker = InMemoryStrikeTracker()
    for _ in range(3):
        await tracker.record_violation(user_id="u1", flags=("x",))

    gate = Gate(warden=warden, strike_tracker=tracker)
    result = await gate.process_input("hello", auth=_auth())

    assert result.blocked is True
    assert result.account_disabled is True
    assert "disabled" in result.block_reason
    assert warden.scanned_texts == []


async def test_locked_not_disabled_account_blocks_before_warden_scan():
    warden = _StubWarden()
    tracker = InMemoryStrikeTracker()
    await tracker.record_violation(user_id="u1", flags=("a",))
    await tracker.record_violation(user_id="u1", flags=("b",))

    gate = Gate(warden=warden, strike_tracker=tracker)
    result = await gate.process_input("hello", auth=_auth())

    assert result.blocked is True
    assert result.account_disabled is False
    assert result.locked_until != ""
    assert result.locked_until in result.block_reason
    assert warden.scanned_texts == []


async def test_expired_lockout_falls_through_to_normal_scan():
    warden = _StubWarden()
    tracker = InMemoryStrikeTracker()
    await tracker.record_violation(user_id="u1", flags=("a",))
    record = await tracker.record_violation(user_id="u1", flags=("b",))
    record.locked_until = datetime.now(UTC) - timedelta(seconds=1)

    gate = Gate(warden=warden, strike_tracker=tracker)
    result = await gate.process_input("hello", auth=_auth())

    assert result.blocked is False
    assert warden.scanned_texts == ["hello"]


async def test_no_strike_tracker_skips_lock_check_entirely():
    warden = _StubWarden()
    gate = Gate(warden=warden, strike_tracker=None)
    result = await gate.process_input("hello", auth=_auth())
    assert result.blocked is False
    assert warden.scanned_texts == ["hello"]


async def test_empty_user_id_skips_lock_check_even_with_tracker():
    warden = _StubWarden()
    tracker = InMemoryStrikeTracker()
    for _ in range(3):
        await tracker.record_violation(user_id="anon-would-be-disabled", flags=("x",))

    gate = Gate(warden=warden, strike_tracker=tracker)
    result = await gate.process_input("hello", auth=None)
    assert result.blocked is False
    assert warden.scanned_texts == ["hello"]


# ─── Warden dirty verdict -> strike recording ───────────────────────────────────


async def test_dirty_verdict_with_tracker_records_violation_and_populates_fields():
    dirty = WardenVerdict(clean=False, flags=("injection",))
    warden = _StubWarden(dirty)
    tracker = InMemoryStrikeTracker()

    gate = Gate(warden=warden, strike_tracker=tracker)
    result = await gate.process_input("malicious", auth=_auth())

    assert result.blocked is True
    assert result.strike_number == 1
    assert result.scrutiny_level == "elevated"
    assert result.account_disabled is False
    assert result.block_reason == "Blocked by Warden: injection"


async def test_dirty_verdict_without_tracker_blocks_with_default_strike_fields():
    dirty = WardenVerdict(clean=False, flags=("injection",))
    warden = _StubWarden(dirty)

    gate = Gate(warden=warden, strike_tracker=None)
    result = await gate.process_input("malicious", auth=_auth())

    assert result.blocked is True
    assert result.strike_number == 0
    assert result.scrutiny_level == "normal"
    assert result.locked_until == ""
    assert result.account_disabled is False


# ─── execution_mode branches on clean verdict ───────────────────────────────────


async def test_best_effort_mode_passes_through_with_no_clarifying_questions():
    gate = Gate(warden=_StubWarden(), strike_tracker=None)
    result = await gate.process_input("do the thing", execution_mode="best_effort", auth=_auth())
    assert result.blocked is False
    assert result.clarifying_questions == ()


async def test_persistent_mode_empty_content_returns_sufficiency_question():
    gate = Gate(warden=_StubWarden(), strike_tracker=None)
    result = await gate.process_input("   ", execution_mode="persistent", auth=_auth())
    assert result.blocked is False
    assert len(result.clarifying_questions) == 1
    assert "empty" in result.clarifying_questions[0].question


async def test_persistent_mode_nonempty_content_passes_through():
    gate = Gate(warden=_StubWarden(), strike_tracker=None)
    result = await gate.process_input("do the thing", execution_mode="persistent", auth=_auth())
    assert result.blocked is False
    assert result.clarifying_questions == ()


async def test_supervised_mode_nonempty_content_uses_generic_confirm_question():
    gate = Gate(warden=_StubWarden(), strike_tracker=None)
    result = await gate.process_input("do the thing", execution_mode="supervised", auth=_auth())
    assert len(result.clarifying_questions) == 1
    q = result.clarifying_questions[0]
    assert q.question == "I understood your request. Should I proceed?"
    assert q.options == ("Yes, go ahead", "No, let me clarify")
    assert q.allow_freetext is True


async def test_supervised_mode_empty_content_uses_sufficiency_question_instead():
    gate = Gate(warden=_StubWarden(), strike_tracker=None)
    result = await gate.process_input("   ", execution_mode="supervised", auth=_auth())
    assert len(result.clarifying_questions) == 1
    assert "empty" in result.clarifying_questions[0].question


# ─── sanitize() applied before scan ──────────────────────────────────────────────


async def test_sanitize_applied_before_warden_scan_collapses_whitespace():
    warden = _StubWarden()
    gate = Gate(warden=warden, strike_tracker=None)
    await gate.process_input("hello   \n\n  world", auth=_auth())
    assert warden.scanned_texts == ["hello world"]
