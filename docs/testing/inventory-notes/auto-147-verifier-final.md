# auto-147 verifier re-check at banked head 14e5b3330

Independent verifier re-derivation of #147 acceptance at `14e5b3330e4b21bcc56e3a36d6b2cfaf42d60818`
(the head that banks the ac-state bound). Everything below was executed by the verifier at this
exact head; nothing is inherited from the repair artifact.

## Issue acceptance — proven by execution

- `uv run pytest` on the changed suites: child-run file + review file 49 passed;
  factory/task_kinds/human-pause-reasons/delegate-remote surface 118 passed;
  `graph/durable_runs/test_answer_gated_recovery.py` 7 passed; hive
  `test_dag_agents.py` 13 passed. All named acceptance nodes PASSED: in-process child Run,
  cross-instance child Run (incl. real-HTTP `MockTransport` path), provenance
  (admission_source/mode/both agents/a2a_task_id receipt), both escape guards
  (`RunIntegrityError` via `validate_child_scope`), resolver wiring, both
  `DelegationNotConfiguredError` loud refusals, `TestTheReceiptIsAttemptOwnedIdentity`.
- `uv run ruff check .` clean; `ruff format --check .` clean (2527 files);
  `mypy` over the six package src trees clean (712 files).
- `uv run python scripts/check-suite-inventory.py`: 13/13 suites match the recorded inventory.

## Required ac-state gate — green in CI shape, executed at this head

`uv run python scripts/check-ac-state.py --run-tests --ratchet --mandate 8bb344e32` with
`MAISTRO_TEST_PG_DSN` (pg18 container, `alembic upgrade head` applied first, per
`.github/workflows/quality.yml:940-955`) exited 0: design coverage measured 37.693%, sitting
exactly on the banked bound (`quality/ac-state-notes/auto-147.json`, `measured_with_tests: true`);
`'Implemented', contradicted: 0`; unverifiable 0; acceptance and chain mandates both OK.

## Prior findings — disposition at this head

- Receipt placeholder (ADR-082526-7f02): repaired at ancestor `dc408b0fe`. Reservation Attempt
  records `{"mode": ...}` only (no `task_id: ""`); the settling Attempt carries the receipt;
  Run provenance receives `a2a_task_id` post-acceptance via `attach_delegation_receipt` —
  which is what #147's own acceptance asks the provenance to name. Pinned by three tests in
  `TestTheReceiptIsAttemptOwnedIdentity`, all PASSED.
- ac-state "4 contradicted specs" does not reproduce in CI shape: this verifier's own gate run
  reports `contradicted: 0` (exit 0). The driver commit `1aa326b4b` note deletions + baseline
  rewrite are validated by the gate itself ("folded from 72 note(s) at 8bb344e32b86"); the
  baseline move is upward (21.3053 -> 36.5259), i.e. stricter, not a weakened floor.
- `check-vulture-baseline.py` exits 1 locally, and this verifier reproduced the failure
  byte-identically at base `8bb344e32` (1430 findings, identical per-category NEW profile) in a
  detached worktree: pre-existing/environmental (local vulture resolves differently than the
  ledger's banking run), introduced by neither this branch nor measured by any #147 criterion.
  The branch's only ledger edit (pruning `register_agent_capability`, now read at
  `agents/factory.py:317`) creates no new unauthorized finding — the base ledger the gate
  compares against still authorizes it.

## Closure-keyword review

No `fixes/closes/resolves #N` in the PR body ("Refs #147" only) or in any commit message on
`8bb344e32..14e5b3330`.
