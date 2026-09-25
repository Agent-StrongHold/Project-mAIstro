---
inventory-delta:
  packages/hive-conductor/backend/tests: +26
  packages/maistro-core/tests: +0
---

# M2 #1061 canonical username allocation

Twenty-six focused tests (nine from the original change, seventeen from the
diff-coverage repair) cover many case-variant writers across two independent
SQLite state writers, rollback of a claim when the user insert fails, release
of a claim and account as one rollback transaction, the live atomic storage
seam, setup rollback after a post-allocation failure, voice resolution through
the canonical quarantine, historical duplicate quarantine, and a mutation guard
against restoring the old scan-then-random-write registration path. The first
test is intentionally a real multi-writer race rather than a process-local lock
test.

The mutation criterion is executed, not only asserted statically:
`test_scan_then_write_mutation_loses_the_race` runs the same concurrent harness
against a deliberately mutated allocator with the historical read-then-write
shape (barrier forced inside the check-to-write window) and proves the identity
duplicates — the exact failure the atomic seam prevents. Replacing the register
route's `username_registry.create_users` call with the historical
`_username_taken()` scan plus random-id write was also executed by hand during
repair; `test_registration_route_uses_atomic_allocator_not_scan_then_write`
fails under that mutation, and the suite was green again after reverting.

The conftest gains an autouse `_isolate_username_claims` fixture: the claim
index is process-global like the users store, and without per-test isolation an
active claim from one test makes another test's fresh-users setup observe the
name as taken.

## Diff-coverage repair (2026-09-23)

The change's own lines in `routes/auth.py`, `routes/setup.py`,
`services/username_registry.py`, and `maistro/state.py` scored below the
diff-coverage floors (90% lines / 80% branch arcs per file): the refusal and
rollback branches — a durable rival claim landing between the availability
check and the transaction, corrupt or stale durable claims that must fail
closed, backends without the atomic boundaries, memory-mode rollback ownership
checks, and the 409/503 handlers in the register and setup routes — had no
test driving them. Sixteen tests close that gap:

- `test_username_registry.py` +13: durable-window loser, corrupt durable
  claim occupied fail-closed, resolve guards (bad schema, quarantined,
  mismatched, ghosted claim), stale durable claim requiring operator repair,
  legacy-migration skip and quarantine paths, backends missing the atomic
  boundaries, memory-mode write/rollback ownership checks, batch validation.
- `test_registration_policy.py` +4: register 503 on allocation outage, setup
  409 on losing the username race, setup 503 on allocation outage, and the
  setup rollback failure that demands operator reconciliation.

The mutation criterion was additionally executed at runtime against the
DURABLE path (a monkeypatched scan-then-write `_write_batch` racing 32 threads
across two state writers): the second same-username row is refused by the
`kv_store_users_username_unique` SQL index, so the mutated allocator cannot
persist a duplicate identity in durable mode; the in-tree
`test_scan_then_write_mutation_loses_the_race` proves the duplicate identity
the same mutation produces in memory mode.

## Independent verification (2026-09-23, this worktree)

Re-verified from a clean tree at `8a99a1363`, not trusting the claims above:

- Full suites green: hive-conductor `2679 passed, 1 skipped`; core
  `state+persistence 576 passed`; targeted registration/registry/core-claim
  suites `89 passed`.
- Multi-process race, run outside the test suite: 6 spawned OS processes on
  one shared SQLite file, three rounds — each round exactly one winner, one
  `users` row, one `username_claims` row, every loser `UsernameTakenError`.
- Live mutation of `_write_batch` to scan-then-write (reverted byte-identical
  afterwards) fails three tests: `test_allocator_calls_storage_atomic_claim_seam`,
  `test_durable_loser_at_the_atomic_layer_is_refused`, and
  `TestInvitations::test_independent_process_writers_publish_one_username`; the
  `kv_store_users_username_unique` SQL index additionally refuses the duplicated
  row with `IntegrityError`.
- Diff-coverage gate reproduced with CI's own producer commands and
  `--base 8bb344e32`: `ok: every measured file this change touches is at or
  above 90% lines / 80% branch arcs`.
- Gates green: `check-agent-store-writes`, `check-owned-store-access`,
  `check-enumerations-provenance`, `check-doc-links`,
  `check-durable-table-inventory`, `ruff check`, `ruff format --check`.
- Known environmental failure, NOT this change: `packages/maistro-core/tests/
test_container_postgres.py::test_an_unreachable_server_is_an_error_not_a_fallback`
  times out in this WSL environment because connections to `127.0.0.1:1` hang
  (SYN dropped by mirrored networking) instead of raising `ECONNREFUSED`. The
  test, `container.py`, and asyncpg are unchanged by this branch; verified with
  a bare `asyncpg.connect` hang outside the test suite.

## Independent verification (2026-09-24, head 36f81563 + db0c6d590)

Fresh validation of the post-reconciliation head; not trusting earlier notes:

- Full hive suite `2686 passed, 1 skipped`; core `state` suites `114 passed`;
  targeted registry/voice/registration-policy/auth/setup suites `219 passed`.
- The two hive tests CI failed on the stale head `873f1a4f4` (2026-09-20 runs)
  — `TestLostSetupMarkerCannotReopenBootstrap` and
  `test_first_run_provisions_vault_and_persists_seed`, both "409 Username is
  already taken" — pass on this head; no CI run exists yet for `36f81563`.
- Diff-coverage gate math (gate's own `audit`, floors 90/80) applied to the
  seven #1061 surfaces vs base `b41be6b5e^`, with CI's per-package
  `coverage run --branch` producer and the FULL hive suite: all seven at or
  above both floors. A subset-only producer first showed real gaps
  (`auth.py:712,715` 503 handler; `model_store.py` 41.9%) that the full-suite
  producer covers — the earlier subset run was the artifact, not the code.
- Live mutation of `_write_batch` to the historical scan-then-write shape
  fails 7 tests including the 32-thread/2-writer race and the atomic-seam
  spy; reverted byte-identical (`git status` clean).
- Gates green: `ruff check`, `ruff format --check`, `mypy` (713 files),
  `check-durable-table-inventory`, `check-owned-store-access`,
  `check-agent-store-writes`.
- OUTSTANDING (out of this lane's authority): `exact-debt-ledger` fails on
  this head — vulture flags `state.py:817 put_raw_with_unique_claims` and
  `state.py:873 delete_raw_with_unique_claims` as NEW core-public-api-surface
  debt (callers live in `packages/hive-conductor/backend`, outside the
  `packages/*/src` scan). Reproduced locally with the exact CI command. The
  gate requires a separately reviewed vulture-ledger grant; ledger edits are
  prohibited in this implementation lane.

## Independent verification (2026-09-24, head a8e3695ba, post-develop-merge)

Fresh validation after merging develop `60862b6c5` into the lane branch;
not trusting earlier entries:

- Suites green: full hive backend `2693 passed, 1 skipped`; core
  `test_unique_claim_transactions.py` + `test_persisted_store.py`
  `51 passed`; targeted registry/voice-auth/registration-policy
  `102 passed`; registry + registration-policy after mutation restore
  `58 passed`. Full core producer for the coverage run: `10177 passed,
  654 skipped`, with the same pre-existing WSL-environment failure in
  `test_container_postgres.py` documented above (unchanged by this branch).
- Gates: `ruff check` clean, `ruff format --check` clean (2536 files),
  `mypy` clean (713 files), `check-durable-table-inventory`,
  `check-owned-store-access`, `check-agent-store-writes` all green.
- Diff-coverage gate run END TO END for the first time on this lane:
  both CI producers executed locally (`coverage run --branch
  --source=packages/maistro-core/src/maistro -m pytest
  packages/maistro-core/tests`, then `coverage run --append --branch
  --source=packages/hive-conductor/backend -m pytest
  packages/hive-conductor/backend/tests`), `coverage xml`, then
  `check-diff-coverage.py coverage.xml --base origin/develop` → exit 0,
  "every measured file this change touches is at or above 90% lines /
  80% branch arcs".
- Live mutation re-executed on this head, two variants, both reverted
  byte-identical (sha256-verified) with the suite green after restore:
  1. Registry `_write_batch` durable path replaced by get_raw-scan +
     put_raw-upsert writes (the historical shape; `put_raw` is
     `ON CONFLICT DO UPDATE`, so a second writer silently overwrites the
     first's claim). Kills 2 tests semantically:
     `test_allocator_calls_storage_atomic_claim_seam` (atomic seam not
     used) and `test_durable_loser_at_the_atomic_layer_is_refused`
     (DID NOT RAISE UsernameTakenError — the durable conflict decision
     is gone). The 32-thread race test still passes under this mutant
     because the module-level `_LOCK` serializes in-process allocations;
     the durable-layer contract tests are what catch it in-process.
     A first no-fallback variant additionally errored 3 tests
     (AttributeError on the LegacyBackend fake, which has no put_raw).
  2. Register route allocation replaced by `_username_taken()` +
     `stores.users[user_id] = user` (the issue's literal mutation).
     Kills 3 tests: the static route-shape assertion,
     `TestInvitations::test_durable_claim_loses_after_the_in_memory_check_passes`,
     and `TestInvitations::test_allocation_outage_answers_503_with_a_retry_hint`.
- Vulture `exact-debt-ledger` re-characterized on this head: the gate
  still fails (exit 1), but `state.py:817`/`:873` are NO LONGER flagged —
  the scan args (`packages tests`) include `hive-conductor/backend`, so
  the atomic-claim functions have a visible caller and vulture never
  emits them. The remaining failure is repo-wide ledger drift: 285
  distinct files carry NEW identities and every one of them is outside
  this branch's 15-file diff (verified with `comm` against
  `git diff --name-only 60862b6c5..HEAD`); `quality/` is byte-identical
  between base and head. The failure is therefore unattributable to this
  lane and the reviewed-grant handoff stands.

## Independent re-verification (2026-09-25, head a73d45ae6)

Repair-lane re-verification against the four 2026-09-07 findings; code at
this head is byte-identical to `a8e3695ba` (the diff is docs-only), so the
end-to-end diff-coverage pass recorded above carries over:

- Setup retry: `test_failed_first_run_releases_the_claim_so_setup_stays_retryable`
  and `test_settings_failure_releases_accounts_and_username_claims` pass on
  this head; the SettingsPersistenceError / SettingsSecretError /
  RegistrationPolicyError handlers each call `_rollback_setup_accounts`.
- Voice principal: `services/voice_identity.py` resolves through
  `username_registry.resolve` (canonical index); no scan-then-write path
  remains in production code.
- Mutation criterion RE-EXECUTED live on this head, both variants restored
  byte-identical afterwards (sha256 `718c2994…` registry / `422ff447…`
  auth route, tree clean):
  1. Registry `_write_batch` durable path replaced by scan + plain writes:
     8 tests fail, including the 32-thread/2-writer race
     `test_many_case_variants_have_one_winner_on_shared_persistence` (8
     winners instead of 1) and `test_allocator_calls_storage_atomic_claim_seam`.
  2. Register route allocation replaced by `_username_taken()` +
     `stores.users[user_id] = user`: 3 tests fail (route-shape assertion,
     `test_durable_claim_loses_after_the_in_memory_check_passes`,
     `test_allocation_outage_answers_503_with_a_retry_hint`).
  Suite green after restore.
- Suites green on this head: full hive backend `2693 passed, 1 skipped`;
  core `test_unique_claim_transactions.py` + `test_persisted_store.py`
  `51 passed`; combined registry/registration-policy/voice/setup/
  settings-durability `118 passed`.
- Gates green: `ruff check` clean, `ruff format --check` clean (2536
  files), `mypy` clean (713 files), `check-durable-table-inventory`,
  `check-owned-store-access`, `check-agent-store-writes` all ok.
- One transient: in a single combined run under residual load from the
  mutation batches, `TestInvitations::
  test_concurrent_open_registration_claims_username_once` failed once
  (barrier-timeout window); it then passed 5/5 alone and the full file
  passed 3/3, and the same 4-file combination passed on rerun. No code
  change made; noted as a load-sensitive concurrency test.

## Independent verification 2026-09-25 (head `e41ebb2f0`)

Re-derived all nine acceptance criteria from the issue text and re-executed
them on this exact head; working tree was clean before and after (doc-only
append by this record).

- Full suites on this head: hive-conductor backend `2741 passed, 6 skipped`;
  maistro-core `10233 passed, 673 skipped, 1 xfailed`.
- Named acceptance tests re-run individually, all PASSED:
  `test_many_case_variants_have_one_winner_on_shared_persistence` (32
  threads / 2 replicas / shared SQLite → 1 winner, 1 row, 1 claim),
  `test_scan_then_write_mutation_loses_the_race` (executed mutant: 8/8
  winners — harness proves it detects the duplication),
  `test_allocator_calls_storage_atomic_claim_seam`,
  `test_historical_duplicate_is_quarantined_not_winner_selected`,
  `TestPutRawWithUniqueClaims::test_lost_claim_race_refuses_and_writes_no_record`,
  `TestPutRawWithUniqueClaims::test_failed_record_insert_rolls_back_the_claim`,
  `TestInvitations::test_durable_claim_loses_after_the_in_memory_check_passes`.
- Mutation sensitivity of the route-shape assertion independently confirmed
  in memory (no tree edit): real `register` source passes
  `test_registration_route_uses_atomic_allocator_not_scan_then_write`'s
  assertions; the same source with `username_registry.create_users([user])`
  replaced by `_username_taken()` + `stores.users[user_id] = user` fails them.
- Gates re-run on this head: `ruff check .` clean, `ruff format --check .`
  clean (2548 files), `check-suite-inventory` ok for both suites (2747 /
  10907 recorded), `check-vulture-baseline` rc 0, `mypy` clean (713 files).
- Surfaces re-checked in source: register (open + invitation)
  `routes/auth.py` and setup `_provision_first_run` both allocate via
  `username_registry.create_users`; `services/oauth_login.py` creates no
  users (link-only); no rename surface exists (grep: none); the only
  remaining direct `stores.users[...] =` writes are field updates to
  already-claimed accounts (login rehash, permissions).
- Boundary re-checked: `username_claims` is a `JsonStore` index of plain
  dicts (no second User model); claim key is the normalized username from
  the request, not the invitation token; `registration_policy` (#313) is
  untouched by the branch diff.
- PR #1453 body and all 19 branch commits scanned for closure keywords:
  none (`Refs #1061` only). Prior round's push-rejection block is obsolete:
  `origin/auto-1061` already resolves to `e41ebb2f0` (same as PR head) and
  `origin/develop` is an ancestor of this head.

## Independent verification 2026-09-25 (head `d7990f94c`, this round)

Re-derived all nine acceptance criteria from the issue text and re-executed
them at this exact head; tree clean before and after this docs-only append.

- Driver determinstic checks all green (job logs): sync, ruff check, ruff
  format --check, core 51 passed, hive targeted 121 passed, both
  check-suite-inventory runs ok. Verifier re-executed with the same results:
  core claim/persisted-store suites `51 passed`; registry +
  registration-policy + voice-auth + auth-throttle `121 passed`; `ruff check`
  clean; `ruff format --check` clean (2548 files); `check-suite-inventory`
  ok for both suites; `check-agent-store-writes`, `check-owned-store-access`,
  `check-durable-table-inventory` (63 tables) all ok.
- Multi-PROCESS race executed by the verifier outside the test suite: 7 OS
  processes racing 7 case variants of `Alice` through
  `UsernameRegistry.create_users` on one shared SQLite file, 3 rounds — each
  round exactly 1 winner and 6 `UsernameTakenError`; direct `kv_store`
  inspection after every round showed exactly one `users` row and one active
  `username_claims` row whose `user_id` equals the winning process.
- Route-shape mutation sensitivity re-confirmed in memory (no tree edit): the
  shipped register source satisfies
  `test_registration_route_uses_atomic_allocator_not_scan_then_write` and the
  throttle-ordering assertions; the issue's literal mutation
  (`_username_taken()` + `stores.users[user_id] = user`) fails both.
- `check-vulture-baseline` **rc=1 at this head AND at the develop base**
  `2c8022fe` (reproduced in a throwaway worktree: 1451 vs 1447 findings).
  The failure is pre-existing repo-wide ledger drift (identities in files
  this branch never touched; `quality/` is byte-identical base↔head); the
  branch's net contribution is +4 findings (its new pytest fixtures/tests and
  one route-handler line shift), and `core-public-api-surface` is unchanged
  at 103 — the `_vulture_whitelist.py` grant for the atomic seam works.
  CORRECTION to the 2026-09-25 `e41ebb2f0` entry above: its
  "check-vulture-baseline rc 0" claim did not reproduce and cannot be correct
  (the base commit itself fails with an identical ledger). The rc=1 gate
  requires the separately reviewed ledger grant already flagged as
  OUTSTANDING at `a8e3695ba`; it is unattributable to this lane.
- Boundary re-checked at this head: `services/registration_policy.py` is not
  in the branch diff (#313 untouched); `username_claims` is a `JsonStore` of
  plain dicts (no second User model); the claim key is the request's
  normalized username, never the invitation token; no rename surface exists;
  `services/oauth_login.py` links existing accounts only (creates none); the
  only remaining direct `stores.users[...] =` writes are field updates to
  already-claimed accounts (login rehash, permission assignment) — noted:
  `_username_taken` is now a definition-only advisory helper (no production
  caller), intentionally retained and vulture-flagged.
- PR #1453 body ("Refs #1061") and all branch commit messages scanned: no
  fixes/closes/resolves closure keywords. The prior round's push
  non-fast-forward block is driver-scope (this verifier never pushes).

## Independent verification (2026-09-25, head a9d3302e, lane L1061)

Fresh validation at the exact PR head (`a9d3302e1`), not trusting any claim
above. All commands executed in this worktree; tree left clean except this note.

- Driver checks reproduced: `uv sync --locked --extra dev` ok; `ruff check .`
  ok; core state suites 51 passed; hive targeted suites (conftest,
  auth-throttle, registration-policy, username-registry, voice-auth)
  121 passed; both `check-suite-inventory` runs ok (the `e41ebb2f0`
  inventory-delta repair holds).
- Additional gates executed: mypy (713 files, 0 errors); FULL hive backend
  suite 2716 passed / 6 skipped; `check-agent-store-writes`,
  `check-owned-store-access`, `check-durable-table-inventory`,
  `check-doc-links` all rc 0.
- CORRECTION to the 2026-09-25 correction above: `check-vulture-baseline`
  PASSES at this head when invoked exactly as
  `.github/workflows/quality.yml` does —
  `RATCHET_BASE_REV=origin/develop uv run python
  scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → rc 0, "1415 reviewed identities -> 1415
  findings", base `2c8022fe81c4`. The earlier rc=1 reproductions (including
  this lane's own) ran the script with no scope arguments, which scans
  `hive-conductor/backend`, `maistro-canvas/frontend`, `dags/`, `eval/` etc.
  — out of the gate's CI scope. No ledger grant is outstanding for this
  branch in the CI invocation shape.
- Diff-coverage gate reproduced locally with a full-suite producer
  (`coverage run --branch` over `packages/hive-conductor/backend/tests` +
  `packages/maistro-core/tests/state`, 2855 passed) and
  `scripts/check-diff-coverage.py --base 2c8022fe81c4`: "ok: every measured
  file this change touches is at or above 90% lines / 80% branch arcs"
  (tests exempt by declaration; `_vulture_whitelist.py` has no producer).
- Mutation criterion executed independently, outside the tree: the backend
  was copied to /tmp and `_write_batch`'s durable branch was replaced with
  the historical `_username_taken`-style scan plus non-atomic `put_raw`
  upserts. Under that mutation the targeted suites fail 3 tests:
  `test_allocator_calls_storage_atomic_claim_seam`,
  `test_durable_loser_at_the_atomic_layer_is_refused`,
  `test_persistence_without_atomic_claims_refuses_allocation`. Nuance
  recorded: the 32-thread race test itself survived this particular mutant
  because losers die with `RuntimeError` (the mutated upsert path) instead of
  `UsernameTakenError`, leaving one outcome entry; the mutation is caught by
  the seam-spy and window-loser tests, and the in-tree
  `test_scan_then_write_mutation_loses_the_race` demonstrates the duplicate
  identity the same shape produces without a storage constraint. Copy
  deleted; real tree byte-identical (`git status` clean before this note).
- Acceptance re-derived from the issue: atomic durable claim (single SQLite
  txn, primary-key `ON CONFLICT DO NOTHING` claims decide the winner),
  Alice/alice two-writer and two-OS-process races (32 case variants → one
  row/one claim; spawn'd processes → exactly [200, 409]), admin-open,
  invitation, and setup/bootstrap allocation with rollback and
  lost-marker fail-closed retention, login and voice resolution through the
  canonical index only, legacy-duplicate quarantine at `initialize_stores`,
  and crash-safe claim+row atomicity — all observed in this session's runs.
  No rename surface exists and OAuth creates no accounts (links only), so
  those two "where applicable" clauses are vacuously satisfied, re-confirmed
  at this head. Live GitHub CI on draft PR #1453 remains UNVERIFIED from
  here (no CI run is claimed by any artifact in this lane).

## Independent verification (2026-09-26, head ae7dbd3a, lane L1061)

Re-validation at the exact branch head (`ae7dbd3a7`) after the previous
round's evidence was rejected because the worktree had changed underneath
it (docs commits `d7990f94c`/`a9d3302e`/`ae7dbd3a` landed after the
verified head). All commands executed fresh in this worktree at
`ae7dbd3a7`; no code or test file changed in this round.

- Full driver battery reproduced: `ruff check .` ok; `ruff format --check .`
  ok (2548 files); core state suites 51 passed; hive targeted suites
  (registration-policy, username-registry, auth-throttle, voice-auth)
  121 passed; both `check-suite-inventory` runs ok;
  `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` rc 0 (1415 reviewed identities -> 1415
  findings). mypy on `packages/maistro-core/src`: 5 pre-existing
  `maistro_bootstrap` import-stub errors in `maistro/cli/_builders_tui.py`
  and `maistro/cli/_install.py` — files untouched by this branch (checked
  against the branch diff stat); `state.py` itself clean.
- Mutation criterion executed at full strength in this round: backed up
  `services/username_registry.py` (cp), replaced `create_users`' atomic
  block with the literal historical shape — `_username_taken()`-style scan
  of `_legacy_candidates` plus random-id `self._users[user.id] = user`
  writes (no claim, no transaction), with a 50 ms window between check and
  write — ran
  `test_many_case_variants_have_one_winner_on_shared_persistence`, and the
  test FAILED at line 86 (`assert sum(outcomes) == 1`), i.e. the race
  harness itself kills the scan-then-write mutant (unlike the previous
  round's `put_raw`-upsert mutant, which only the seam-spy tests caught).
  Restored via cp; `git diff` on the file empty; suite green again
  (username-registry 20 passed); tree clean.
- Allocator coverage re-derived: the only production `HiveUser(`
  construction outside tests is `routes/auth.py:716` (register →
  `create_users`); setup builds via `stores.users._model_class` → the same
  allocator (`routes/setup.py:353`); remaining `stores.users[...] =`
  writes are login password rehash and permission assignment, neither of
  which creates or renames an identity.
- No repair was needed this round: the sole prior validation failure
  (`check-5.log`, unparseable `inventory-delta` in
  `m2-1061-throttle-ordering-assertion-repair.md`) was already fixed by
  `e41ebb2f0` and the gate passes at this head. The only edit in this
  commit is this note; every code/test surface above was verified exactly
  as committed at `ae7dbd3a7`.
