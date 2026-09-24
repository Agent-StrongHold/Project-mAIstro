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
