---
inventory-delta:
  added: []
  removed: []
  modified:
    - tests/migrations/test_migration_chain.py::empty_database
  rationale: >
    Fixture repair for a reproduced shared-DB ordering failure; no net test
    count change (11 tests before and after), so no new coverage is claimed.
    The fixture now drops every table in `public` at setup and teardown
    instead of only `alembic downgrade base`, because standalone-path stores
    (`pg_strikes._SCHEMA` and siblings) create chain-owned tables with
    `CREATE TABLE IF NOT EXISTS` outside the chain and one suite poisoned the
    next ("relation security_strikes already exists" in migration 005).
---

# auto-72 verifier repair 4 — migration-chain fixture is order-independent

## Vulture gate reconciliation (prior finding resolved, no ledger edit)

Prior finding claimed `scripts/check-vulture-baseline.py` exits 1 at head
0baf1eb and would fail CI. Actual evidence this round:

- Both enforcing CI invocations
  (`.github/workflows/quality.yml` and `vulture-ratchet.yml`) pass the
  narrow scan `packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  — verified exit 0 at 0baf1eb (throwaway worktree
  `~/Git/worktrees/auto-72-vul-check`) and at the post-sync head.
- The exit-1 shape comes from the no-arg default scan (`packages tests`,
  including `hive-conductor/backend/`), which only `scripts/run-quality-scans.sh`
  uses; no workflow references that script and its vulture step is explicitly
  advisory (WARN, non-failing).
- The ledger's last mutation (f0792d935, RouterEngine dead quota_tracker,
  #1632) came from develop itself; once the develop sync (merge 75d9f293f)
  reconciled the divergent src, the enforcing gate matches 1403↔1403 with no
  unbanked/prune deltas.
- Per the repair discipline (address actual evidence, not guessed scanner
  findings), `quality/vulture-baseline.json` is left untouched: the enforcing
  gate is green, so amending it would churn reviewed grants for an
  advisory-only invocation.

## Evidence

Reproduced against a live pgvector:pg18 (`auto-72-pg`, db `maistro`) at head
0baf1eb226074110a178deca2090c2f536264d87 before the fix:

1. `drop schema public cascade; create schema public` (pristine)
2. `uv run pytest tests/migrations/test_migration_chain.py -q` → 11 passed
   (teardown leaves `alembic_version` at base)
3. `uv run pytest packages/maistro-core/tests/security/test_strike_tracker_conformance.py -q`
   → 40 passed (standalone `db_url` path raw-DDLs `security_strikes`,
   `security_violations`, `security_rate_limits`)
4. `uv run pytest tests/migrations/test_migration_chain.py -x -q` → **FAILED**
   `test_upgrade_head_succeeds_on_an_empty_database` (returncode 1 in 005,
   create_table security_strikes)

After the fixture repair, the same sequence passes:

- step 4 rerun on the poisoned DB: 11 passed
- strikes → migrations again: 40 passed + 11 passed
- migrations teardown now leaves zero tables; the strike suite recreates its
  own tables on connect (40 passed immediately after a migrations teardown)

## Why drop-all is safe

- Chain tables were already destroyed by `downgrade base`; the fixture only
  stops pretending runtime-created tables are not there.
- Runtime stores bootstrap with `CREATE TABLE IF NOT EXISTS` on connect, so
  nothing that runs later on the shared DB is stranded.
- Identifiers are quoted catalog values; drops are `IF EXISTS ... CASCADE`.
