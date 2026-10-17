---
inventory-delta:
  packages/maistro-server/tests: +16
  tests/: +19
---

# m2-1095 — live-PostgreSQL leg and unambiguous credential allocation

Two halves of the same issue, both previously verified only against strings.

**Live-PostgreSQL migration leg.** The 036 migration was verified only
against its own SQL text: the contract suite in
`tests/test_legacy_principal_migration.py` proves the plan's shape, but
losslessness and restart-reconcilability are claims about executed
transactions, and no server had run them. `tests/migrations/
test_legacy_principal_ownership_live.py` (3 tests, gated on
`MAISTRO_TEST_DATABASE_URL` and wired into the `postgres` job in `ci.yml`)
seeds a mixed old/new deployment — one `default` row and one `conductor` row
in every surface 036 touches, plus a workspace where `default` joined first
as member and `conductor` later as owner — and asserts the merge is lossless
(owner role wins, earliest `added_at` survives, grants union, strike history
sums) — 3 tests; that a migration SIGKILLed while blocked mid-transaction
rolls back
totally and reconciles to the identical converged state on restart; and that
two `maistro_server.entrypoint.run_migrations()` replicas racing through the
advisory lock both succeed with one `default -> conductor` mapping. Running
it against a real server also exposed two gaps in the existing suites that
the string-level checks could not see, now repaired without changing their
counts: `test_migration_chain.py`'s live-catalog table list did not name
`principal_identity_mappings`, and `test_revision_metadata.py`'s head parser
could not read the merge revision's tuple `down_revision`.

**Credential-collision rejection.** The #1095 comment requirement that one
bearer credential never resolve to more than one principal/role set was
unimplemented: `_build_token_index` was last-write-wins, so
`API_KEYS=["alice:shared","bob:shared"]` authenticated as Bob and a
reordering changed the answer. Entries now fail closed at resolve time when
collided (8 tests in `test_auth.py` covering same secret two principals,
order-independence, user/admin role mismatch on one secret, the
bare-secret-vs-full-entry alias collision, the HTTP wire behavior, and the
harmless duplicate boundary), and the startup gate rejects the configuration
(3 tests in `test_startup.py`). The root mirrors under `tests/api/` carry the
identical 16 beside the 3 live-migration tests.
