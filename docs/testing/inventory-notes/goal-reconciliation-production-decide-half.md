---
inventory-delta:
  packages/maistro-core/tests: +16
---

# Production #805 Goal-reconciliation decide-half composed in create_container

`packages/maistro-core/tests/goals/test_goal_reconciliation_production.py` is
new: 16 node IDs pinning the production composition of the Goal
reconciliation decide-half (issue #7 row 8, #805/#806).

- The policy's deterministic answers: an unblocking wake progresses under the
  wake's correlation id; a replayed wake yields the same decision key while a
  genuinely new wake replans under a new one; pursuit work in flight waits
  wake-driven (no sweep horizon, no cost); an open admission never stacks a
  second one; an exhausted budget gates with a reason; a terminal posture is
  never re-decided; a never-notified Goal is discovered under one stable key.
- The physical admitter: an admission is fulfilled as one canonical QUEUED
  Run bound to `goal_id`/`goal_revision` through `admit_direct_work`, with
  goal-context provenance and the accountable Agent as both delegate target
  and acting identity; unknown canonical Goals, revisions missing from the
  chain, and non-run admission kinds refuse loudly; two pursuit Runs across
  a revision bump each keep their own revision's language; the
  `goal_reconciliation` admission source is pinned consumable so the
  consumer tick owns every pursuit Run (#251).
- The composed Container, end to end over SQLite: `reconcile_goals()`
  discovers a durable Goal into one canonical QUEUED Run (parked wake-driven
  on the second tick), `execute_admitted_runs_accounting()` claims and drives
  it leaving real NodeRun/Attempt rows, and a revision bump plus a durable
  wake replans into a second Run bound to the new revision and its language.

No existing test was removed. Two node IDs in
`test_goal_container_wiring.py` were renamed to the new contract
(`test_container_composes_the_production_decide_half` and the explicit
hand-built-Container no-policy test) — count-neutral, verified by the
unchanged collected total minus this file. The hive-side
`test_canonical_recovery_cadence.py` renames land in that suite's own count,
which stayed equal (2 rewritten, net 0).
