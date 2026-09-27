---
inventory-delta:
  packages/maistro-core/tests: 0
---

# auto-147 repair-phase re-check: #364 answer authorization drift

Re-execution at the #147 repair head after the prior round died mid-flight (provider
timeout, no checks run). Two results.

## One repair: the durable-answer test predated #364's authorization boundary

The merge of `60862b6c5` (#364, Workspace object authorization on HITL
settlement) made `CanonicalDurableRunStore.submit_hitl_answer` require a keyword-only
`HitlAuthorization`. `test_durable_parent_resumes_from_the_answer_and_settles_child`
(`test_agent_delegate_remote_child_run.py`) — the test proving a paused delegation's
answer stamps the child `run_id` from the node's own pause and requeues the parent —
still called the old shape and died with `TypeError` at HEAD.

The fix presents explicit operator evidence (effective principal + fixture Workspace +
permissive membership predicate), the same shape `test_hitl_settlement.py` uses for its
own fixtures, rather than any bypass. No test was added, moved or removed: the suite
inventory is unchanged and `scripts/check-suite-inventory.py` still reports 13/13.

## The repair moved the measured bound, and it is banked

Running the required gate in CI shape (pg18 DSN `MAISTRO_TEST_PG_DSN`/`DATABASE_URL`,
`alembic upgrade head`, `check-ac-state.py --run-tests --ratchet --mandate 55c5ad892`)
after the fix failed with `FAIL: unbanked improvement — design_coverage: 38.0924, floor
still says 37.693`: the repaired durable-answer test proves criteria the broken call
could not, and the ratchet refuses to leave that slack on the ceiling. Banked with the
same CI shape (`--bank` → `quality/ac-state-notes/auto-147.json`, this branch's own
note); the gate now exits 0 with every counter exactly on its bound.

## Both prior findings re-adjudicated with executed evidence

- *Receipt placeholder / Attempt-owned identity*: does not reproduce. The yielded
  reservation Attempt records `{"mode": ...}` and no `task_id` key at all
  (`test_the_reservation_attempt_records_no_receipt_placeholder`), and the settling
  Attempt's result carries the real receipt under `task_id`, equal to the child Run's
  `provenance["a2a_task_id"]` (`test_the_settling_attempt_names_the_transport_receipt`).
  An absent fact stays absent (ADR-082526-7f02 AC-3).
- *67 deleted `quality/ac-state-notes/*.json` + rewritten `_baseline.json`* (salvage
  commit `1aa326b4b`): fold-neutral. Folding the notes at base `657ef93fe` (72 notes)
  and at HEAD (5 notes) per counter — `max` for floored, `min` for ratcheted, the same
  rule `scripts/ac_state_notes.py::fold` applies — shows no counter weakened:
  `design_coverage` 36.5259 → 37.693 (improved via this branch's own note), every debt
  ceiling identical. The required gate reads the fold from the 72 notes at the base
  revision regardless, so the deletions cannot lower any bound it enforces.
  `'Implemented', contradicted: 0` at this head; the earlier "4 contradicted" does not
  reproduce.

## Validation battery executed at this head

- Delegation suites (`test_agent_delegate_remote`, `..._child_run`, `..._review`,
  `test_container_delegation_wiring`, `test_node_composition`): 133 passed.
- `packages/maistro-core/tests/graph/nodes/` + `packages/maistro-core/tests/runs/`:
  1165 passed, 203 skipped.
- `uv run ruff check .` clean; `uv run ruff format --check .` clean (2540 files);
  `uv run mypy packages/maistro-core/src` clean (629 files).
- `scripts/check-suite-inventory.py` ok (13 suites); `scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` exit 0.
- Required ac-state gate in CI shape (mandate base `55c5ad892`, the develop base):
  EXIT 0 — ratchet on its bounds, acceptance mandate OK, chain mandate OK,
  `'Implemented', contradicted: 0`.
