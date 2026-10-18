---
inventory-delta:
  packages/hive-conductor/backend/tests: 0
  packages/hive-conductor/tests/e2e: 0
  packages/maistro-core/tests: 0
---

# Issue #358 repair — job cc5fea2 (integration-scope)

## Frozen scope

Branch `auto-358`, starting head `f6da3ed082946d0e3d30de6a5e6c30b97a409d8c`,
supplied base `91996e19223db61bab49ce2e8a8d5b8f6eb2728e` (merge base with
origin/develop: `2a24c8a82dc0`). Starting worktree clean. Repairs address the
named `integration-scope` gate failure and the exact-debt-ledger instruction;
no unrelated changes.

## Finding 1 (the real integration-scope breaker): duplicate Alembic revision id

`051_audit_cursor_indexes.py` (this branch, #358) declared `revision = "051"`,
`down_revision = "050"` — the same id develop's `051_canonical_run_eval_scores`
took in the meantime. The graph had two heads; `alembic upgrade head` failed
with "Requested revision 052 overlaps with other requested revisions 051" /
"Revision 051 is present more than once", so **both** `postgres (pg17)` and
`postgres (pg18)` required producers failed and `integration-scope` aggregated
the failure. The repo's own guard caught it deterministically:
`tests/migrations/test_single_migration_head.py` — 3 failed before the repair.

Repair: renumber to `053_audit_cursor_indexes.py` (`revision = "053"`,
`down_revision = "052"`). No test or doc pins the audit migration's id; the
index names (`ix_audit_page_*`) are unchanged.

## Finding 2: the supplied check-3 e2e failure is environmental

check-3 ran the PM-workflow e2e against the shared stack on `127.0.0.1:8101`
(`maistro-hive-conductor`, image created 2026-07-01 — pre-#358 develop code).
The failing response was a **bare JSON array of the whole corpus** with
`limit=1` — a shape no code path on this branch can produce (the branch route
returns `{"entries": [...], "next_cursor": ...}` or 403). Proof by contrast:
CI's exact harness (`docker compose -f docker-compose.test.yml --profile test
up --build --exit-code-from api-tests api-tests`) built from this worktree —
`TestAuditTrail::test_audit_log_has_entries` **passed** (10 passed, 13
skipped), as did the UI harness (`e2e-tests`: **125 passed**). The stale shared
container was not modified.

## Finding 3: exact-debt-ledger — blocked by the two-merge rule, not by banking

`uv run python scripts/check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'` reports 4 NEW identities
(`AuditLog.get_page` in `pg_audit.py:49`, `sqlite_audit.py:96`,
`protocols/memory.py:427`, `sentinel/audit.py:42`). They are already banked in
the candidate ledger beside the identical, maintainer-banked `get_entries`
rows; the failure is trusted-base authorization (no grant at merge base
`2a24c8a82`, none on origin/develop either — 61 vulture grants, none for
`get_page`). An experiment adding `read_page` to `persistence/audit_pages.py`
so the scan would see an in-scope caller was **reverted**: within
`packages/*/src` no production code reads the Sentinel audit log (writers
only), so the seam merely converted 4 reviewed identities into 1 new
unbankable one. Resolution requires the grant to land on develop first (the
gate's own two-merge rule); no push was performed.

## Repair 4: boundary-conformance scoped case

`test_store_boundary_scope_conformance.py::test_the_audit_log_has_no_by_id_mutation`
failed on pg legs (required producer): `get_page` is a public audit-store
method outside its allowlist. Per its docstring a new method arrives with its
own scoped case: `get_page` named as the bounded keyset **read** (#358); the
no-by-id-mutation invariant is unchanged.

## Validation (all commands CI-exact)

- `tests/migrations/test_single_migration_head.py`: 3 passed (after repair).
- pg18 + pg17 batteries: migration chain 13 passed; `alembic upgrade head` /
  `downgrade base` / `upgrade head` clean; `packages/maistro-core/tests/persistence`
  + `test_container_postgres.py` 747 passed each; workspaces + canvas with
  `MAISTRO_REQUIRE_PG_LEGS=1` 335 passed, 2 skipped each.
- `hive-conductor-e2e` compose harness: 10 passed, 13 skipped.
- `hive-conductor-e2e-ui` compose harness: 125 passed (2.6m).
- `uv build` all 10 package wheels + `verify-wheel-imports.py`: all import.
- `ruff check .`, `ruff format --check .`: clean; `mypy` (six src trees): clean.
- Focused audit suites: backend 76 passed; core audit-pages + conformance 45
  passed, 4 skipped (pg legs covered in the battery above).
- Suite inventories (`hive-conductor/backend/tests`, `maistro-core/tests`): match.
- `check-doc-links.py`: 0 broken.
- Vulture exact gate: still fails on the 4 identities — see Finding 3; the only
  remaining red, and not fixable from this branch.
