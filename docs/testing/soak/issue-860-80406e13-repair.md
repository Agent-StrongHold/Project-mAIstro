# Issue #860 — bounded repair 80406e13

## Frozen scope

- Issue #860 only; assigned worktree `/home/dev/Git/wt/auto-860`.
- Starting HEAD: `66a13b1815b5a513616ff79090ce1bebb627ae5f`.
- Supplied develop base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Clean starting worktree; no incoming changes to salvage.
- Dispatch snapshot: job `80406e13d8c7469aa345e3d869c561f7/dispatch-context.json`.
- Processing the reported vulture gate failure and #860 acceptance only; no linked PR work.
- Repair surfaces: this report, and `quality/vulture-baseline.json` only if the exact prescribed scan identifies reviewed retained identities. Production/test changes require actual failure evidence before expanding this scope.

## Initial evidence and assumptions

The current job directory contains no `check-*.log` files. The supplied prior result reports BLOCKED, not a develop-sync conflict. No merge or GitHub mutation is warranted. Prior verification claims will be independently checked. Production release artifact/configuration identity is not provided by the assignment; host-process preflight is not assumed to qualify as the exact release candidate.

## Reproduced gate evidence

The prescribed vulture command passed (1323 reviewed identities, 1323 findings; zero unclassified/never-allowlist). No ledger amendment is justified. The supplied historical `98a11313/check-3.log` instead reports a schema-fence test failure: 24 DDL statements versus 21 expected. Rechecking that exact production/test surface next. No scanner findings are guessed.

## Fresh validation

Commands were executed locally, with 600–1200 second timeouts:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1323/1323 identities; matches `.github/workflows/quality.yml:1078`.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py -x -q`: **126 passed, 6 skipped**, 2.90s. Skipped tests are not PostgreSQL integration evidence.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3277 files.
- `uv run python scripts/check-doc-links.py`: PASS, 2686 Markdown files, no broken links.
- `git diff --check`: PASS.

The historical schema assertion already includes all three validation-audit columns at `packages/maistro-core/tests/persistence/test_pg_learnings.py:177`. Production `PgLearningStore.ensure_schema` takes the advisory lock inside its transaction before upgrading those columns. The current ordered-DDL regression passes; no fresh schema repair is indicated.

## Architecture reconciliation

Read repository instructions, documentation authority hierarchy, accepted ADR-081226-a66b (lifecycle), accepted ADR-081626-f383 (fencing), and proposed ADR-081 (deployment). Preserve Goal -> Graph -> Run -> NodeRun -> Attempt. Queue receipts do not own execution lifecycle. The fencing ADR explicitly does not establish expiry takeover; the issue's reclaim acceptance cannot authorize inventing that mechanism. ADR-081 is proposed and cannot establish accepted deployment authority on its own. The assignment supplies no designated immutable RC image/configuration.

## Acceptance review

| Criterion | Executed evidence and verdict |
| --- | --- |
| Representative RC profile | Read `m3a-load-profile.md`; its remaining-gaps section at line 163 excludes concurrent user/Workspace populations, Graph fan-out, successful tool/model calls, Canvas and Goal/background workloads. Complete representative coverage **UNVERIFIED**. |
| At least two production replicas | Tests execute two ASGI instances, not the designated deployed RC. Production replica exercise **UNVERIFIED**. |
| Sustained saturation, queue growth, expiry/reclaim, retries, leaks and shutdown | Sampler and counter regressions pass; no sustained production soak executed. **UNVERIFIED**. |
| No duplicate physical work across schedule/task/Run/Attempt and Goal paths | Admission tests exercise evidence accounting, not a physical-work oracle under load. Goal reconciliation and physical deduplication **UNVERIFIED**. |
| Rate/security/degraded concurrency cannot be bypassed by replica selection | Executed `test_replica_selection_has_an_independent_production_allowance` (`tests/test_soak_promotion_gates.py:439`) for authenticated and pre-auth identities. Each replica returns `[200, 200, 429]` for the same identity. This matches the explicit local-budget contract in `packages/maistro-server/src/maistro_server/api/rate_limit.py:32`; aggregate non-bypass is **NOT PROVEN**, and shared aggregate-budget interpretation is contradicted. Exact-RC security/degraded soak **UNVERIFIED**. |
| Full production metrics and explicit thresholds | Profile provides partial thresholds; sampler tests pass. Production query/lock/pool, application-loop, worker/RSS/fd/queue/error/timeout observations **UNVERIFIED**. Driver loop lag is not application loop lag. |
| Kill/restart during active work with drain/fencing/recovery | Boot cleanup and evidence-gate regressions pass, not a live active-work recovery oracle. **UNVERIFIED**. |
| Long-running exact RC/configuration soak | `scripts/soak/run_soak.py:744` deliberately returns `ok=False` for host-process preflight. Executed CLI tests reject synthetic four-hour evidence; they do not run four hours. **UNVERIFIED / BLOCKED**. |
| Findings filed/reclassified to earliest broken invariant | No new live-load finding claimed; external filing/reclassification **UNVERIFIED**. GitHub mutations prohibited. |
| Machine/human soak evidence tied to image/package/commit/config hashes | This report identifies the tested commit but is not production soak evidence. Exact-artifact evidence **UNVERIFIED**. |

The executed production-router receipt regression at `tests/test_soak_promotion_gates.py:564` observes admission-instance 200 and peer 404. The route reads the local queue at `packages/maistro-server/src/maistro_server/api/tasks.py:147`. This demonstrates a visibility limit, not physical duplication. Neither that limit nor the intentional local rate-budget contract justifies introducing a new authority in this bounded CI repair.

## Disposition and handoff

**BLOCKED** on production acceptance, with no reproduced CI repair target. Changed only this report; no code, tests, inventory counts, ledger, grants, gates or runtime configuration changed. No inventory delta is required because no tests were added or modified. Local commit is a handoff only, never integration approval.

Progress: checked 1 issue; done 0; skipped 0; fresh validation errors 0.
Next: designate immutable RC images/configuration; complete the representative workload and physical-work/metric oracles against that topology; reconcile the rate-budget acceptance mismatch under existing authority; execute and publish the required long-running production soak. Repeating an unchanged-head CI-repair request cannot establish those missing prerequisites.
