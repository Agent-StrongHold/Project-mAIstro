# Issue #860 — evidence-led CI repair checkpoint ee0f04ab

## Frozen scope and disposition

Assigned issue #860 only, branch `auto-860`, starting HEAD
`1891405bd5ef1338db71072b597c61b00a3a3506`, supplied base
`3c761d14db944a727fa0744444bc67cfe36d49f7`. Starting worktree clean.
Snapshot: existing issue diff; inspect the reported schema test failure and
Vulture ledger; change only an evidenced repair and this checkpoint. No GitHub
mutations, integration actions, or new execution authority.

Ambiguity: the dispatch labels this a Vulture CI repair, but its historical
`98a113.../check-3.log` is a schema-fence test failure (24 DDL statements versus
21 expected). Treat actual fresh failures as repair targets, not the label.
Current job supplied no `check-*.log` files. Fresh logs are in
`/home/dev/maistro/jobs/ee0f04ab10b749a2bc03634588753f75/worker-*.log`.

## Fresh validation

- Exact requested Vulture command:
  `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  **PASS**: 1323 reviewed identities, 1323 findings, zero unclassified or
  never-allowlist findings. No ledger amendment is justified.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  **37 passed, 6 skipped**. The historical failure does not reproduce.
  The ordered test already includes the three validation-audit columns at
  `packages/maistro-core/tests/persistence/test_pg_learnings.py:177–179`.
  Production `PgLearningStore.ensure_schema` takes the advisory lock before
  upgrades (`packages/maistro-core/src/maistro/persistence/pg_learnings.py:215`).
  Skipped PostgreSQL cases are not live concurrency evidence.
- `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py -x -q`:
  **89 passed**. Total focused validation: **126 passed, 6 skipped**.
- `uv run ruff check .`: **PASS**.
- `uv run ruff format --check .`: **PASS**, 3277 files.
- `git diff --check`: **PASS** before final report completion.

Validation commands used 1200-second timeouts. An exploratory lookup of
`packages/maistro-core/src/maistro/persistence/backend.py` found no such file;
that lookup was skipped, not used as evidence.

## Architecture reconciliation

Read repository instructions, documentation authority hierarchy, accepted
ADR-081226-a66b and ADR-081626-f383. Preserve
Goal -> Graph -> Run -> NodeRun -> Attempt. Queue receipts and the soak driver
are not lifecycle authorities. The fencing ADR explicitly does not define
lease-expiry takeover; issue acceptance cannot authorize inventing reclaim
semantics. ADR-081 is Proposed, not accepted authority. The shipped Compose
reference does define two application services, but requires an external model
gateway and advises pinning image digests; it is not a designated immutable RC.
Missing production evidence must remain a blocker, not be replaced by unit-test
success or a longer host-process emulator run.

## Acceptance review

| Criterion | Executed evidence and remaining gap |
| --- | --- |
| Representative RC load profile | Read `m3a-load-profile.md`; its remaining-gaps section explicitly excludes multi-user/Workspace traffic, Graph fan-out, successful tool/model, Canvas and Goal/background work. Complete representative coverage **UNVERIFIED**. |
| Two production application replicas | Real middleware/router instances exercised in ASGI tests, not deployed replicas. Compose declares two replicas; production exercise on this HEAD **UNVERIFIED**. |
| Sustained saturation, queue growth, expiry/reclaim, retry/backoff, leaks and shutdown | Accounting/sampler tests pass. No sustained production run executed; **UNVERIFIED**. |
| No duplicate physical work for schedule/task/Run/Attempt/Goal operations | Admission/receipt regressions pass, not a physical-work oracle. Schedule admission alone cannot establish physical fencing or Goal reconciliation; **UNVERIFIED**. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | Production middleware test at `tests/test_soak_promotion_gates.py:439` passes for both identity classes: replica 1 returns 200/200/429, then replica 2 independently returns 200/200/429. This contradicts a cluster-wide-budget interpretation, consistent with documented process-local scope at `packages/maistro-server/src/maistro_server/api/rate_limit.py:32`. Full acceptance **UNVERIFIED**; contract reconciliation required. |
| Complete production metrics with thresholds | Profile includes partial thresholds; sampler tests pass. Driver-loop lag is not application-loop lag. Full production pool/query/lock/worker/RSS/fd/queue/error/timeout evidence **UNVERIFIED**. |
| Active-work replica kill/restart with drain/fencing/recovery | Boot cleanup regressions pass, not active-work recovery. **UNVERIFIED**. |
| Long-running exact-RC artifact/configuration soak | `scripts/soak/run_soak.py:744` unconditionally rejects host preflight as exact RC; executed CLI tests enforce rejection even for simulated four-hour evidence. Historical round100 evidence identifies another HEAD and 420.04 seconds. Required exact-RC soak **UNVERIFIED** and blocked. |
| Findings filed/reclassified before promotion | No new live-load finding claimed; GitHub mutations prohibited. External filing/reclassification **UNVERIFIED**. |
| Machine/human soak evidence tied to exact artifact/config hashes | Local validation logs and this report identify the tested HEAD; they are not production image/configuration evidence. Exact-RC publication **UNVERIFIED**. |

The executed production-router receipt test at
`tests/test_soak_promotion_gates.py:564` observes 200 on the admitting instance
and 404 on its peer. The real route uses `queue.get` at
`packages/maistro-server/src/maistro_server/api/tasks.py:144`. This establishes
a receipt-visibility limitation, not duplicated physical work.

## Handoff

**BLOCKED**, with no reproduced CI repair target. This checkpoint is the only
changed repository file. No test additions or inventory deltas; no runtime,
configuration, ledger, grant or gate changes. All previous work preserved.
Local commit is a handoff only, not integration approval.

Next action requires a designated immutable RC image/configuration and complete
production workload/physical-work/metrics oracles, then the actual long soak.
Reassigning the same passing Vulture scan cannot resolve these prerequisites.
Progress: checked 1 issue, done 0, skipped 0, validation errors 0; acceptance
blocked.

Final documentation validation: `uv run python scripts/check-doc-links.py`
**PASS** (2688 Markdown files, zero broken relative links); `git diff --check`
**PASS**. No new test inventory note required.
