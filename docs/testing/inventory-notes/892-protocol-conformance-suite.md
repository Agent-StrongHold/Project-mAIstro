---
inventory-delta:
  packages/maistro-core/tests: +72
---

# #892 generalized protocol conformance suites (M8-A12 prototype)

Bounded research prototype: the archive tier's shared conformance-suite
pattern, generalized into a contract/leg split and run unchanged against
the three production implementations of two capability-tier protocols.

New files, all under `packages/maistro-core/tests/conformance/`:

- `_invocation_contract.py` -- 12 implementation-agnostic behavior checks
  for the capability `InvocationStore` / `EffectClaimStore` protocols
  (round-trip fidelity, absence semantics, optimistic concurrency,
  admission refusal beside live/completed priors, FAILED-prior-only
  retries, history scope/span/order and tiebreak, ambiguity staleness
  predicate, atomic-claim replay/refuse/admit).
- `_approval_contract.py` -- 7 checks for the durable `ApprovalStore`
  protocol (pending round-trip with digest binding, explicit absence,
  effect-identity idempotence, duplicate-id refusal, verified actor,
  first-decision-wins, restart durability).
- `_legs.py` -- build/restart/close for each backend (in-memory, real
  aiosqlite, real asyncpg against `MAISTRO_TEST_DATABASE_URL` with the
  honest-skip discipline; namespace isolation, no truncation).
- `test_invocation_store_conformance.py` /
  `test_approval_store_conformance.py` -- the check x backend matrices (65
  run + 7 protocol-gated skips with a live PG URL) plus per-leg structure
  guards; every recorded divergence is a finding-numbered xfail
  (`strict=True` except the possibly-deliberate F3).
- `test_conformance_teeth.py` -- 8 strictness proofs: seven single-behavior
  drifts each flag exactly their check, and an honest in-memory leg
  violates exactly the recorded findings.

Net: +72 collected node IDs on `packages/maistro-core/tests`. Experiment
record, six cross-implementation findings (F1-F6), and INCUBATE disposition:
`docs/testing/conformance-suite-evidence.md`.

## Post-merge repair (auto-892, develop sync to 34795962)

`inventory-delta:` none — collected node count unchanged (72; scan total
29494 matches `docs/testing/inventory/baseline.json`).

The develop sync (merge 6e582553, bringing #1326's M1-B2 Invocation-seam
rework) silently broke the prototype: `Invocation.logical_effect` was
retired for the explicit `effect_scope` + `bind_logical_effect_scope`
seam, so `claim_replays_a_completed_prior` died with a pydantic
`extra_forbidden` ValidationError — caught by the honest-leg teeth test,
which is exactly the regression-guard role that test claims.

- `_invocation_contract.py`: migrated the #1194 cross-NodeRun replay
  scenario onto the new seam (`effect_scope=<stable key>` on the canonical
  row and the retry), matching the pinned claim tests' convention. Teeth
  still bite: `test_the_suite_flags_a_claim_that_never_replays` passes via
  `_AmnesiacClaim`.
- Marker retirements (the suite retiring its own findings, as designed):
  F4 — the merged SQLite claim now keys its history read on
  `effect_scope or node_run_id` (verified in-process); F1 — the merged
  `PgInvocationStore.create` refuses beside any prior via the effect-wide
  `_find_effect` lookup (verified against a real PostgreSQL 18 server via
  `MAISTRO_TEST_DATABASE_URL`). Remaining live findings: F3 (non-strict),
  F6 (strict), F2/F5 (recorded, portable-refusal). Evidence record updated:
  `docs/testing/conformance-suite-evidence.md`.
- Full matrix on this tree: without a PG URL 50 passed / 20 PG-leg skips /
  2 xfailed; with one, 67 passed / 3 claim-protocol skips / 2 xfailed.
