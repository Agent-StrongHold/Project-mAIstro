---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
---

# Issue #7: the Goal reconciliation control plane gains its production tick caller

Row 8 of the frozen issue #7 acceptance matrix (see
`docs/implementation/issue-7-handoff.md`) failed on reachable production
composition: `Container.sweep_goal_leases` and `Container.reconcile_goals`
(M3 #806) had no production caller — every prior sweep of `git grep` found
tests and the vulture whitelist only. The repair is pure composition on the
existing operator cadence (ADR-019): hive's `canonical_recovery` loop now
ticks both halves beside the three existing recovery halves, so a lapsed Goal
claim's fence is released in production and the Goal is marked due for the
bounded reconciliation sweep. No new scheduler, store, or execution authority;
the reconciliation half stays a safe no-op until a #805 policy is composed.

Three tests join `test_canonical_recovery_cadence.py`, all driving a real
SQLite Container through the production engine lookup the cadence uses:

1. `test_cadence_reclaims_a_lapsed_goal_claim` — the cadence tick releases a
   dead holder's claim row and wakes the Goal (`awake_after` set). It asserts
   the sweep's own observable effects (`reconciliation_view()["claim"]` /
   `["awake_after"]`), not takeover-ability, because
   `GoalReconciliationStore.claim` treats a lapsed claim as claimable anyway —
   the first draft of this test passed for exactly that wrong reason and was
   rewritten. Red against the pre-repair cadence (2 failed, 1 passed).
2. `test_cadence_reconciliation_tick_decides_a_due_goal_under_a_composed_policy`
   — with a minimal #805 stand-in policy composed onto the production
   Container, the cadence repairs a missed wake into exactly one fenced
   admission and the next pass finds the Goal asleep (idempotent). Red
   against the pre-repair cadence (`admissions_total 0 == 1`).
3. `test_cadence_reconciliation_without_a_policy_decides_nothing` — the
   negative control: a production Container ships no invented decision
   semantics; the tick is a safe no-op over the durable facts.

Focused suites: cadence 13 passed, JIT 41 passed, retire pin 1 passed (55
total). `ruff check` / `ruff format --check` clean on both touched files.
This is a bounded composition repair; milestone #7 acceptance accounting is
otherwise unchanged (rows 18/2/3/5/17 remain unmet/unverified — see the
Round 11 section of the handoff doc).
