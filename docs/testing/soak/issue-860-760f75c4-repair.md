# Issue #860 — repair checkpoint 760f75c4

## Frozen scope

- Issue: #860 only; branch `auto-860`.
- Starting HEAD: `cbf228f2167e8653f27601cfa4d2ec70698c0032` (verified).
- Supplied base: `b1f17b8d6246d347f617fb2c0b969e6798e0152b` (resolved by diff).
- Initial worktree clean; no incoming uncommitted changes to salvage.
- Inspect: supplied dispatch snapshot and prior result/check logs; repository instructions;
  relevant execution/deployment ADRs; `scripts/soak/run_soak.py`, its promotion tests,
  load profile and preserved evidence; CI vulture checker/workflow and any identities
  it actually reports. No GitHub refresh or mutations.
- Candidate changes: this report; `quality/vulture-baseline.json` only if the exact
  requested scanner produces reviewed retained identities; soak implementation/tests
  and inventory note only if a demonstrated local defect warrants repair.
- Ambiguity: assignment asks for CI repair and complete issue acceptance. Treat
  these separately; green static checks cannot substitute for exact-RC production
  soak evidence. No new production authority or unrelated rate-limiter redesign.
- Current job directory contains no `check-*.log` at initial snapshot. Inspect the
  explicitly supplied previous failed log instead; execute fresh checks locally.

## Progress

- Confirmed starting HEAD and clean worktree.
- Exact requested vulture scan PASS: 1332 findings, 1332 reviewed identities,
  zero unclassified/forbidden. No ledger amendment is justified by current evidence.
- Historical `98a113.../check-3.log` reports 24 observed schema statements against
  21 expected. The current test explicitly covers the three additional validation
  audit columns. Fresh package-scoped run: 37 passed, 6 skipped. Failure not reproduced.
- Read soak profile and adjacent promotion tests. Profile explicitly excludes
  complete representative traffic and exact production topology. Acceptance remains
  open; executed middleware tests confirm same-identity independent replica budgets.
- Fresh lint/format, focused tests (73 passed), inventory (17 suites / 28173
  identities), and backlog gates PASS. Production registers RateLimitMiddleware
  at `maistro_server/main.py:648`; its limiter is instantiated per process.
- New local evidence to repair within frozen scope: `run_soak.py:1495-1511`
  promises 429-with-Retry-After and non-vacuous admission evidence, but counts
  every 429 and allows zero accepted tasks. Add a regression and a focused
  evidence-accounting fix; this does not establish production soak acceptance.
- Reproduced the defect after behavior-preserving extraction of the existing H6
  formula: `uv run pytest tests/test_soak_promotion_gates.py -q -k sustained_admission`
  yielded 5 failed / 4 passed. Failing cases: all backpressure, missing/blank
  Retry-After, acceptance only during kill, and a kill-window Retry-After hiding
  an outside-window rejection. Failures were `True is False`, not missing APIs.
- Fixed the real worker to record nonblank Retry-After on task responses under
  the same stats lock; kill/rejoin snapshots now carry those counters. H6 uses
  only outside-window qualified 429s and requires at least one outside-window
  202. Main runner calls the extracted evaluator. No production scheduling,
  admission, or rate-limit behavior changed; no gate weakened.
- Post-fix focused tests PASS: 82 passed. Added nine cases and an inventory-delta
  note. Formatted the two Python files; `git diff --check` PASS.

## Validation commands and outcomes

Commands ran in the assigned worktree with 1200-second validation timeouts.

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS before and after repair: 1332 reviewed / 1332 findings, no unclassified or forbidden. Matches `.github/workflows/quality.yml:1013-1016`. No ledger edit needed. |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped. Historical schema failure absent; skipped integrations do not prove live DB fencing. |
| `uv run pytest tests/test_soak_promotion_gates.py -q -k sustained_admission` | Before fix: 5 failed, 4 passed, confirming actual false-positive verdicts in the extracted original calculation. |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | Before additions: 73 passed. After fix: 82 passed, including all nine new cases. |
| `uv run ruff format scripts/soak/run_soak.py tests/test_soak_promotion_gates.py` | One file reformatted. |
| `uv run ruff check .` | PASS before and after repair. |
| `uv run ruff format --check .` | PASS before and after repair, 3105 files. |
| `uv run python scripts/check-suite-inventory.py` | PASS: 17 suites, 28182 unique identities after repair (+9); zero duplicate evidence. |
| `uv run python scripts/check-backlog-consistency.py` | PASS, 168 items, before and after repair. |
| `uv run python -` importing current runner and evaluating preserved `m3a-round6-shakedown.json` | Asserted both `sustain_duration` and `exact_rc_artifact` fail. Historical duration 90.43 seconds; current preflight artifact check returns false. This is re-evaluation, not a fresh soak. |
| `git diff --check` | PASS. |

## Architecture reconciliation

Read accepted ADR-081226-69ee (Graph/Run/NodeRun/Attempt authority), accepted
ADR-081626-f383 (Run-store fencing; expiry takeover explicitly not yet defined),
and accepted ADR-085 (principal-keyed rate limits). ADR-081 is Proposed, not an
accepted waiver of production-artifact evidence. The issue's reclaim wording
cannot authorize an alternate scheduler or implicit takeover. This repair changes
only load-evidence accounting; it preserves Goal -> Graph -> Run -> NodeRun ->
Attempt and every existing production authority. It does not turn a documented
process-local budget into proof of the issue's stronger replica-selection claim.

## Acceptance review (all ten criteria)

| Criterion | Executed evidence / disposition |
| --- | --- |
| Representative RC load profile | UNVERIFIED. `m3a-load-profile.md:153-172` lists missing user/Workspace population, fan-out, successful model/tool, Design/Canvas and background-work coverage. Selected RC applicability has not been supplied/proven. |
| At least two production application replicas | UNVERIFIED. `deploy/docker-compose.prod.yml:26-78` defines two services; middleware tests use two ASGI instances, not two running RC containers. No new deployment executed. |
| Sustained saturation, queue growth, reclaim/retry, memory/fd/process leaks and restart | UNVERIFIED. Sampler tests exercise a real uv child, not sustained application load. Historical 90.43-second evidence fails minimum duration. Reclaim must respect accepted fencing authority. |
| No duplicate physical work across schedule/task/Run/Attempt/Goal operations | UNVERIFIED. Admission-receipt and backpressure tests pass, but they are not a physical-work or Goal-reconciliation oracle. New H6 tests prevent zero accepted work from falsely passing an admission evidence check. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | NOT MET by executed production-middleware tests at `tests/test_soak_promotion_gates.py:439-488`: same identity gets `[200,200,429]` independently on each instance. Production wires that middleware at `maistro_server/main.py:648`. Broader sustained security/degraded acceptance remains UNVERIFIED. |
| Complete metrics and explicit thresholds | UNVERIFIED. Sampler and accounting tests pass. H6 now rejects absent/blank Retry-After and all-backpressure traffic, with kill-window exclusion. Driver loop latency is not application event-loop latency; complete production pool/worker/error thresholds remain unproven. |
| Active-work kill/restart with drain/fencing/recovery | UNVERIFIED. Boot-cleanup tests pass; no live physical Attempt correlation or recovery run was executed. |
| Long-running exact RC artifact/configuration soak | NOT MET by evaluated evidence: 90.43 seconds and host-process preflight. Current `preflight_artifact_check` rejects this topology even after four hours. Code changed in this round; prior runs cannot certify it. |
| Findings filed/reclassified to earliest invariant before promotion | UNVERIFIED. Backlog consistency passes; external filing completeness not established and GitHub mutations prohibited. This report preserves the new H6 false-positive finding and its repair. |
| Human/machine soak evidence tied to exact image/package/commit/config hashes | UNVERIFIED. Existing preflight artifacts are preserved, not newly generated promotion evidence. This report is local validation/handoff only. |

## Changed files and remaining prerequisites

- `scripts/soak/run_soak.py`: observed Retry-After counters, kill-window isolation,
  and non-vacuous H6 evaluation wired into the runner.
- `tests/test_soak_promotion_gates.py`: nine HTTP-worker/evaluator regressions.
- `docs/testing/inventory-notes/m3a-860-sustained-admission-evidence.md`: +9 delta.
- This report: frozen scope, regression evidence, fresh validation and acceptance.

**BLOCKED for issue acceptance**, despite the completed local repair. Do not
repeat the obsolete schema/vulture repair without a new failing command. Next:
select immutable RC image/configuration and representative workload applicability;
resolve replica-budget acceptance and physical-work/recovery oracles; then run
and publish a fresh >=4-hour exact-artifact soak. No new soak was run here.
Retry-After accounting verifies nonblank presence (as the existing profile
requires), not HTTP-date/numeric validity. A positive H6 is admission evidence,
not proof of physical execution or representative sustained workload.

Progress: {checked: 1, done: 0, skipped: 0, errors: 0,
next: exact-RC and production acceptance prerequisites}. One local defect repaired;
no integration approval, remote mutation, issue closure, or discarded salvage.
