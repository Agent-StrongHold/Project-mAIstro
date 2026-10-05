---
inventory-delta:
  packages/maistro-core/tests: +58
---

# Tests for the Codex review fixes on #1362

`+58` is the net movement for `packages/maistro-core/tests` across this
branch's Codex-fix commits — additions minus the one test that was replaced.
(It has grown as review rounds landed; the number in the front matter is the
one to trust, and this sentence is kept equal to it on purpose, because a
note whose prose and front matter disagree is worse than one with neither.)
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


## The process default context (+4)

`capabilities/test_effect_context_policy.py`, class
`TestNestedContainersHandTheDefaultBack`. Containers nest, so the published
default has to be a stack rather than one slot: closing an inner Container was
clearing the slot outright, leaving the process with no published context and
every later registry-constructed node — the bare `RunConsumer` fallback among
them — resolving Bindings against a fresh empty one while a perfectly usable
Container was still open.

The four cases are the four ways a single slot gets it wrong: closing the
inner restores the outer; closing *out of order* leaves the rest in place;
the last release falls back to one shared ephemeral context rather than
`None`; and re-publishing moves a context to the top instead of recording it
twice, so one release cannot leave a stale duplicate answering as the default.

## SQLite usage provenance (+2)

`quota/test_sqlite_usage_log.py`

- `test_canonical_invocation_provenance_survives_a_restart` — `snapshot` wrote
  seven columns and `restore` read the same seven, so every restart discarded
  the invocation identity, provider, billing cycle and reported flag. The test
  also pins that a legacy callback event stays honestly empty rather than
  defaulted.
- `test_an_unreported_call_restores_as_unreported_not_missing` — `False` and
  `None` mean different things here ("called and reported nothing" versus
  "nobody recorded whether it did"), and storing the flag as an INTEGER makes
  that easy to conflate on the way back.

## SQLite unreported-usage projection

`persistence/test_sqlite_quota.py` — three tests, written because the diff
gate scored `sqlite_quota.record_unreported` as entirely uncovered. It was:
`test_pg_quota.py` covers the PostgreSQL tracker's version of the method and
nothing covered the SQLite one, so the branch changed a method whose only
evidence lived in its sibling implementation.

- `test_record_unreported_counts_the_call_without_inventing_tokens` — a
  provider that answered but reported no usage costs a request and zero
  tokens, and the row says `usage_complete: False`. The point is the doubt
  being recorded rather than estimated: an invented estimate makes the
  aggregate agree with itself and disagree with the bill.
- `test_record_unreported_accumulates_beside_reported_usage` — reported and
  unreported calls share one row, and two unreported calls neither grow nor
  lose the 150 tokens a reported call already banked.
- `test_record_unreported_is_committed_not_merely_buffered` — reads back
  through a `rollback()`, so a write still sitting in an open transaction
  disappears. Verified by removing the `commit()`: this test fails and the
  other seventeen pass.

Coverage for `maistro/persistence/sqlite_quota.py` is 98% with this file
alone (one uncovered line, 71).

## Diff-coverage gaps the gate named

`+34` for two files the per-file diff-coverage floor reported, neither of
which had anything testing the lines it measured.

`quota/test_lazy_exports.py` — **+10**. `maistro/quota/__init__.py` exports
lazily so importing config does not drag Invocation accounting in behind it,
and sat at 18.2% line coverage with every export unexercised. The shape
invites one specific bug: a name in `__all__` that `__getattr__` has no branch
for, which imports clean and fails at first use. The suite resolves every
advertised name, pins the two loader branches by identity rather than shape,
and checks that an unknown name raises `AttributeError` rather than the
`KeyError` the dict lookup would otherwise leak — a `KeyError` from attribute
access breaks `hasattr`, `getattr(..., default)` and `from ... import` each in
a different way. The module is now at 100%.

`capabilities/test_durable_approval_validation.py` — **+24**. The store's
existing tests build *valid* approvals; nothing built an invalid one, so every
refusal in `DurableApproval` was unexercised. A validator nothing tests can be
deleted without a test failing, which is the same as not having it. Covered:
each correlation field blank or whitespace (parametrized over
`_IDENTITY_FIELDS`, because a blank one does not narrow a lookup and the row
would answer for a different effect than it authorizes); the three
digest-derivation paths; and both halves of resolution consistency — a
resolved approval naming no actor or no time, and a pending one claiming a
time — for both terminal states, since a denial nobody signed is as
unauditable as an approval nobody signed.

`approval_store.py` rises to 77%; what remains uncovered there is
`PgApprovalStore`, which has no tests on any branch and needs a live server,
and is not in scope for this note.
