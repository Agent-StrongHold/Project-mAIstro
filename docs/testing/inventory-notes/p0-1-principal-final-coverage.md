---
inventory-delta:
  packages/maistro-canvas/tests: +3
  packages/maistro-server/tests: +1
---
# p0-1-principal-final-coverage

## What moved and why

- **canvas +3** — foreign-org guard tests on delete / latest / export
  (`test_{delete,latest_composite,export}_rejects_foreign_org_canvas_even_if_store_leaks`
  in `test_routes_org_paths.py`). They exist because the `CurrentUser` →
  `Principal` migration touched `maistro_canvas/auth.py` and the three canvas
  routes; the diff-coverage gate required the guarded branches to be exercised.
- **server +1** — `test_auth_off_admits_a_dev_principal` in `test_auth.py`:
  the auth-off sentinel path of `resolve_token_principal` (empty `api_keys` +
  `admin_api_keys` → dev principal) was reachable production behavior with no
  test; the migration made `Principal` the carrier, so the path is now pinned.
- Compensating edits, not count moves: `verify_api_key` assertions were
  rewritten off the burned `.token` attribute onto `user_id`, and the removed
  `principal.user_id != principal.token` assertion died with the attribute.

## Local gate reproduction (2026-11-16 verification round, head 64677f012a4d)

- `scripts/check-principal-identity.py` with CI's exact env
  (`RATCHET_BASE_REV=origin/develop`): ok — 4 tolerated → 0 current, none new.
- Diff-coverage gate reproduced locally: branch-coverage runs of the server
  (658 passed), canvas (584 passed), hive (4147 passed), privilege/fitness
  core selections, and the four root script tests under the changed
  `scripts/`, then `scripts/check-diff-coverage.py` vs base `f8a2df966a1d`:
  ok — all 17 changed measured files ≥90% lines / ≥80% branch arcs.
- Mutation gate: `mutation_critical.py --validate` ok (8 critical sources);
  target resolution reproduces the sole target
  `maistro/privilege.py` → `packages/maistro-core/tests`. The trusted merge
  base baseline has no entry for it, so per `mutation_pr_gate.py` the run is
  report-only and cannot fail the PR.

The aggregate 87% publish-set floor itself needs CI's full multi-producer
combine and was not reproduced locally; the branch deletes ~11k lines net, so
the risk direction is downward in denominator, not coverage.

## Second verification round (2026-11-16, head 03a40f495fa9 = develop f8a2df966 merged)

Issue test plan re-executed against the merged head:

- `scripts/check-principal-identity.py`: ok — 4 tolerated → 0 current, none new.
- `pytest packages/maistro-core/tests/fitness/test_principal_identity.py`
  `packages/maistro-server/tests/api/test_auth.py`: 39 passed.
- `pytest packages/hive-conductor/backend/tests/test_username_registry.py`:
  24 passed.

Driver check battery found one intermittent failure:
`test_concurrent_open_registration_claims_username_once`
(`test_registration_policy.py`) asserted 7×409 but observed 2×429 among the
eight simultaneous registrations. Diagnosis: the test's fresh
`AuthThrottle(_STRICTER.register)` kept production budgets
(per_client=5, per_account=3) that are *below* the contender count, and every
409 loser records a throttle failure (`routes/auth.py`); under machine load the
eight `check()` calls stagger, a late arrival reads a filled budget, and the
route lawfully answers 429. The test body was byte-identical on the develop
base, and the suite passed on re-run and in isolation — a pre-existing timing
flake, not a regression of this branch.

Repair (no collected count moved): the fresh throttle is now built with
`AuthLimits(per_client=8, per_account=8, global_failures=8)` — at most seven
failures can be recorded, so no scope can refuse, and the outcome depends on
the username-claim critical section alone. The route's real check/record path
stays exercised; the assertion set (1×200 / 7×409 / one row / one username) is
unchanged. Verified 5/5 passes under a 12-process CPU load on 20 cores, where
request runtimes stretched 2.1s → 5.8s — the staggered-arrival shape that
produced the 429s. Full hive battery re-run: 199 passed; suite inventory: ok.
