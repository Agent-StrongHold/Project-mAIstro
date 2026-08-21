"""Stateful, sequence-aware policy engine.

``SequencePolicyEngine`` keeps a running :class:`SequenceState` per key (a session,
agent, or harness run) and evaluates each incoming :class:`Action` against a list
of rules. ``charge(key, action)``:

- computes the *prospective* state (current + action),
- runs the rules (any DENY wins immediately; else the first REQUIRE_APPROVAL
  stands unless ``approved=True``),
- commits the action to the key's state **only** on ALLOW.

DENY / REQUIRE_APPROVAL therefore do not advance the budget — a rejected action
did not happen; an approval-pending action commits when re-charged with
``approved=True``. Thread-safe via a reentrant lock.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable

from maistro.policy.rules import PolicyRule
from maistro.policy.types import Action, Decision, PolicyVerdict, SequenceState

# Sink invoked with (key, action, verdict) for every non-ALLOW decision, so an
# app consuming maistro.events can emit the `policy.decision` audit record
# (ADR-037) without this package importing the events layer.
DecisionSink = Callable[[str, Action, PolicyVerdict], None]


class SequencePolicyEngine:
    def __init__(
        self,
        rules: Iterable[PolicyRule],
        *,
        history_limit: int = 256,
        on_decision: DecisionSink | None = None,
    ) -> None:
        self._rules: list[PolicyRule] = list(rules)
        self._history_limit = history_limit
        self._on_decision = on_decision
        self._state: dict[str, SequenceState] = {}
        self._lock = threading.RLock()

    def charge(self, key: str, action: Action, *, approved: bool = False) -> PolicyVerdict:
        """Evaluate ``action`` for ``key``; commit to running state on ALLOW."""
        with self._lock:
            state = self._state.setdefault(key, SequenceState.empty(self._history_limit))
            prospective = state.with_action(action)
            verdict = self._evaluate(action, prospective, approved=approved)
            if verdict.decision is Decision.ALLOW:
                state.commit(action)
        # Emit outside the lock so a slow/blocking sink can't stall other keys.
        if verdict.decision is not Decision.ALLOW and self._on_decision is not None:
            self._on_decision(key, action, verdict)
        return verdict

    def evaluate(self, key: str, action: Action, *, approved: bool = False) -> PolicyVerdict:
        """Evaluate without committing (dry run)."""
        with self._lock:
            state = self._state.get(key, SequenceState.empty(self._history_limit))
            return self._evaluate(action, state.with_action(action), approved=approved)

    def snapshot(self, key: str) -> SequenceState:
        """Return a detached copy of the key's state — safe to read/mutate for
        logging or diagnostics without perturbing future policy decisions."""
        with self._lock:
            existing = self._state.get(key)
            return (
                existing.copy()
                if existing is not None
                else SequenceState.empty(self._history_limit)
            )

    def reset(self, key: str) -> None:
        with self._lock:
            self._state.pop(key, None)

    def _evaluate(
        self, action: Action, prospective: SequenceState, *, approved: bool
    ) -> PolicyVerdict:
        pending: PolicyVerdict | None = None
        for rule in self._rules:
            verdict = rule.evaluate(action, prospective)
            if verdict is None:
                continue
            if verdict.decision is Decision.DENY:
                return verdict  # hard deny short-circuits
            if verdict.decision is Decision.REQUIRE_APPROVAL and not approved:
                pending = pending or verdict  # first approval-gate stands; keep scanning for DENY
        return pending if pending is not None else PolicyVerdict(Decision.ALLOW)
