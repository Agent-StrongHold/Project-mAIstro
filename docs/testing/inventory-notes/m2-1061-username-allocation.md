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
