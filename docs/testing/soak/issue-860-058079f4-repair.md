# Issue #860 — bounded repair 058079f4

## Frozen scope

- Only issue #860; branch `auto-860`, clean starting HEAD
  `b09673333341505343041b9db07987d778af5d8b`; supplied develop base
  `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- No PR processing, network enumeration, GitHub mutation, or deployment mutation.
- Inspection/validation scope: supplied dispatch and prior result/log; repository
  instructions; ADRs governing canonical execution and production deployment;
  `scripts/check-vulture-baseline.py`, its CI invocation and ledger;
  `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
  `docs/testing/soak/m3a-load-profile.md`, adjacent production task/rate paths
  and their existing tests. Changes limited to this handoff and any genuinely
  evidenced vulture repair (ledger amendment explicitly authorized).
- Current job directory contains no `check-*.log` files. Prior result is BLOCKED;
  its verification claims are not assumed true.
- Ambiguity: this is assigned as a writer repair despite generic verifier wording.
  Proceed as writer with local validation and a required local commit.

## Progress

Exact prescribed vulture scan passed: 1323 findings / 1323 reviewed identities,
zero unclassified or forbidden identities. No ledger amendment is justified.
The supplied historical `98a11313/check-3.log` instead fails the schema-fence
assertion (24 actual DDL statements versus 21 expected). Recheck that exact test.
Exact-RC identity/configuration is not supplied in the lane brief. No production
soak acceptance is inferred from unit tests.

## Fresh validation

All commands used a 1200-second timeout:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: passed, 1323 reviewed identities / findings. Invocation matches `.github/workflows/quality.yml:1078`.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py -x -q`: **126 passed, 6 skipped** in 2.73s. Skips are not live PostgreSQL evidence.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3277 files.
- `uv run python scripts/check-doc-links.py`: passed, 2685 Markdown files, zero broken links.
- `git diff --check`: passed.

The historical schema assertion is already repaired at
`packages/maistro-core/tests/persistence/test_pg_learnings.py:177`: its ordered
DDL expectation includes the three validation-audit columns. No reproducible
CI failure remains in this focused validation. Do not invent dead code or amend
an already-matching ledger. No tests changed, so no inventory delta is required.

## Architecture and acceptance review

Read accepted ADR-081226-a66b and ADR-081626-f383. Preserve
Goal -> Graph -> Run -> NodeRun -> Attempt; queue receipts are not an execution
authority. The fencing ADR explicitly does not define expiry takeover; the
issue's reclaim wording cannot authorize a competing recovery authority.
ADR-081, cited by the profile, is **Proposed**, not accepted deployment authority.
The exact supported RC topology still needs owner designation.

| Issue acceptance | Executed evidence / remaining limit |
| --- | --- |
| Representative RC workload profile | Profile read in full; `m3a-load-profile.md:163` explicitly identifies missing users/Workspaces, Graph fan-out, successful tools/models, Canvas and Goal/background workloads. Complete representative profile **UNVERIFIED**. |
| At least two production replicas | Existing tests execute two ASGI instances, not deployed RC replicas. Production topology **UNVERIFIED**. |
| Sustained saturation, growth, reclaim/backoff, leaks, shutdown | Process sampler regressions pass, including a real uv child. Long-running resource and recovery observations **UNVERIFIED**; no soak executed. |
| No duplicate physical work across schedule/task/Run/Attempt and Goal paths | Admission-evidence tests pass, but use mocked HTTP receipts; backpressure uses a real in-memory spine without execution. Physical-work and Goal reconciliation proof **UNVERIFIED**. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | `tests/test_soak_promotion_gates.py:439` executes production middleware and observes `[200, 200, 429]` independently on each replica for the same authenticated/pre-auth identity. Shared aggregate non-bypass **NOT MET** by these observations; exact-RC security/degraded soak **UNVERIFIED**. |
| Full metrics with explicit thresholds | Profile defines thresholds; sampler/counter tests pass. Production PG query/lock/pool, application event-loop, worker/RSS/fd/queue and error/timeout coverage **UNVERIFIED**. Driver loop lag is not application loop lag. |
| Kill/restart during active work with drain/fencing/recovery | Boot cleanup and evidence-gate tests pass; live physical-work loss/duplication oracle **UNVERIFIED**. |
| Long-running exact RC/configuration, rerun on changes | `scripts/soak/run_soak.py:744` always rejects this host-process preflight as exact-RC evidence. CLI tests at `tests/test_soak_promotion_gates.py:105` reject synthetic four-hour evidence; they do not run four hours. Exact-RC soak **UNVERIFIED / BLOCKED**. |
| File/reclassify load findings | No new live load finding claimed. External filing/reclassification **UNVERIFIED**; GitHub mutations prohibited. |
| Machine/human evidence tied to exact artifact/config hashes | This is a local validation handoff, not a hash-tied production soak. Promotion evidence **UNVERIFIED**. |

The executed production-router receipt test at
`tests/test_soak_promotion_gates.py:564` also observes 200 on the admitting
instance and 404 on its peer. This follows the local queue read at
`packages/maistro-server/src/maistro_server/api/tasks.py:147`; it does not by
itself demonstrate duplicated physical work. Rate-limit process-local scope is
explicit at `packages/maistro-server/src/maistro_server/api/rate_limit.py:32`.
Changing either authority/policy speculatively is not this CI repair.

## Disposition

**BLOCKED**. Only this handoff changed; no code, tests, ledger, grants, gates or
runtime configuration changed. Commit locally, with no integration approval.

Progress: checked 1 issue; done 0; skipped 0; fresh validation errors 0.
Next: owner-designated immutable RC images/configuration, ADR-compatible
production workload/physical-work/metric oracles, and resolution of the stated
rate-budget acceptance mismatch; then execute the required long soak. Another
unchanged-head CI-repair round cannot resolve these prerequisites.
