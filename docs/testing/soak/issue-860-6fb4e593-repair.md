# Issue #860 — job 6fb4e593 repair checkpoint

## Frozen scope

Only issue #860, branch `auto-860`, starting head
`a912da4c86c6fa2c0db59c39f614aa83e236640a`, supplied base
`140e881808475a4dbec063d19740e1e50c340905`. Starting worktree clean.
No GitHub mutations, no other issues or PRs processed.

Repair targets frozen to the supplied findings: the exact vulture gate and
`quality/vulture-baseline.json` only if its executed output warrants a change;
suite inventory for `tests/test_soak_promotion_gates.py`; soak production behavior
in `scripts/soak/run_soak.py`, server rate limiting/tasks and adjacent tests;
`docs/testing/soak/m3a-load-profile.md` and supplied evidence. This checkpoint
records validation and unresolved acceptance rather than inventing promotion evidence.

Ambiguity: prompt includes verifier and writer directions. The explicit repair
assignment and mandatory local commit select writer mode. No `check-*.log` files
were present in the supplied job directory at initial inspection; execute checks
locally instead. Full dispatch is a captured evidence snapshot, not authority to
change gates or broaden scope.

## Executed checkpoint 1

- Exact requested vulture command exited 0: 1322 findings / 1322 reviewed
  identities, zero unclassified or never-allowlist findings. No ledger amendment
  is justified by this scan; the requested unbanked-identity defect is not
  reproduced. Gate reported its own base as `2f56be40ad24`.
- `uv run ruff check .` exited 0.
- `uv run ruff format --check .` exited 0 (3306 files).
- Prior result was read from the supplied job: it reported BLOCKED, not acceptance.
- Read root instructions, load profile, accepted ADR-085, ADR-081426-1f7c and
  ADR-081626-f383. Physical execution remains Attempt-owned; lease-expiry
  takeover cannot be invented by this harness (fencing ADR explicitly leaves
  reclaim authority to a later contract). Existing per-replica rate-limit
  allowances do not prove #860's stronger replica-selection criterion.

Logs: `/tmp/860-6fb4-{vulture,ruff,format}.log`.
## Executed checkpoint 2

- Root suite inventory failed: expected 5353, collected 5354, no duplicate
  evidence. This reproduces the supplied +1 discrepancy; do not bank a guessed
  delta. Provenance review in progress, bounded to two investigations.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q`
  passed: 92 tests. These exercise the driver and real middleware/route seams,
  not a production deployment. In particular the replica-selection tests assert
  that both independent limiters allow `[200, 200, 429]` for the same identity.
- `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`
  passed: 1 test, HTTP backpressure contract only.
- Confirmed the vulture invocation matches `.github/workflows/quality.yml`.

Logs: `/tmp/860-6fb4-{inventory,soak-tests,server-tests}.log`.
## Final validation and bounded disposition

- Loaded the current driver and executed `failed_promotion_checks` against
  `evidence/m3a-round30-shakedown.json`: actual duration 420.08 seconds;
  failures exactly `sustain_duration`, `exact_rc_artifact`. Executed
  `preflight_artifact_check`: `ok=False`, `host-uvicorn-preflight`.
- `uv run pytest tests/test_soak_promotion_gates.py --collect-only -q`:
  84 collected. The nine existing soak-specific inventory notes total exactly
  +84 (2 + 27 + 5 + 12 + 6 + 4 + 9 + 7 + 12). This file did not exist at the
  supplied develop base. Its additions are already accounted for; another +1
  note against this file would be unjustified.
- Inventory discrepancy provenance: **UNRESOLVED** after the bounded review.
  No test added/removed in this job, no inventory change, no baseline edit.
  The reproduced root-suite discrepancy remains a failing gate, not a waiver.
- `uv run pytest packages/maistro-server/tests/api/test_rate_limit.py -x -q`:
  26 passed. Log `/tmp/860-6fb4-rate-tests.log`.
- `uv run python scripts/check-deployment-claims.py`: PASS. This only resolves
  documented component/backend names, not deployment or load behavior.
  Log `/tmp/860-6fb4-deployment.log`.

## Acceptance matrix (no integration approval)

| Issue criterion | Executed evidence / disposition |
|---|---|
| Representative RC workload | **UNVERIFIED**. Profile lines 167–183 explicitly lack concurrent users/Workspaces, Graph fan-out, successful tools/models, Canvas and background reconciliation. |
| At least two application replicas | **UNVERIFIED** for the exact RC. Two real middleware instances in passing ASGI tests and static boot contracts are not two deployed production replicas. |
| Sustained saturation, queues, reclaim, retry and leaks | **UNVERIFIED**. Evaluated historical window is 420.08 seconds, not the required 14400; no long-window production observation executed. |
| No duplicate physical schedule/task/Run/Attempt work; Goal reconciliation | **UNVERIFIED**. Admission identities do not count physical effects. Profile lines 215–217 acknowledges that one raced occurrence is cancelled without execution. Accepted fencing ADR does not authorize inventing reclaim behavior. |
| Concurrency/security/degraded behavior cannot be bypassed by replica selection | **NOT PROVEN**. Executed tests at `tests/test_soak_promotion_gates.py:483–526` reproduce independent allowances through production middleware; `rate_limit.py:32–37,93` implements that scope. Passing local limiter tests cannot satisfy the stronger criterion. |
| All required telemetry with explicit thresholds | **UNVERIFIED** under sustained production traffic. Profile distinguishes driver-loop lag from application-loop lag and does not prove saturation/worker coverage. |
| Active-work replica kill/restart with drain/fencing/recovery | **UNVERIFIED**. Boot cleanup tests pass, but process exit/rejoin and terminal Run counts alone do not establish no lost or duplicated physical work. |
| Long soak of exact RC artifact/config | **NOT MET** by evaluated evidence: current evaluator rejects duration and artifact. Current driver always marks its host-process topology non-RC (`run_soak.py:744–755`). No new soak run or immutable promoted artifact/configuration established in this job. |
| Findings filed/reclassified to earliest milestone invariant | **UNVERIFIED** externally. Local findings preserved here; GitHub mutation prohibited. |
| Machine/human evidence bound to exact promoted hashes | **UNVERIFIED**. Existing JSON/Markdown is historical preflight evidence, not proof for this head and production image/configuration. |

## Handoff

**BLOCKED**, not merge-ready. The explicitly assigned vulture defect is not
reproduced; do not amend a passing multiset ledger merely to manufacture a fix.
Only this report changed. No scheduler, execution authority, authorization,
runtime config, tests, historical evidence or quality policy changed.

Next: identify the root-suite +1 test's actual provenance before recording a
scoped inventory correction; supply the selected immutable RC image/config and
complete a representative production runner/workload, then collect a new
four-hour soak with physical-work/Goal/fencing and required telemetry evidence.
The documented per-replica budget requires an explicit supported-policy
resolution; do not label its current behavior replica-selection-resistant.

Progress: checked 1 issue; completed 0 acceptance-complete issues; skipped 0;
1 reproduced deterministic gate failure (inventory). Validation is complete
for this bounded repair, but no evidence-supported production fix was found.

