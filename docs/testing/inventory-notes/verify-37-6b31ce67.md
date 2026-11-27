# Verification round — #37 at 6b31ce674f (producer repair)

Round L37 (job 83e96153): independent re-verification at the exact assigned
head `6b31ce674f`, plus one writer repair for a producer break this round
found. No GitHub actions; no closure keywords added anywhere.

## formal-conformance gate — green at CI's exact arguments

The lane's named CI failure was `formal-conformance`. Re-executed every step
of `.github/workflows/formal-conformance.yml` against a fresh pgvector:pg18
database (`maistro:maistro`, db `maistro_fc_37`), CI env shape:

- `uv pip install -e formal/ -e packages/maistro-evolve` first: a bare
  `uv sync` venv uninstalls both (the driver's check-0 log shows it), and
  `formal/models/test_rsi_*_conformance.py` then fail collection with
  `ModuleNotFoundError: No module named 'maistro_evolve'`. That is a venv
  shape, not a tree defect — CI installs both explicitly.
- `alembic upgrade head` (fresh DB): full chain → **071**.
- `pytest formal/models/ --timeout=300 --hypothesis-seed=0` → **672 passed**.
- `python scripts/extension_lifecycle_proof.py` → **13/13 stages, 62/62
  checks, exit 0**.
- `check-formal-oracle-independence.py --base 80242f2852` → OK;
  `check-m1-convergence-freeze.py --base 80242f2852` → OK (re-run after the
  repair below: still OK).

## Prior finding (RestrictViolationError) — verified fixed

`40f961d1ef` restored `pytest.raises(asyncpg.exceptions.RestrictViolationError)`
in `personas/test_durable_store_pg.py`. With `MAISTRO_TEST_PG_DSN` set:
the named test → **1 passed**; the whole file → **14 passed**. The driver's
earlier green was skip-shaped (232/11 PG legs skipped); these legs ran here.

## New finding: the #37 fences broke four PG producers (repaired here)

The fence work (workspace existence check in `PgProjectScopeStore.create_root`
and migration 071's `canonical_projects` → `canonical_workspaces` RESTRICT FK)
is exactly the #37 acceptance behavior — but four test producers were still
provisioning Projects/Roots for Workspaces that never existed durably, which
migration 019's deferred FK had allowed. Base-equivalence proven: dropping only
`fk_canonical_projects_workspace` on an otherwise identical migrated DB turns
`test_brief_commit.py` from 37 setup errors back to **49 passed**.

Reproduced at CI's coverage-postgres env shape (`DB_*` + `MAISTRO_TEST_*` +
`MAISTRO_REQUIRE_PG_LEGS=1`, pgvector:pg18):

- `hive-conductor/backend/tests/test_brief_commit.py` → **37 errors at setup**
  (FK violation in `stack`; its comment even asserted the revoked assumption:
  "the shared test database keeps no Workspace rows of its own").
- `test_evolution_restart_replay.py` [postgres*] → **8 failed** (`WorkspaceNotFound`
  fence via `_PgRestartSpine.start`), `test_evolution_restart_replay_pg.py` →
  **3 failed** (same fence via `_start_leg`), `test_evolve_domain_retention.py`
  [postgres] → **1 error** (`WorkspaceNotFound`).
- `maistro-design/tests/test_creative_brief_pg.py` → **1 failed** (`_seed_scope`
  inserted a Project with no durable Workspace; no CI producer runs it with a
  DSN today, but `MAISTRO_REQUIRE_PG_LEGS` declares the leg must run when a
  server exists).

Repair (test provisioning only, no production code touched):

- `test_brief_commit.py`: `_mirror_workspace_identity` mirrors the canonical
  identity the in-process authority owns (workspace row only — the one-root
  index already owns the Root mirror); teardown deletes the mirrored identity
  last (RESTRICT ordering); the stale comments updated.
- `_PgRestartSpine.start` / `_start_leg` / `retention_domain[postgres]` /
  `_seed_scope`: provision the durable Workspace through the shipped atomic
  `PgWorkspaceStore.create` (identity + roster + Root in one transaction)
  before minting Roots; idempotent via an existence check, since restart legs
  share one fixed workspace id.

## Post-repair validation (same CI env shapes)

- The four repaired files + `test_evolve_domain_store.py` → **107 passed**.
- Full `hive-conductor/backend/tests`, PG shape → **4711 passed, 2 skipped**
  (collected 4713 = recorded inventory; was 49 broken before the repair).
- Full `hive-conductor/backend/tests`, server-less (ci.yml/coverage-gate
  shape) → **4592 passed, 121 skipped** (unchanged by the repair).
- `maistro-design/tests`: PG shape **725 passed**; server-less **724 passed,
  1 skipped** (unchanged).
- coverage-postgres core session (quality.yml:445-461 suite list, DSN set) →
  **7721 passed, 99 skipped, 4 xfailed, 0 failed**.
- `tests/migrations` against an **unmigrated** DB (CI's migration job shape) →
  **174 passed** (includes `test_workspace_tombstones_installed_base.py`).
- `check-suite-inventory.py` → 21/21 suites match; **37436 unique identities**,
  no duplicates (fixture repairs move no node identity — no delta note owed).
- `ruff check .` + `ruff format --check .` clean; `check-backlog-consistency.py` OK.
