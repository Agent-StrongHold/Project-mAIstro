# auto-147 repair-phase re-check at head 7524465

Independent re-execution at `752446569896c9f5491589ffa9308dde7413de29`. That head differs from
the previously verified `14e5b3330` only by the docs note
`docs/testing/inventory-notes/auto-147-verifier-final.md` (`git diff --stat` is 1 file, 51
insertions), so every production path verified there is byte-identical here; everything below
was nonetheless re-executed at this exact head, not inherited.

## Re-executed validation (all at 7524465)

- `uv run pytest packages/maistro-core/tests/graph/nodes/test_agent_delegate_remote_child_run.py
  packages/maistro-core/tests/graph/nodes/test_agent_delegate_remote_review.py` — 49 passed.
- `uv run pytest` on task_kinds / human_pause_reasons / factory / answer_gated_recovery — 112
  passed; `packages/hive-conductor/backend/tests/test_maistro_core_adapter.py` — 9 passed.
- `uv run ruff check .` clean; `uv run ruff format --check .` clean (2527 files);
  `uv run mypy` over the six package src trees clean (712 files).
- `scripts/check-suite-inventory.py` for both changed suites — ok.
- Required ac-state gate re-run in CI shape at this head:
  `check-ac-state.py --run-tests --ratchet --mandate 8bb344e32` with `MAISTRO_TEST_PG_DSN`
  (pg18 container `auto-147-pg`, `alembic upgrade head` re-applied first) — EXIT 0;
  `'Implemented', contradicted: 0`; design coverage 37.693% exactly on the banked bound;
  acceptance and chain mandates OK against base `8bb344e32`.
- Production wiring read-verified at this head: `Container.node_resolver()`
  (`container.py:871-881`) and `dag_agents.py:105-113` both pass the container's
  a2a_delegator/guest_peers/run_store into `build_node_resolver`; the bare
  `build_node_resolver()` at `dag_agents.py:70` is the pre-Container fallback whose delegate
  node now raises `DelegationNotConfiguredError` instead of returning a declined-looking
  result.
- `uv run pyright` is not installed in this local environment (spawn failure); the pyright
  ratchet (baseline 21) remains verified by CI only — the workflow comment already accounts
  for #147's findings when it was ratcheted.

## Prior-findings re-adjudication (executed evidence, not inherited)

- Receipt placeholder: `_yield_transport_attempt` writes `result={"mode": mode}` only and
  `test_the_reservation_attempt_records_no_receipt_placeholder` asserts that exact dict
  (no `task_id` key) — PASSED here; `test_the_settling_attempt_names_the_transport_receipt`
  PASSED here. The Run-provenance `a2a_task_id` write is #147's own acceptance item and is
  pinned equal to the settling Attempt's `task_id` by test.
- ac-state note deletions vs base: the merge-time ratchet folds the base revision's notes
  ("folded from 72 note(s) at 8bb344e32b86" in this run's output), so candidate-side
  deletions cannot hide a regression; `--compact` is documented maintenance validated
  idempotent by the tool's own `after != before` guard.
- No `fixes/closes/resolves` keywords in any commit message on `8bb344e32..7524465`.
