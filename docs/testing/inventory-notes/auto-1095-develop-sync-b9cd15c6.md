---
inventory-delta:
  tests/: 0
---

# auto-1095-develop-sync-b9cd15c6

Resolving the preserved `origin/develop` (b9cd15c60) sync conflict on
`auto-1095` renumbered develop's newest migration past the branch chain and
fixed a pre-existing crash in 064 on pre-M2 installed bases. No test counts
move.

## Develop sync resolution: delegation grants renumber 067 -> 068

develop's chain at b9cd15c60 is `063 goals -> 064 personas -> 065 replay
cursors -> 066 receipts -> 067 delegation_grants (#845)`. The branch chain is
`063 goals -> 064 legacy_principal (#1095) -> 065 personas -> 066 cursors ->
067 receipts` (established by the earlier syncs recorded in
`auto-1095-develop-sync.md`), so the incoming `067_delegation_grants` collided
with the landed `067_durable_delivery_receipts` — the raw merge produced two
revisions numbered `067`, both parented on `066`. Per the convention this
branch and develop itself already applied (`78154170f`, and develop's own
`9854033c7` "renumber delegation_grants migration past develop's 066 as 067";
"a landed trunk migration never moves, so later revisions renumber past it"),
the newcomer renumbers:

- `alembic/versions/068_delegation_grants.py`: `revision = "068"`,
  `down_revision = "067"`, with the renumber provenance in the docstring.
- `tests/migrations/test_capability_invocation_effect_index_migration.py`:
  head assertion `["068"]`, `068 -> 067` lineage assertion, merged narrative.
- `tests/migrations/test_goal_installed_base_upgrade.py`:
  `CHAIN_HEAD = "068"`, `068 -> 067` lineage assertion, `068_delegation_grants.py`
  filename assertion, merged narrative.
- `tests/migrations/test_legacy_principal_ownership_live.py`: the fixture's
  chain-tip pin `{"067"}` -> `{"068"}` (caught by the live PostgreSQL run, not
  by the offline suite — recorded because it is exactly the kind of pin a
  comment-only merge misses).
- `tests/migrations/test_migration_chain.py` and
  `quality/durable-table-retention.json`: the delegation row's prose mentions
  the creating revision; updated `067` -> `068` for accuracy (no gate input).
- `Dockerfile` / `quality/image-pins.json`: comment/provenance-only conflicts
  over the identical `golang:1.27.3-alpine@sha256:b8c9b82a…` pin; both sides'
  provenance sentences kept, develop's wording for the shared comment.

Evidence: `alembic` ScriptDirectory resolves exactly one head `068`;
`scripts/check-image-pins.py` and `scripts/check-durable-table-inventory.py`
exit 0; `scripts/check-suite-inventory.py` reports 21 suites matching.

## 064 forward-upgrade crash on pre-M2 installed bases (pre-existing, fixed)

Running the DB-gated installed-base suite against real PostgreSQL surfaced a
failure independent of this sync: `064_legacy_principal_ownership` executed
`UPDATE audit_log … WHERE signature = ''`, but the `signature` column was
folded into 005 by the M2 security-cage work (d32ddff76), so an installed base
built by any landed chain older than that (the HITL-era 061 snapshot
`66f3cea9`, the user-model `c560d4cc` and planner `4675101` snapshots the
suite reconstructs) has no such column and the legally-owed forward upgrade
died with `UndefinedColumn` at 064. Reproduced identically at the pre-merge
head `4b1284897` in a throwaway worktree before touching anything — the sync
did not introduce it; the fresh-chain path (new 005) masks it.

Fix: 064 probes `information_schema.columns` (guarded, in the chain's
re-adoption style) and only applies the proof-preservation exception where the
column exists; a base without proof columns has no signed rows by
construction, so every `default` row follows the identity there.

Evidence: `tests/migrations/test_goal_installed_base_upgrade.py` went from
5 failed / 3 passed to 8 passed against
`MAISTRO_TEST_DATABASE_URL=postgresql://…@127.0.0.1:5595/maistro`
(pgvector/pgvector:pg18); the live suite
(`test_legacy_principal_ownership_live.py`, 3 tests: mixed-data lossless
merge, SIGKILL restart reconciliation, two-replica entrypoint convergence),
`test_migration_chain.py`, `test_durable_delivery_receipts_downgrade.py`,
`test_event_schema_agreement.py`, `test_capability_invocation_effect_index_migration.py`,
`test_revision_metadata.py`, `test_single_migration_head.py` — 35 passed;
`tests/test_legacy_principal_migration.py` and all of
`packages/maistro-server/tests/api` (613 passed, 7 skipped) green; ruff check
and format clean.
