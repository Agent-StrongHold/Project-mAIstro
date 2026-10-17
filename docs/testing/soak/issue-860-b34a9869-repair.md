# Issue #860 — repair checkpoint b34a9869

## Frozen scope

- Assigned issue only: #860; branch `auto-860`.
- Starting HEAD verified: `8f3653e05abbf82a9453afee6b0acdf068f80022`.
- Assigned base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Initial worktree clean; no incoming uncommitted work to salvage.
- Process only the supplied dispatch snapshot; no GitHub queries or mutations.
- Repair surfaces: this report and, only if the exact scan supplies evidence,
  `quality/vulture-baseline.json` and identified genuinely dead code.
- Acceptance inspection surfaces: `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, existing soak profile, adjacent server
  concurrency tests, repository instructions and governing ADRs.
- Current job directory contains no `check-*.log` files. The specifically
  supplied prior failure log and prior result will be inspected instead.

## Initial disposition

Prior result says BLOCKED, not accepted as verification. No exact release
candidate/deployment identity is supplied in the lane prompt. Assumption:
validate local gates and reachable harness behavior; do not invent RC evidence
or broaden into a new distributed execution/rate authority.

## Executed checkpoint

The exact requested vulture command passed (exit 0): 1323 findings, 1323
reviewed identities, zero unclassified and zero never-allowlist findings.
No ledger amendment is evidence-supported. The supplied historical
`check-3.log` instead reports a schema-fence test failure (24 actual statements
versus 21 expected). That exact test suite will be re-run; no guessed scanner
repair will be made.

Read the issue's ten acceptance criteria from the supplied snapshot, repository
instructions, accepted ADR-081626-f383 (Attempt fencing), ADR-082126-f69c
(recurrence uses canonical Runs), and ADR-083026-a91e (unmeasured is absent).
No competing scheduler/authority or missing-as-zero evidence is permissible.
The adjacent schema test already expects all 24 statements, including the
three validation columns absent from the historical failing version. Existing
soak tests distinguish admission from execution and reproduce independent
production middleware allowances; their results are still to be executed.

## Focused validation results

Executed in the assigned worktree with 1200-second timeouts:

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | exit 0; 1323 findings match 1323 reviewed identities |
| `uv run ruff check .` | exit 0; all checks passed |
| `uv run ruff format --check .` | exit 0; 3270 files already formatted |
| `uv run pytest tests/test_soak_promotion_gates.py -x -q` | exit 0; 65 passed |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | exit 0; 37 passed, 6 skipped |
| `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | exit 0; 1 passed |

The historical schema-fence failure does not reproduce. The production fence
at `packages/maistro-core/src/maistro/persistence/pg_learnings.py:215` opens a
transaction and takes the advisory lock before the upgrades; the current test
independently expects the complete statement sequence. Six skipped integration
cases are not evidence of a live database concurrency run.

The task-backpressure test reaches the production router and real canonical
Run spine; `packages/maistro-server/src/maistro_server/api/tasks.py:117` maps
`RunConcurrencyExceeded` to retryable HTTP 429. It deliberately starts no
runner and therefore proves no physical-work recovery.

No tests added or modified; no inventory delta. No ledger amendment: no
unbanked identities were reported. No production code change is justified by
the supplied CI failure at the verified starting head.

## Acceptance disposition (all ten issue criteria)

| Criterion | Executed evidence / remaining gap |
| --- | --- |
| Representative RC profile covering concurrent users/Workspaces, fan-out, schedules, tools/models, Design/Canvas and workers as applicable | UNVERIFIED. Read `m3a-load-profile.md`; it explicitly identifies missing representative surfaces. No selected RC applicability decision is provided. |
| At least two deployed application replicas | UNVERIFIED for the promotion RC. Middleware tests use two ASGI instances, not deployed RC images. No deployment run performed this round. |
| Sustained saturation, queue growth, lease reclaim, retries and leaks | UNVERIFIED. Focused regressions exercise accounting and process sampling, not sustained production load. |
| No duplicate physical work across replicas | UNVERIFIED. `scripts/soak/run_soak.py:1044` cancels a queued admission-probe Run; its docstring and code explicitly exclude execution. Admission uniqueness cannot prove Attempt fencing or Goal reconciliation. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | UNVERIFIED overall; the independent-allowance counterexample is reproduced. Both cases of `tests/test_soak_promotion_gates.py:439` use real production middleware and obtain 200, 200, 429 independently on each replica for the same identity. `packages/maistro-server/src/maistro_server/api/rate_limit.py:93` constructs an in-memory limiter per middleware instance. |
| Complete telemetry with explicit thresholds | UNVERIFIED. The profile distinguishes driver loop lag from application loop lag and process-group RSS from container/worker measurements; no complete RC time series executed. |
| Active-work kill/restart, graceful drain, fencing and recovery | UNVERIFIED. Passing boot-cleanup regressions do not demonstrate active-work recovery, and the schedule probe executes no physical work. |
| Long unchanged exact-RC soak | UNVERIFIED / BLOCKED. No immutable RC/configuration designated in the lane. `scripts/soak/run_soak.py:730` always rejects host preflight as exact-RC evidence. Three passing CLI regression cases demonstrate that four-hour evidence with missing/null/preflight identity still exits 1. |
| Findings filed/reclassified before promotion | Local findings recorded here; external disposition UNVERIFIED. No GitHub mutation permitted or performed. |
| Machine/human evidence tied to image/package/commit/config hashes | UNVERIFIED for a promotion run. This report identifies the tested source head, not an immutable deployment/configuration-bound soak. |

## Handoff

**BLOCKED**, not merge-ready. The CI-repair hypothesis is disproved at the
starting head, but the actual release-evidence blockers remain. Only this
report changes this round. Existing work is preserved; no policy, ledger,
gate, authorization, runtime or scheduler changes were made.

Next: designate the exact immutable RC and supported runtime configuration;
complete representative production workloads and instrumentation for canonical
physical Attempts/recovery; resolve replica-selection rate semantics against
the acceptance contract; then execute the unchanged >=4-hour RC soak and
publish hash-bound evidence. A longer host preflight cannot satisfy this.
Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt` throughout.

Progress: checked 1 issue; done 0 acceptance-complete issues; skipped 0 issues;
validation errors 0; blocked 1. Stop this scanner-repair loop unless new actual
scanner evidence or the missing RC/deployment inputs are supplied.
