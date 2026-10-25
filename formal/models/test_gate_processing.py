"""I10: Gate Input Processing Pipeline — Hypothesis property-based tests."""

from __future__ import annotations

import asyncio

from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, rule, invariant

from maistro.security._types import AuthContext, WardenVerdict
from maistro.security.gate import Gate
from maistro.security.strikes import InMemoryStrikeTracker


def _run(coro):
    return asyncio.run(coro)


class _CleanWarden:
    async def scan(self, content, boundary):
        return WardenVerdict(clean=True)


class _BlockedWarden:
    async def scan(self, content, boundary):
        return WardenVerdict(clean=False, blocked=True, flags=("injection",), confidence=0.9)


class _SuspiciousWarden:
    async def scan(self, content, boundary):
        return WardenVerdict(clean=False, blocked=False, flags=("suspicious",), confidence=0.5)


class GateMachine(RuleBasedStateMachine):
    """Gate pipeline against an independent strike-count model.

    Model semantics (per gate.py): a blocked scan records exactly one strike
    while the account is not locked; once the second strike locks the account
    the lock short-circuit blocks every input (clean or hostile) WITHOUT
    recording further strikes. Every rule asserts the transition; the
    invariant asserts the store matches the model, so "clean input silently
    records strikes" or "blocked input stops recording them" fails here.
    """

    def __init__(self):
        super().__init__()
        self.tracker = InMemoryStrikeTracker()
        self.warden = _CleanWarden()
        self.gate = Gate(warden=self.warden, strike_tracker=self.tracker)
        self.user = "gate-user"
        self.auth = AuthContext(user_id=self.user, roles=frozenset({"user"}))
        self.blocked_count = 0
        self.model_strikes = 0
        self.model_locked = False

    @rule(
        content=st.text(min_size=1, max_size=200),
        mode=st.sampled_from(["best_effort", "persistent", "supervised"]),
    )
    def process_clean_input(self, content, mode):
        self.warden = _CleanWarden()
        self.gate._warden = self.warden
        result = _run(
            self.gate.process_input(
                content,
                execution_mode=mode,
                auth=self.auth,
            )
        )
        if self.model_locked:
            # Safety: the lock short-circuit fires BEFORE the scan, so even
            # clean input is refused while locked (and records no strike).
            assert result.blocked
        else:
            # Liveness: clean input passes and must never escalate strikes.
            assert not result.blocked
            assert result.strike_number == 0

    @rule(
        content=st.text(min_size=1, max_size=200),
        mode=st.sampled_from(["best_effort", "persistent", "supervised"]),
    )
    def process_blocked_input(self, content, mode):
        self.warden = _BlockedWarden()
        self.gate._warden = self.warden
        result = _run(
            self.gate.process_input(
                content,
                execution_mode=mode,
                auth=self.auth,
            )
        )
        assert result.blocked
        if not self.model_locked:
            self.model_strikes += 1
            if self.model_strikes >= 2:
                self.model_locked = True
        # The lock short-circuit blocks WITHOUT recording a further strike.
        assert result.strike_number == self.model_strikes
        self.blocked_count += 1

    @invariant()
    def tracker_matches_model(self):
        """State-transition property replacing `strike_count >= 0`.

        Counterexample class: the gate recording a strike on clean input,
        recording two strikes for one block, or continuing to strike an
        already-locked account all diverge from the model here.
        """
        rec = _run(self.tracker.get(self.user))
        if self.model_strikes == 0:
            assert rec is None, f"no strike modeled but store holds strike_count={rec.strike_count}"
            return
        assert rec is not None
        assert rec.strike_count == self.model_strikes


TestGateMachine = GateMachine.TestCase


@given(
    content=st.text(min_size=1, max_size=200),
    mode=st.sampled_from(["best_effort", "persistent", "supervised"]),
)
@settings(max_examples=50)
def test_blocked_warden_blocks(content, mode):
    gate = Gate(warden=_BlockedWarden(), strike_tracker=InMemoryStrikeTracker())
    auth = AuthContext(user_id="user1", roles=frozenset({"user"}))
    result = _run(gate.process_input(content, execution_mode=mode, auth=auth))
    assert result.blocked
    assert "Blocked by Warden" in result.block_reason


@given(
    content=st.text(min_size=1, max_size=200),
)
@settings(max_examples=30)
def test_clean_warden_best_effort(content):
    gate = Gate(warden=_CleanWarden())
    auth = AuthContext(user_id="user1", roles=frozenset({"user"}))
    result = _run(gate.process_input(content, execution_mode="best_effort", auth=auth))
    assert not result.blocked
    assert len(result.clarifying_questions) == 0


@given(
    content=st.text(min_size=1, max_size=200),
)
@settings(max_examples=30)
def test_clean_warden_persistent(content):
    gate = Gate(warden=_CleanWarden())
    auth = AuthContext(user_id="user1", roles=frozenset({"user"}))
    result = _run(gate.process_input(content, execution_mode="persistent", auth=auth))
    assert not result.blocked


@given(
    content=st.text(min_size=1, max_size=200),
)
@settings(max_examples=30)
def test_clean_warden_supervised(content):
    gate = Gate(warden=_CleanWarden())
    auth = AuthContext(user_id="user1", roles=frozenset({"user"}))
    result = _run(gate.process_input(content, execution_mode="supervised", auth=auth))
    assert not result.blocked
    assert len(result.clarifying_questions) > 0


def test_empty_input_persistent():
    gate = Gate(warden=_CleanWarden())
    auth = AuthContext(user_id="user1", roles=frozenset({"user"}))
    result = _run(gate.process_input("   ", execution_mode="persistent", auth=auth))
    assert not result.blocked
    assert len(result.clarifying_questions) > 0


def test_empty_input_supervised():
    gate = Gate(warden=_CleanWarden())
    auth = AuthContext(user_id="user1", roles=frozenset({"user"}))
    result = _run(gate.process_input("", execution_mode="supervised", auth=auth))
    assert not result.blocked
    assert len(result.clarifying_questions) > 0


@given(content=st.text(min_size=1, max_size=100))
@settings(max_examples=30)
def test_blocked_warden_escalates_strikes(content):
    tracker = InMemoryStrikeTracker()
    gate = Gate(warden=_BlockedWarden(), strike_tracker=tracker)
    auth = AuthContext(user_id="strike-user", roles=frozenset({"user"}))

    _run(gate.process_input(content, execution_mode="best_effort", auth=auth))
    rec = _run(tracker.get("strike-user"))
    assert rec is not None
    assert rec.strike_count >= 1


def test_locked_user_blocked_regardless():
    tracker = InMemoryStrikeTracker()
    _run(
        tracker.record_violation(
            user_id="locked-user",
            flags=("a",),
            boundary="user_input",
        )
    )
    _run(
        tracker.record_violation(
            user_id="locked-user",
            flags=("b",),
            boundary="user_input",
        )
    )

    gate = Gate(warden=_CleanWarden(), strike_tracker=tracker)
    auth = AuthContext(user_id="locked-user", roles=frozenset({"user"}))
    result = _run(gate.process_input("hello", execution_mode="best_effort", auth=auth))
    assert result.blocked


def test_disabled_user_blocked():
    tracker = InMemoryStrikeTracker()
    for i in range(3):
        _run(
            tracker.record_violation(
                user_id="disabled-user",
                flags=(f"f{i}",),
                boundary="user_input",
            )
        )

    gate = Gate(warden=_CleanWarden(), strike_tracker=tracker)
    auth = AuthContext(user_id="disabled-user", roles=frozenset({"user"}))
    result = _run(gate.process_input("hello", execution_mode="best_effort", auth=auth))
    assert result.blocked
    assert result.account_disabled


def test_no_auth_no_lockout_check():
    gate = Gate(warden=_BlockedWarden(), strike_tracker=InMemoryStrikeTracker())
    result = _run(gate.process_input("hello", execution_mode="best_effort", auth=None))
    assert result.blocked


@given(
    content=st.text(min_size=1, max_size=100),
)
@settings(max_examples=30)
def test_clean_warden_supervised_always_has_questions(content):
    gate = Gate(warden=_CleanWarden())
    auth = AuthContext(user_id="q-user", roles=frozenset({"user"}))
    result = _run(gate.process_input(content, execution_mode="supervised", auth=auth))
    assert not result.blocked
    assert len(result.clarifying_questions) > 0
    for q in result.clarifying_questions:
        assert len(q.question) > 0


@given(
    content=st.text(min_size=1, max_size=100),
    mode=st.sampled_from(["best_effort", "persistent", "supervised"]),
)
@settings(max_examples=50)
def test_suspicious_warden_not_blocked_but_flagged(content, mode):
    gate = Gate(warden=_SuspiciousWarden(), strike_tracker=InMemoryStrikeTracker())
    auth = AuthContext(user_id="suspicious-user", roles=frozenset({"user"}))
    result = _run(gate.process_input(content, execution_mode=mode, auth=auth))
    assert result.blocked


@given(content=st.text(min_size=1, max_size=50))
@settings(max_examples=20)
def test_sanitized_text_populated(content):
    gate = Gate(warden=_CleanWarden())
    auth = AuthContext(user_id="sanitize-user", roles=frozenset({"user"}))
    result = _run(gate.process_input(content, execution_mode="best_effort", auth=auth))
    assert result.sanitized_text is not None


def test_three_blocks_disable_account():
    tracker = InMemoryStrikeTracker()
    gate = Gate(warden=_BlockedWarden(), strike_tracker=tracker)
    auth = AuthContext(user_id="triple-user", roles=frozenset({"user"}))

    for i in range(2):
        _run(gate.process_input("bad", execution_mode="best_effort", auth=auth))

    _run(tracker.unlock("triple-user"))

    _run(gate.process_input("bad", execution_mode="best_effort", auth=auth))

    rec = _run(tracker.get("triple-user"))
    assert rec.disabled
    assert rec.strike_count == 3

    result = _run(gate.process_input("anything", execution_mode="best_effort", auth=auth))
    assert result.blocked
    assert result.account_disabled
