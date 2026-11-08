# Issue #860 — repair checkpoint (4ccdf5fc)

## Frozen scope

Only issue #860, branch `auto-860`, starting HEAD
`b8dac6fe125d9110246f4b628aa0b36aa7812dac`, supplied develop base
`3c761d14db944a727fa0744444bc67cfe36d49f7`. Starting worktree clean.
No ref updates or GitHub mutations.

Inputs frozen to this job's dispatch context, prior result `6b497183`, and
reported historical `98a11313/check-3.log`. Review surfaces: repository
instructions, applicable execution ADRs, `scripts/soak/run_soak.py`,
`tests/test_soak_promotion_gates.py`, core learnings persistence/test,
server concurrency backpressure/test and production rate middleware, load
profile/evidence documentation, and exact gate scripts/workflow arguments.
Potential edits limited to reproduced failures on those surfaces, explicitly
permitted `quality/vulture-baseline.json` retained-identity repair if needed,
required inventory notes if tests change, and this checkpoint.

Initial evidence: no check-*.log files in current job directory. The supplied
historical failure is a schema-fence test expecting 21 DDL statements but
observing 24. Prior result is BLOCKED on exact-RC soak acceptance. Ambiguity:
CI repair may already be complete, while actual deployment acceptance is not.
Assumption: reproduce the named failure and exact scanner before proposing any
code/ledger edits. Never manufacture debt or treat unit tests as a deployed soak.

## Validation checkpoint

Fresh exact vulture gate passed: 1323 findings / 1323 reviewed identities,
zero unclassified or never-allowlist findings. Checker-selected base was
`4aa68edc0b6b`; no ledger amendment is justified. Historical schema failure
also does not reproduce: the current independent ordered DDL assertion includes
the three audit columns at `test_pg_learnings.py:175-177`, matching production
`pg_learnings.py:116-118`. No test weakening or speculative repair.

Executed commands (logs in this job directory):

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS (`worker-vulture.log`).
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py -x -q`: 102 passed, 6 skipped (`worker-core-soak-tests.log`). Skips do not establish database acceptance.
- `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: 1 passed (`worker-server-tests.log`).
- `uv run ruff check .`: PASS (`worker-ruff-check.log`).
- `uv run ruff format --check .`: PASS, 3270 files (`worker-ruff-format.log`).

Read repository instructions and accepted ADR-081426-1f7c, ADR-081626-f383,
ADR-082526-b36a and ADR-082826-08f0. Reconciliation: later lease renewal/reclaim
and recovery disposition contracts resolve the older fencing ADR's deferral;
Attempt is physical-work identity, and recovery must use the canonical
lifecycle seam. No competing execution or authorization authority is proposed.

## Acceptance review

Source inspections below were performed this round; historical soak claims are
not treated as fresh acceptance. The supplied source head is not a designated
immutable RC image/configuration. No production deployment or long soak was run.

| Issue acceptance | Fresh evidence / remaining gap |
|---|---|
| Representative RC profile | **UNVERIFIED.** `run_soak.py:1373-1395` uses one credential and health/task/receipt/metrics traffic, with no LiteLLM. `m3a-load-profile.md` explicitly lists missing users/Workspaces, Graph fan-out, successful model/tool, Design/Canvas and Goal/background-worker coverage. Selected-RC applicability is not established. |
| At least two application replicas | **UNVERIFIED for RC.** Host processes are preflight only (`run_soak.py:730-741`), not two observed promoted-image replicas. |
| Sustained saturation, queue growth, lease/retry, memory/descriptor/process leaks | **UNVERIFIED.** Sampler regressions executed successfully, but no sustained deployment observations collected this round. |
| No duplicate physical work across schedule/task/Run/Attempt/Goal paths | **UNVERIFIED.** `run_soak.py:1507-1527` checks Run status/admission counts, not physical Attempt execution. Admission-probe tests passed; admission uniqueness alone does not prove physical-work uniqueness. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED for deployment; independent allowances reproduced.** Executed `test_replica_selection_has_an_independent_production_allowance` (`tests/test_soak_promotion_gates.py:439`) obtains `[200,200,429]` on each middleware instance for the same authenticated/unauthenticated identity. Production registers that middleware at `maistro_server/main.py:648`; `api/rate_limit.py:90-98` allocates its local limiter. Documented N-times-local allowance is not proof of deployment-wide non-bypass. |
| Full PostgreSQL/application-loop/process/RSS/FD/queue/error telemetry and thresholds | **UNVERIFIED.** `run_soak.py:1410-1426` samples driver-loop lag, not application-loop lag. No complete required deployment telemetry collected. |
| Kill/restart during active work, graceful drain/fencing/recovery | **UNVERIFIED.** Drain/CLI regressions passed; no live Attempt kill/restart performed. Process exit/rejoin and terminal Run counts are insufficient. |
| Long soak of exact promoted RC/configuration | **BLOCKED / UNVERIFIED.** `preflight_artifact_check` always returns false (`run_soak.py:730-741`), wired into evaluated thresholds at line 1552. Executed `test_four_hour_preflight_cannot_pass_cli` (`test_soak_promotion_gates.py:103`) rejects otherwise-passing four-hour host evidence. No designated immutable RC deployment was supplied. |
| Findings filed/reclassified before promotion | **UNVERIFIED externally.** This report records local evidence; no GitHub mutations authorized or performed. |
| Machine/human evidence tied to image/package/commit/config hashes | **UNVERIFIED for RC.** Fresh check logs and this report are not an RC soak evidence pack. |

The backpressure regression also exercises the actual task router with canonical
Run admission: two requests accepted, full principal ceiling returns retryable
429, another principal remains admissible, and freeing a slot restores admission.
It does not certify concurrent deployed execution.

## Disposition and handoff

**BLOCKED for issue acceptance.** CI triage completed; named failure is stale at
this HEAD, and no scanner debt exists to repair. Vulture arguments match
`.github/workflows/quality.yml:1078-1081` and `vulture-ratchet.yml:82-85`.
No test additions/removals, so no inventory delta. No runtime, gate, ledger,
grant or deployment edits. Sole changed file is this report; commit is a local
writer handoff, not integration/promotion approval.

Next prerequisite: designate the immutable RC image and runtime configuration,
settle representative workload applicability and deployment rate-budget semantics
through existing policy authority, then execute the long production soak with
physical Attempt and recovery observations plus complete telemetry. Repeating
short host runs or CI checks cannot close these gaps.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "exact-RC deployment/workload prerequisites; issue acceptance blocked"}`.
