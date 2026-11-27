---
inventory-delta:
  packages/maistro-turing/tests: +6
---
# Issue #9 — interrupted chat turns preserve completed history

Extends the existing provider-failure rollback slice without enabling autonomous
cognition or adding execution authority. The reachable chat node continues to
run under the canonical Run/NodeRun/Attempt path.

Six parametrized runtime cases fill the session through successful turns, then
fail or cancel at classification, provider completion, or output scanning.
They require exact preservation of completed history and no episodic capture,
then recover and verify that only a successful turn evicts the oldest complete
pair. This catches both cancellation leaving an unanswered user entry and
pre-emptive trimming losing previously completed history on ordinary failure.

The existing backend cancellation test is strengthened (zero count delta): it
uses the composed real chat session/bridges rather than a BlockingSession stub,
cancels during provider completion, checks canonical cancellation evidence and
unchanged history/no capture, then recovers through a distinct completed Run.

Validation on this worktree:

- Before the production repair: all six new runtime cases failed at exact
  history equality; the strengthened backend case failed with the unanswered
  `hello` retained after canonical cancellation had succeeded.
- `uv run pytest packages/maistro-turing/tests -x -q`: 233 passed.
- `uv run pytest packages/maistro-turing/backend/tests -x -q`: 125 passed
  (one runpy warning from the existing provision-module test).
- `uv run ruff check .` and `uv run ruff format --check .`: passed.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-turing/tests --suite packages/maistro-turing/backend/tests`:
  both counts match; 358 unique test identities, no duplicate evidence.
- `uv run python scripts/check-execution-lifecycles.py` and
  `uv run python scripts/check-model-egress.py`: passed their ratchets. These
  are no-expansion checks, not proof that all existing convergence debt is gone.
- Combined invocation of both package suites: 358 passed, one existing warning.
- `uv run python scripts/check-test-duplicates.py`: passed (zero identical groups).

This is not evidence that the six milestone-wide exit conditions of #9 are
complete. The standalone backend still explicitly composes in-memory stores;
no persistent autonomous Goal loop, activation cage, or RSI re-enable is added.
