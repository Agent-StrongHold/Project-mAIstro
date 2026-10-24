---
inventory-delta:
  packages/maistro-core/tests: +15
  packages/maistro-server/tests: +2
---

# Issue #1182: opt-in system-wide active root-Run ceiling

Closes the one acceptance residual the previous verification round recorded
for #1182 ("an explicit system/global ceiling where needed"): the admission
authority (`RunStore.create_run` on all three backends) now also enforces an
opt-in system-wide ceiling on concurrently active root Runs, configured via
`MAX_ACTIVE_ROOT_RUNS_SYSTEM`. Unset stays the owner-decided baseline of 8
per principal / 32 per Workspace with no global bound; a configured value can
only tighten. On PostgreSQL a system-wide advisory lock serializes the count
across replicas, in the existing workspace→principal lock order (system last,
so the order stays acyclic). `/health/ready`'s admin payload reports the
effective ceilings, `system: null` included.

## maistro-core/tests/runs/test_run_concurrency_limits.py (+15)

- `test_the_system_ceiling_is_opt_in_and_validated` — default None, positive
  values accepted, zero refused (1).
- `test_configured_reads_the_system_ceiling_setting` — the settings knob is
  the one `RunConcurrencyLimits.configured()` enforces (1).
- `test_a_non_positive_system_ceiling_is_refused_at_settings` — `0` and `-3`
  are refused at Settings, so a typo cannot silently close every submit
  surface (2).
- `test_the_spine_wiring_enforces_the_configured_system_ceiling` — the
  shipped `wire_execution_spine` path on memory and SQLite (2).
- `test_the_system_ceiling_spans_workspaces_and_principals`,
  `test_terminalizing_a_run_frees_its_system_slot`,
  `test_concurrent_admission_holds_the_system_ceiling` — the new
  `system_spine` fixture runs each on memory, SQLite and PostgreSQL; the
  concurrent case is the serialized advisory-lock path on real PostgreSQL (9).

## maistro-server/tests/api/test_resource_policy_health.py (+2)

- `test_readiness_exposes_run_concurrency_limits_to_admin_callers` — admin
  payload shows per-principal/per-Workspace/system (null and 64), anonymous
  probes keep the status-only contract. Its `@pytest.mark.ac` binding names
  `SPEC-082226-2a10/AC-6` (public readiness discloses no effective protected
  values to anonymous callers — the contract this test asserts directly).
- `test_readiness_degraded_still_reports_run_concurrency_limits_to_admins` —
  the 503 detailed payload carries the same ceilings when a dependency is
  down.

## Independent re-verification (2026-10-24, live evidence, tree unmodified)

Executed on this worktree at `cc605a6c` against the live `pgvector:pg18`
container (`MAISTRO_TEST_PG_DSN` set, so no `[postgres]` leg skipped):

- `uv run pytest packages/maistro-core/tests/runs/test_run_concurrency_limits.py -q`
  → **79 passed** (principal/Workspace/system ceilings, fairness, parked-resume,
  duplicate-vs-backpressure, stranded-turn reclaim; concurrent-admission cases
  exercised the real advisory-lock path on PostgreSQL 18).
- `uv run pytest packages/maistro-core/tests/runs -q` → **1670 passed,
  3 skipped**; `uv run pytest packages/maistro-server/tests/api -q` → **552
  passed** (includes the 429-without-retained-claim and admin-diagnostics
  regressions); `test_resource_policy_declared_floors.py` → 8 passed
  (tighten-freely / loosen-only-with-override for both ceilings).
- **Fail-before proof:** a `-p` plugin neutering only
  `RunConcurrencyLimits.check` (no other change) makes all 15 ceiling tests
  fail across memory, SQLite and PostgreSQL — the check is the single
  refusing site; without the plugin all pass.
- **Gates with CI's exact arguments:** `ruff check .` / `ruff format --check .`
  clean; `check-suite-inventory.py` (21 suites match); `check-security-inventory.py`;
  `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (1321 reviewed = 1321 findings); `check-radon-baseline.py`;
  `check-reachability.py`; `check-reachability-dispositions.py`;
  `check-ratchet-provenance.py`; `check-promotion-surface.py`;
  `check_direct_effects.py` — all exit 0. Running the vulture gate without its
  CI path arguments fails on `tests/`-scoped rows the blocking job never sees
  (the documented default-scan trap), which is an invocation error, not debt.
- mypy on `maistro/runs`, `maistro/config`, `maistro/security`,
  `maistro_server/api`: clean (remaining repo mypy errors are pre-existing
  import-stub issues in unrelated `cli`/`maistro_canvas` modules).

Known residuals, unchanged: RC/load evidence under #860 is an external-issue
dependency (delegated by this issue's own 2026-10-03 decomposition); the
branch needs a sync merge from `origin/develop` before integration — develop's
delta touches adjacent regions of `settings.py`/`store.py`/`sqlite_store.py`/
`pg_store.py`/`health.py`, so expect small same-region conflicts there.

## Merge-queue repair round (2026-10-24, live evidence, tree at 5b7ff2aef)

Correction to this note's earlier claim: the `SPEC-1182/AC-6` marker was
**not** a report-only bucket — `scripts/check-ac-state.py --ratchet` failed
with `markers_without_criterion: 3 exceeds the ceiling of 2` (base 4de7e906d
measures exactly the two pre-existing orphans `ADR-070126-6386/persist` and
`ADR-070126-6386/stage3`; this branch added the third). The marker now binds
to the existing `SPEC-082226-2a10/AC-6` criterion the test genuinely
exercises. Base-vs-candidate discrimination was measured, not assumed: the
base revision itself measures `design_coverage` 44.2377% (identical to this
branch — the branch adds no specs), so the second ratchet failure
(`design_coverage: 44.2377, floor still says 39.641`) is develop's own
unbanked improvement, carried by this merge group; banked per the gate's own
instruction as `quality/ac-state-notes/auto-1182.json`.

Evidence from this round (all exit 0 unless stated):

- `check-ac-state.py --run-tests --ratchet --mandate 4de7e906d9dc` against a
  live pgvector:pg18 (migrations applied first, CI's exact step order) — was
  exit 1 with the two failures above, now **exit 0** (ratchet on the folded
  bound, acceptance mandate, and chain mandate all pass).
- `pip_audit_gate.py` on a fresh `pip-audit --strict --format=json` report —
  was exit 1 (`fastmcp==4.0.11` GHSA-7xgj-8392-5q4r + GHSA-vqqp-x5qm-5qp4,
  `setuptools==84.0.0` GHSA-xmj3-9gf7-h52w), now **exit 0** after lock-only
  upgrades (`uv lock --upgrade-package fastmcp setuptools`: fastmcp/
  fastmcp-slim 4.1.3, setuptools 84.2.1, transitive openapi-pydantic 0.6.0).
  The fastmcp-adjacent suites still pass (523 passed, 4 skipped:
  `test_import_surface.py`, `api/test_main.py`, `test_sigterm_shutdown.py`,
  `maistro-core/tests/tools`).
- Canvas frontend `npm audit --audit-level=high` — was 6 vulnerabilities
  (3 high: undici ×3, zod; 3 moderate: ip-address), now 0 after lockfile-only
  `npm audit fix` (no package.json change); `test:ci` 79 passed, lint and
  build exit 0. Hive-conductor frontend had 1 high (zod), now 0; build and
  lint exit 0. (The `test` job's npm-audit step and the container job's
  frontend license surfaces both consume these locks.)
- Container-scan failure re-read from the actual job log: Trivy fails on
  `maistro-engine-research` — pypdf 6.21.1 CVE-2026-115572 (HIGH, fixed in
  6.21.2; the two sibling CVEs are unfixed and `ignore-unfixed: true`). Lock
  bumped to pypdf 6.21.2 (`uv lock --upgrade-package pypdf`); pypdf is a
  browser-use transitive that ships only in that image, so no local suite
  exercises it — the image rebuild picks the fix up.
- `packages/maistro-core/tests/runs/test_run_concurrency_limits.py` + health
  + declared-floors suites against live PostgreSQL 18: **98 passed**
  (principal/Workspace/system ceilings incl. the real advisory-lock path,
  fairness, parked-resume, admin readiness diagnostics, tighten-freely/
  loosen-only-with-override).
- Full server suite with CI's env (`REQUIRE_AUTH=false MAISTRO_DRY_RUN=1`):
  **646 passed, 8 skipped**. `check-suite-inventory.py` for maistro-core and
  maistro-server: both match. `ruff check .` / `ruff format --check .`: clean.
  `check-dependency-namespaces.py` (the ci.yml `security` job's other leg):
  no unreviewed top-level namespaces.
