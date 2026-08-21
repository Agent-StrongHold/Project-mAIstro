"""Tests for the stateful, sequence-aware policy engine."""

from __future__ import annotations

from maistro.policy import (
    Action,
    AfterCountRule,
    BudgetRule,
    Decision,
    ForbiddenPairRule,
    PolicyActionGate,
    SequencePolicyEngine,
    VelocityRule,
)


def test_budget_denies_when_cumulative_limit_exceeded():
    engine = SequencePolicyEngine([BudgetRule("tokens", limit=100)])
    assert engine.charge("s", Action("turn", tokens=60)).decision is Decision.ALLOW
    # Second turn would push cumulative tokens to 120 > 100 → deny, and NOT commit.
    v = engine.charge("s", Action("turn", tokens=60))
    assert v.decision is Decision.DENY and "tokens" in v.reason
    assert engine.snapshot("s").tokens == 60  # denied action did not advance the budget
    # A smaller turn that fits still passes afterward.
    assert engine.charge("s", Action("turn", tokens=30)).decision is Decision.ALLOW
    assert engine.snapshot("s").tokens == 90


def test_after_count_requires_approval_then_commits_on_approval():
    engine = SequencePolicyEngine([AfterCountRule("write", threshold=2)])
    assert engine.charge("s", Action("write")).decision is Decision.ALLOW
    assert engine.charge("s", Action("write")).decision is Decision.ALLOW
    # Third write exceeds threshold → require approval, not committed yet.
    v = engine.charge("s", Action("write"))
    assert v.decision is Decision.REQUIRE_APPROVAL
    assert engine.snapshot("s").counts_by_kind["write"] == 2
    # Re-charge with approval → commits.
    assert engine.charge("s", Action("write"), approved=True).decision is Decision.ALLOW
    assert engine.snapshot("s").counts_by_kind["write"] == 3


def test_forbidden_pair_gates_ordering():
    engine = SequencePolicyEngine([ForbiddenPairRule(before="credential_read", after="git_push")])
    # git_push alone is fine.
    assert engine.charge("s", Action("git_push")).decision is Decision.ALLOW
    engine.reset("s")
    # But git_push after a credential_read requires approval.
    assert engine.charge("s", Action("credential_read")).decision is Decision.ALLOW
    assert engine.charge("s", Action("git_push")).decision is Decision.REQUIRE_APPROVAL


def test_forbidden_pair_survives_history_window_eviction():
    # The `before` action must keep gating even after it scrolls out of the
    # bounded recent-history window — otherwise padding history bypasses it.
    engine = SequencePolicyEngine(
        [ForbiddenPairRule(before="credential_read", after="git_push")],
        history_limit=4,
    )
    assert engine.charge("s", Action("credential_read")).decision is Decision.ALLOW
    for _ in range(10):  # far more than history_limit unrelated actions
        assert engine.charge("s", Action("noop")).decision is Decision.ALLOW
    assert engine.snapshot("s").history.maxlen == 4  # credential_read long evicted
    assert engine.charge("s", Action("git_push")).decision is Decision.REQUIRE_APPROVAL


def test_deny_beats_require_approval():
    engine = SequencePolicyEngine(
        [
            AfterCountRule("write", threshold=0),  # would require approval
            BudgetRule("count", limit=0),  # would deny
        ]
    )
    v = engine.charge("s", Action("write"))
    assert v.decision is Decision.DENY  # hard deny short-circuits over approval-gate


def test_velocity_limits_within_window():
    engine = SequencePolicyEngine([VelocityRule("call", max_in_window=2, window=3)])
    assert engine.charge("s", Action("call")).decision is Decision.ALLOW
    assert engine.charge("s", Action("call")).decision is Decision.ALLOW
    # 3rd call within the last-3 window trips the velocity cap.
    assert engine.charge("s", Action("call")).decision is Decision.DENY


def test_keys_are_isolated():
    engine = SequencePolicyEngine([BudgetRule("count", limit=1)])
    assert engine.charge("a", Action("x")).decision is Decision.ALLOW
    assert engine.charge("b", Action("x")).decision is Decision.ALLOW  # separate key, own budget
    assert engine.charge("a", Action("x")).decision is Decision.DENY


async def test_policy_action_gate_bridges_to_harness():
    engine = SequencePolicyEngine([AfterCountRule("rm", threshold=0)])
    gate = PolicyActionGate(engine, key="sess", kind_field="tool")
    # First rm exceeds threshold 0 → require approval → gate denies (allow() is bool).
    assert await gate.allow({"tool": "rm", "path": "/"}) is False
    # A different tool passes.
    assert await gate.allow({"tool": "ls"}) is True


def test_snapshot_returns_defensive_copy():
    engine = SequencePolicyEngine([AfterCountRule("w", threshold=5)])
    engine.charge("s", Action("w"))
    snap = engine.snapshot("s")
    snap.counts_by_kind.clear()
    snap.tokens = 999
    # Mutating the snapshot must not change the engine's live state.
    assert engine.snapshot("s").counts_by_kind == {"w": 1}
    assert engine.snapshot("s").tokens == 0


def test_decision_sink_fires_on_non_allow_only():
    events: list[tuple[str, str, Decision]] = []
    engine = SequencePolicyEngine(
        [BudgetRule("count", limit=1)],
        on_decision=lambda key, action, verdict: events.append(
            (key, action.kind, verdict.decision)
        ),
    )
    assert engine.charge("s", Action("a")).decision is Decision.ALLOW  # no event
    assert engine.charge("s", Action("b")).decision is Decision.DENY  # emits
    assert events == [("s", "b", Decision.DENY)]


class TestChargeNormalization:
    """Charges come off the foreign harness's action envelope. A negative
    value would CREDIT the budget; a NaN cost makes every later
    `value > limit` comparison False, disabling BudgetRule enforcement for
    the session (Codex, #262)."""

    def test_negative_and_nonfinite_charges_are_zeroed(self):
        from maistro.policy.gate import _as_number

        assert _as_number(-500) == 0.0
        assert _as_number(float("nan")) == 0.0
        assert _as_number(float("inf")) == 0.0
        assert _as_number(float("-inf")) == 0.0

    def test_ordinary_charges_pass_through(self):
        from maistro.policy.gate import _as_number

        assert _as_number(12.5) == 12.5
        assert _as_number("3") == 3.0
        assert _as_number(None) == 0.0
        assert _as_number("garbage") == 0.0
