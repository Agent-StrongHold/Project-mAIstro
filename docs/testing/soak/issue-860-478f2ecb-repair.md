# Issue #860 — bounded repair validation (job 478f2ecb)

## Scope and disposition

**BLOCKED — no promotion approval.** Checked only issue #860 in the assigned
`auto-860` worktree, starting at `88242bca923dc10e283c5f4a56755de7886eaa03`,
with supplied develop base `140e881808475a4dbec063d19740e1e50c340905`.
The starting tree was clean. No driver `check-*.log` files were supplied in
this job directory; the checks below were executed locally, not inferred from
prior claims. Read the captured dispatch issue body and prior result.

The explicit writer/repair assignment selects writer mode despite the generic
verifier directions. The requested vulture defect **does not reproduce**:
1,322 reviewed identities match 1,322 findings, zero unclassified identities.
There is no evidence-supported ledger amendment or dead-code deletion to make.
Do not repeatedly dispatch this same passing scan as an unbanked-identity repair.

Only this report changes. No tests were added or removed, so no inventory delta
is warranted for this job. No quality policy, historical evidence, runtime
configuration, execution authority or authorization path was changed.

## Executed checks

Logs are in `/home/dev/maistro/jobs/478f2ecb1755415aa1de7da03da56da9/`.
All commands used long timeouts.

| Command | Actual outcome | Log |
|---|---|---|
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1322/1322, gate reports base `2f56be40ad24` | `check-vulture-repair.log` |
| `uv run ruff check .` | PASS | `check-ruff-repair.log` |
| `uv run ruff format --check .` | PASS; 3306 files | `check-format-repair.log` |
| `uv run python scripts/check-suite-inventory.py --suite tests` | FAIL; expected 5353, collected 5354, zero duplicate evidence | `check-inventory-repair.log` |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q` | PASS; 92 tests | `check-soak-tests-repair.log` |
| `uv run pytest packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | PASS; 27 tests | `check-server-tests-repair.log` |
| `uv run python scripts/check-deployment-claims.py` | PASS; documented component/backend existence only | `check-deployment-repair.log` |
| `uv run python` loading current `run_soak.py` and calling `failed_promotion_checks` on round30 evidence | Evaluator rejects `sustain_duration` and `exact_rc_artifact`; 420.08 seconds. Current `preflight_artifact_check()` returns `ok=False`. Assertions confirming these results pass. | `check-evidence-repair.log` |

Inventory provenance remains **UNRESOLVED** after bounded review of changed root
tests and their inventory notes. The branch's existing CI-split removal and
soak additions must not be reconciled with a guessed +1. No test was deleted,
duplicated or renamed to force the count. The failed inventory check remains a
blocker, not an accepted exception.

## Architecture and acceptance evidence

Read accepted ADR-085 (principal-keyed request limits), ADR-081426-1f7c
(Attempt identity owns physical execution), and ADR-081626-f383 (canonical-store
lease/fencing authority). The latter explicitly does not itself define expiry
reclaim authority. This issue cannot authorize a parallel scheduler or invent
reclaim behavior in the load driver. The existing documented process-local
limiter contract is not proof of the stronger replica-selection criterion.

| Acceptance criterion | Evidence / remaining gap |
|---|---|
| Representative RC users/Workspaces, request mix, Graph fan-out, schedules, tools/models, Canvas and workers | **UNVERIFIED**. `m3a-load-profile.md:167–183,215–217` explicitly leaves these representative production surfaces incomplete. Passing driver tests do not supply that workload. |
| At least two production application replicas | **UNVERIFIED**. Boot contracts and two ASGI middleware instances were tested; no exact-RC deployment was exercised in this job. |
| Sustained saturation, queue growth, reclaim, backoff, memory/fd/process leaks, restart observations | **UNVERIFIED**. Executed evidence evaluation rejects the 420.08-second historical window against the 14400-second minimum. No new long-running load was executed. |
| No duplicate physical schedule/task/Run/Attempt work, Goal reconciliation | **UNVERIFIED**. `m3a-load-profile.md:215–217` describes one cancelled schedule probe, not sustained scheduling or physical Attempt effects. |
| Concurrency/security/degraded enforcement cannot be bypassed by replica selection | **NOT PROVEN**. Passing `tests/test_soak_promotion_gates.py:479–527` executes production middleware and reproduces `[200, 200, 429]` independently on both replicas for the same identity. `rate_limit.py:32–37,93` documents/constructs the independent allowances. |
| Required DB/query/lock, application-loop, worker/process/RSS/fd, queue/error/timeout telemetry and thresholds | **UNVERIFIED** at production-soak grade. Profile distinguishes driver-loop measurements from application-loop latency and acknowledges incomplete saturation/worker coverage. |
| Kill/restart during active work with drain/fencing/recovery | **UNVERIFIED**. Passing boot cleanup tests and historical rejoin counters cannot establish absence of lost/duplicated physical work. |
| Long-running soak of exact promoted artifact/configuration | **NOT MET** by evaluated evidence. Current `run_soak.py:744–755` unconditionally identifies its host-process topology as non-RC. Neither a longer emulator run nor passing unit tests changes artifact identity. |
| Findings filed/reclassified to earliest milestone invariant | **UNVERIFIED** externally; findings preserved locally. No GitHub mutations performed. |
| Machine/human soak evidence bound to exact promoted hashes | **UNVERIFIED**. Historical JSON/Markdown remains preflight evidence, not evidence for this head's promoted image/configuration. |

## Handoff

Supply the selected immutable RC artifact/configuration and a production-path
runner/workload covering the outstanding surfaces before scheduling the required
four-hour soak. Resolve the replica-budget acceptance mismatch through the
existing security policy/authority, not by describing local 429s as cluster-wide
protection. Separately identify the actual root-suite inventory discrepancy
before writing a scoped correction. Do not amend a passing vulture multiset or
weaken promotion gates to conceal these blockers.

Progress: checked 1 issue; acceptance-complete 0; skipped 0; reproduced failing
validation commands 1 (inventory). Local validation/reporting complete; issue
acceptance remains blocked. This report is committed locally for handoff only.
