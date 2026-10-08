---
inventory-delta:
  tests/: +2
---

# auto-42 round 24 — rewrite the stale 043 conformance test for the surviving 035 chain

Verifier-repair round at head 6f4d79334. One CI `test`-job failure
(`uv run pytest tests/ --ignore=tests/tools/registry`):
`tests/migrations/test_capability_invocation_effect_index_migration.py`
failed + errored with `alembic.util.exc.CommandError: Can't locate revision
identified by '043'`, and `check-suite-inventory.py --suite tests/` drifted
(net +2 node IDs: expected 4539, collected 4541). Both have one root cause.

## What failed and why

The 55be1459 develop-sync resolution
(`auto-42-develop-sync-55be1459-reconciliation.md`) recorded `tests/: -2` for
dropping `tests/migrations/test_capability_invocation_effect_index_migration.py`
— "asserted only the dropped 043 index realignment". But the merge that landed
that resolution (6f4d79334) never actually removed the file: it is still in the
tree, still importing `alembic/versions/043_capability_invocation_effect_index.py`
(deleted by the resolution) and calling `directory.get_revision("043")`. So the
two node IDs the ledger wrote off are still collected — the +2 drift — and one
of them fails against the deleted revision — the CI failure. The recorded
reconciliation was only half-executed; the ledger and the tree disagreed.

## The repair

Rewrote the file instead of deleting it (same two-test count, so this note's
`tests/: +2` puts the ledger back in agreement with collection by adding back
exactly the two IDs the earlier note wrote off):

- `test_effect_claim_revision_follows_the_chain_tip` — single head `053`; the
  folded claim chain (`034_canonical_run_effect_claim` → `034` → `035`) and
  every chronicle revision (`039_quota_usage_event_identity`, `044`,
  `046`–`053`) on the walked path; the superseded `043`/`045` ids asserted
  absent, so resurrecting either fails loudly instead of silently forking.
- `test_migration_and_the_durable_stores_describe_one_claim_schema` — drives
  revision `035`'s `upgrade()`/`downgrade()` through an `op` stub and asserts
  the surviving schema truth: the `effect_scope` column (server-defaulted
  empty, then backfilled), the lookup index keeping `node_run_id` (043's
  reshape was superseded — the stores never dropped it), and the scope-keyed
  claim-index replacement trio. It then extracts both durable stores' `_CLAIM_DDL`
  / `_SCHEMA` (SQLite + PostgreSQL) via the AST and asserts the migration's
  executed statements and index columns match them exactly — the offline guard
  for "identical on SQLite, PostgreSQL, and runtime DDL", previously only
  proven against a live server by `test_migration_chain.py`.

## Mutation evidence (each named regression turns the test red)

1. Claim index re-keyed to `(run_id, node_run_id, …)` in 035 →
   `test_migration_and_the_durable_stores_describe_one_claim_schema` FAILED;
   restored byte-identical (`git diff` empty).
2. SQLite `_CLAIM_DDL` predicate losing `'completed'` → same test FAILED
   (store/migration drift detected); restored byte-identical.
3. A resurrected `043` revision on disk →
   `test_effect_claim_revision_follows_the_chain_tip` FAILED (plus
   `test_single_migration_head.py`'s head checks); file removed.

## Validation at this head

- `uv run pytest tests/migrations/...` (rewritten file): 2 passed.
- Fresh pg18 container (`pgvector/pgvector:pg18`, port 25455):
  `alembic upgrade head` → single head `053`; live
  `uq_capability_invocation_active_effect` is the scope-keyed shape;
  `test_migration_chain.py` + `test_event_schema_agreement.py` + rewritten
  file: 20 passed.
- CI `test` job command: `uv run pytest tests/ --ignore=tests/tools/registry -q`
  → 4375 passed, 90 skipped (was 1 failed, 1 error).
- `ruff check .` / `ruff format --check .`: clean.
