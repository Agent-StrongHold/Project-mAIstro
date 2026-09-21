---
inventory-delta:
  formal/: +2
  packages/maistro-rsi/tests: +1
---
# m5-342-audit-c76b — #342: promotion audit trail records what it changes

The RSI audit-trail conformance model used to *pin the hole*: its bypass
test asserted that the raw `PopulationStore.promote()` moved the active
genome while the audit trail stayed silent, and labeled that observable
gap a regression guard. #342 closes the hole from both sides and moves
the model to requiring the audit evidence.

Where the counts moved:

- `formal/` +2 — `test_rsi_audit_trail_conformance.py` replaces
  `test_bypassing_the_audited_wrapper_is_a_real_detectable_gap` with
  `test_a_state_change_without_an_audit_record_cannot_land` (asserts the
  raw entrypoints are retired and a dead audit sink blocks the mutation),
  and adds the rejection angle
  (`test_a_rejected_promotion_is_audited_as_an_attempt_without_a_commit`)
  and the tampering angle
  (`test_recorded_entries_cannot_be_forged_or_erased_from_outside`).
  Net +2 because one test was replaced (count-neutral) and two were
  added. The stateful machine also gains a replay invariant (committed
  entries alone reconstruct the active genome), which is an invariant,
  not a node ID. `test_rsi_rollback_conformance.py` was re-pointed at
  `promote_audited`/`rollback_audited` — same node IDs, different bodies.
- `packages/maistro-rsi/tests` +1 —
  `test_failed_audit_write_rolls_the_promotion_back` in
  `test_local_loop.py`: when the git-notes audit record cannot be written,
  the fast-forward promotion is reset and the cycle reports not-promoted
  (the production half of "state change without an audit record fails").
- `packages/maistro-evolve/tests` — no count change: `test_rsi_safety.py`'s
  promotion-gate and kill-switch tests now route through the audited path
  (the raw `promote()`/`rollback()` are private now), same test count.
