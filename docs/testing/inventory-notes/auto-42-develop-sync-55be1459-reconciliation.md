---
inventory-delta:
  packages/maistro-core/tests: +15
  tests/: -2
---

# auto-42 develop sync of 55be1459 — reconciliation of the two #1194 implementations

Merging origin/develop (`55be1459b`, carrying #1319's independent #1194
implementation and #1449's durable elevation grants) into the #42 branch
collided two executable replay contracts in the same files. The resolution
keeps this branch's contract as canonical and adopts develop's orthogonal
work; this note records the measured suite movement of that reconciliation.

## What the resolution kept from each side

- **Canonical (this branch):** `Invocation.effect_scope` + `effect_key` with
  the `effect_identity` claim; the active-effect partial unique index that
  covers **every non-FAILED status including `completed`** (closing the
  check-then-insert window develop's status-set left open); the fail-closed
  `Node.logical_effect_key() -> str | None` contract; the migration chain
  rooted at `034_canonical_run_effect_claim` → `035_capability_invocations`.
- **Adopted from develop:** the durable replay-refusal gate
  (`_replay_refused` — an interrupted NON_RETRYABLE attempt is never
  re-executed; the fresh recovery Attempt records the refusal as its own
  evidence) with its conformance tests; the production
  `agent.remote_work` NON_RETRYABLE catalog pin; the in-memory
  `find_run_by_effect` read half; the A2A
  `GET /tasks/by-idempotency-key/{key}` reconciliation endpoint plus its
  tests; #1449's `046_durable_elevation_grants` (re-parented onto `044`,
  the branch chain's tip — only the parent changed, the DDL is untouched)
  with `elevation_durable.py` and its suite; M2-A7's health/main server
  work; and `test_idempotent_replay_conformance.py`, whose registry sweep
  is model-agnostic.
- **Dropped from develop (competing mechanism):** the `logical_effect`
  boolean discriminator with its second partial unique index
  (`uq_capability_invocation_active_logical_effect`), the
  `replay_effect_key()`-in-`NodeResult.metadata` recording, and the
  duplicate migrations `041_canonical_run_effect_claim` (byte-identical DDL
  to the branch's `034` — keeping both would re-apply the effect claim),
  `043_capability_invocation_effect_index`, and
  `045_capability_invocation_logical_effect`, plus the tests that emulate
  only those shapes. Develop's `test_migration_chain.py` reapplication test
  was rewritten for the surviving chain (stamp to `039_quota…`, re-upgrade
  walks `044` + `046`; asserts the scope-keyed claim index, the guarded
  `elevation_grants` table, and that a pre-existing Invocation row survives
  with its `effect_scope` intact) and passes against live PostgreSQL.

## Where the numbers come from

- `packages/maistro-core/tests: +15` — develop's surviving core additions
  (idempotency conformance sweep, unbound-key and refusal conformance,
  remote-work catalog pin, runs-store read-half cases, spawn-harness and
  delegate child-run cases that are contract-agnostic), minus the
  model-bound develop tests the resolution replaced with the branch's own.
- `tests/: -2` — `tests/migrations/test_capability_invocation_effect_index_migration.py`
  asserted only the dropped 043 index realignment; the chain-level
  reapplication test in `test_migration_chain.py` now carries the equivalent
  live-catalog coverage.
