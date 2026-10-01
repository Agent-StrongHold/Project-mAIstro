---
inventory-delta:
  packages/maistro-core/tests: +15
---

# Tests for the Codex review fixes on #1362

`+14` is the net movement for `packages/maistro-core/tests` across this
branch's Codex-fix commits — additions minus the one test that was replaced.
The additions are listed below by what they pin rather than by file
arithmetic; each fails against the commit it was written for, which I checked
by reverting the fix and re-running.

## Quota admission

`quota/test_invocation_quota_boundary.py`

- `test_an_unconfigured_door_admits_rather_than_refusing_everything` —
  `create_container` registers no budget and the migration creates the table
  empty, so refusing with "missing applicable quota policy" meant every
  durable deployment lost *all* effect execution the moment it upgraded.
- `test_a_policy_that_covers_nothing_applicable_still_denies` — the other
  half of that distinction. A populated registry whose budgets exclude this
  call is a policy gap, not an opt-out, and is still refused before any
  physical dispatch. It registers a real in-period budget scoped to a
  different provider, so the "populated but uncovered" path is exercised
  rather than assumed.

These two **replace** `test_absent_policy_denies_before_physical_dispatch_and_records_refusal`,
which pinned the behaviour being corrected. That replacement is the one
removal inside the net above.

`quota/test_pg_invocation_quota_boundary.py`

- `test_pg_admission_subtracts_opening_spend_like_sqlite` — a budget with
  limit 100 and opening spend 90 reported 100 units available and admitted a
  20-unit request against the 10 that remained. Runs against a real
  PostgreSQL; skips without `MAISTRO_TEST_PG_DSN`.
- `test_pg_restores_the_hold_when_completion_retracts_a_release` — newer
  evidence saying the call *did* happen must not leave it free. A
  `not_applied` observation zeroes the allocation; a later higher-revision
  `completed` with no usage was keeping those zeros, settling a real but
  unmeasured provider call as consuming no quota. SQLite always restored
  `held=maximum` here; PostgreSQL did not.

`persistence/test_sqlite_quota.py`

- `test_evidence_and_its_aggregate_commit_together` — the evidence row *is*
  the idempotency key, so committing it before projecting left a window where
  a crash understated `quota_usage` permanently: the retry's `ON CONFLICT DO
  NOTHING` skips the projection too. The test interrupts the projection,
  asserts nothing committed, **and** asserts the retry records both. That
  second assertion is what caught a missing explicit rollback — grouping the
  statements was not sufficient, because aiosqlite reuses one connection and
  an uncommitted evidence row is still visible to it.

## The container's estimate resolver

`test_container_capability_effects.py`

`TestTheInputEstimateIsACeiling` — dense CJK is not divided by four, every
message is counted with its framing, and an empty request still reserves
something. `QuotaEstimate.maximum` is what admission *holds*, and
`len(text) // 4` is the average English characters-per-token: neither a bound
nor inclusive of chat framing.

`TestTheCostCeilingMakesMicroUsdBudgetsUsable` — a priced model yields a
bound, the bound rounds *up* rather than to zero, and an unpriced model stays
`None`. Before this the resolver never populated `micro_usd`, so registering
one applicable money budget denied every governed invocation.

## The harness dispatch rollout

`graph/nodes/test_agent_spawn_harness.py`

- `test_a_dispatch_recorded_under_the_pre_1319_key_is_not_repeated` — #1319
  changed this node's effect key, so a deployment upgrading after the adapter
  dispatched and before the node persisted its pause would send the external
  harness a second task it was already working on. The test dispatches under
  the old key and then runs the node: one task reaches the harness, and the
  pause carries the original invocation id.
