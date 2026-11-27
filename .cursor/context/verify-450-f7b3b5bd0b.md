# Verify #450 @ f7b3b5bd0b4dbd626833cea616ababad4f07ba0c (branch auto-450) — 2026-11-27

## Scope of this round

Independent verification of the two named CI-gate failures from the last merge-queue
evaluation, re-derived from the issue text (not the implementer's summary). Issue #450
is the M4 steering tracker; this PR (refs #450, no closure keywords — checked commit
bodies 618954f052..HEAD and the live PR body) carries the #301/M4-H slice: the
per-Workspace working log's PostgreSQL durable twin, plus the repair rounds for the
071/072 migration-id collision and the CI-quality obligations fixture.

## Executed locally (all commands run by the verifier at this exact head)

1. **Fixture digest (previous coverage-gate red).** 196ed43732 edited the
   quality.yml coverage-postgres producer without updating
   `tests/fixtures/ci_quality_obligations.json`; the contract test
   `tests/test_ci_quality_split.py::test_every_original_quality_obligation_survives_with_its_profile`
   failed locally and in CI (run 45956960890). At this head the fixture pins
   `12fdf1b1dbaa129563af…` for `coverage_jobs.coverage-postgres` and the whole file
   passes: `uv run pytest tests/test_ci_quality_split.py -q` → **96 passed**.
2. **Diff-coverage gate with CI's exact invocation.** Built real coverage data:
   server-less `coverage run --branch --source=packages/maistro-core/src/maistro -m
   pytest packages/maistro-core/tests/memory packages/maistro-core/tests/test_container_postgres.py`
   → 1080 passed/36 skipped; then, against a throwaway pgvector/pg17
   (127.0.0.1:5490) with CI's producer env (`MAISTRO_TEST_PG_DSN`,
   `MAISTRO_TEST_DATABASE_URL`, `MAISTRO_REQUIRE_PG_LEGS=1`) after
   `uv run alembic upgrade head` → 131 passed/0 skipped on CI's exact producer
   paths (the three memory files + test_container_postgres.py). `coverage xml` +
   `uv run python scripts/check-diff-coverage.py <xml> --base origin/develop` →
   **ok: every measured file this change touches is at or above 90% lines / 80%
   branch arcs** (3 measured: container.py, wiring.py, pg_store.py; 8 exempt:
   migration 072 + tests, per the script's own declarations).
3. **Migration chain after the collision resolution.** `alembic upgrade head`
   applies 070→071 (develop's Sentinel decision integrity, #69) →072 (lane's
   working log, #301/#105) and `alembic current` = **072 (head)**. The four
   lane-touched migration suites pass against the real server:
   **31 passed** (test_migration_chain, capability_invocation_effect_index,
   goal_installed_base, legacy_principal_ownership).
4. **#301 acceptance evidence.** The retained-log PostgreSQL durability residual
   requires: actual PG backend selection, real-PostgreSQL conformance, and
   fresh-pool restart/rebuild proof. Executed: conformance's postgres leg +
   `TestPostgresRestart::test_log_and_results_survive_a_fresh_pool`
   (`leg.stop()` → `leg.restart()`, asserts history, reset-survival metadata,
   reference-payload content, store type, idempotent schema bootstrap) and 7
   wiring/container-seam selection tests — all pass against the real server
   (subset rerun `-k "postgres or pg or pool or container"` → 7 passed). The
   server-less run's 36 skips flip to passes under `MAISTRO_REQUIRE_PG_LEGS=1`
   with a server, so the durable legs are genuinely PG-gated, not hollow.
5. **071→072 renumber.** Repo-wide grep for `migration.071|071_workspace_working_log|migration-071`
   over packages/, alembic/, .github/, tests/, docs/testing/ → only legitimate
   refs remain (`alembic/versions/071_sentinel_decision_integrity.py`, the
   `071:072` revision range in the schema-agreement test, 072's `down_revision`).
   The stale-comment findings against 52966c0678 are resolved at this head.
6. **Gates.** `uv run ruff check .` → all passed; `uv run ruff format --check .`
   → 3718 files already formatted; `uv run python scripts/check-suite-inventory.py`
   (CI's no-arg form, all suites) → **ok: 21 suite(s) match the recorded inventory**,
   37758 unique identities, 0 duplicate evidence. Inventory note
   `docs/testing/inventory-notes/450-working-log-postgres.md` (+21) is consistent.

## CI at this head (evidence, not inferred)

`gh pr view 2532` headRefOid = f7b3b5bd0b… (exact). Rollup at verification time:
79 checks COMPLETED/SUCCESS; `test` and `Coverage gate (publish-set floor + diff
coverage)` still IN_PROGRESS; nothing failed. The 87% publish-set aggregate floor
is a whole-repo multi-producer measurement (~30–45 min) not locally reproduced;
its decisive lane-owned components — the previously-red producer-side contract
test and the per-file diff gate — are proven locally above. Pending CI remains
UNVERIFIED by policy; check run 45966639245 for the conclusion.

## Harness note (not a defect)

Running the *whole* `packages/maistro-core/tests/memory` directory under CI's
DB-configured env fails 4 tests in `test_engine.py` ("without database" tests
asserting no-DB behavior). CI never runs that file with `DB_*` set (its producer
paths are explicit), so this is an env artifact of over-inclusion, not a lane
regression; re-running CI's exact paths passed 131/131.
