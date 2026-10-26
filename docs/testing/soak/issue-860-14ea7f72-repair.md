# Issue #860 — repair checkpoint (job 14ea7f72)

## Frozen scope

- Issue #860 only; branch `auto-860`, starting HEAD
  `e9cabc1c0569af60cef242de64cd6f2c10287003`, supplied base
  `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
- Starting worktree clean; no incoming edits to salvage.
- Inputs: supplied dispatch-context.json, previous result 5e62acbd,
  previous failed check 98a11313/check-3.log. Current job contains no check logs.
- Inspect repository instructions, relevant execution/soak ADRs, existing soak
  runner and promotion tests, server admission behavior, and exact vulture gate.
- Candidate edits limited to this report and evidence-backed fixes to those
  files (plus inventory notes for test changes, and the explicitly permitted
  vulture ledger only if the exact scan identifies retained identities).
- Ambiguity: writer instructions apply because this is an assigned repair.
  No develop synchronization conflict is present; no fetch/merge is indicated.

## Progress

Verified starting HEAD and clean status. Prior BLOCKED result is evidence to
recheck, not acceptance proof. No production soak has been executed this round.

Exact vulture command completed successfully: 1,322 reviewed identities matched
1,322 findings; zero unclassified and never-allowlist findings. Log:
`/tmp/860-14ea-vulture.log`. No ledger amendment is supported by this evidence.
Historical check-3 failure expected 21 DDL statements versus 24; current test
already includes the three validation-audit columns. Fresh execution passed:
`uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
reported 37 passed, 6 skipped. Log: `/tmp/860-14ea-schema.log`.
Skipped tests do not establish live database safety.
The guessed ADR filename `ADR-081626-f383-physical-work-fencing.md` was not
found; skipped. Resolved actual filename is `ADR-081626-f383-execution-lease-fencing.md`.

Read repository instructions, documentation authority hierarchy, and accepted
ADRs 081226-69ee, 081226-a66b, 081426-1f7c, 081626-f383. Canonical
Goal -> Graph -> Run -> NodeRun -> Attempt ownership must remain unchanged.
The fencing ADR explicitly leaves lease-expiry takeover/recovery supersession
undefined. The issue's reclaim requirement cannot authorize a new scheduler or
lease authority; that acceptance dependency remains unresolved.

Inspected the existing load profile, promotion evaluator, production task
router and rate limiter, and adjacent promotion tests. The runner explicitly
returns `exact_rc_artifact.ok=false` (`scripts/soak/run_soak.py:744`). The profile
lists missing representative users/Workspaces, fan-out, successful model/tool
calls, and worker/Goal coverage. No supplied immutable promotion RC selection
resolves those gaps. A longer run of this emulator would still not satisfy AC8.

## Completed validation

Commands ran in the assigned worktree with 1,000-second timeouts:

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1,322 accounted-for findings |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 73 passed |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS: 3,301 files already formatted |

Additional logs: `/tmp/860-14ea-{soak-tests,ruff,format}.log`.
The existing tests meaningfully probe production seams, but not an exact-RC
multi-process deployment:

- `tests/test_soak_promotion_gates.py:439` exercises real rate middleware:
  the same identity receives [200, 200, 429] independently on both instances.
  Replica selection therefore increases aggregate allowance. This agrees with
  the explicit local-scope contract in `api/rate_limit.py:31`, not AC5's
  stronger no-replica-bypass claim. No alternate authorization path was added.
- `tests/test_soak_promotion_gates.py:564` uses the production task router and
  a shared canonical admission spine: receipt GET returns 200 locally and 404
  on the peer. `api/tasks.py:146` reads the process-local queue. This is not
  evidence of durable cross-replica receipt availability or physical execution.
- The server backpressure test verifies 202 below capacity, 429 plus
  Retry-After at capacity, principal isolation, and admission after release.
  It deliberately starts no runner, so cannot prove active-work recovery.
- `deploy/docker-compose.prod.yml:11` identifies itself as a reference artifact
  requiring pinned image digests. The file declares two replicas but is not a
  selected immutable RC; no deployment was started or modified in this round.

## Acceptance matrix

| # | Criterion | Executed evidence / remaining gap |
| --- | --- | --- |
| 1 | Representative RC profile | UNVERIFIED: inspected profile explicitly lacks multi-user/Workspace traffic, Graph fan-out, successful tool/model and Design/Canvas/worker coverage; no complete selected-RC workload executed |
| 2 | At least two deployed replicas | UNVERIFIED: inspected Compose declaration and passed ASGI seam tests, not a deployed replica soak |
| 3 | Sustained saturation, queue/reclaim/retries/leaks | UNVERIFIED: no sustained load run; accepted fencing ADR does not define reclaim authority |
| 4 | No duplicate physical work, including Goal reconciliation | UNVERIFIED: admission and receipt tests do not execute physical Attempts or sustained Goal reconciliation |
| 5 | Replica-resistant security/degraded behavior | UNVERIFIED as a whole: reproduced independent per-replica allowances; canonical capacity backpressure test passes |
| 6 | Production telemetry with thresholds | UNVERIFIED: profile has thresholds, but no fresh RC pool/lock/application-loop/worker/RSS/descriptor/error series |
| 7 | Active-work kill/restart/drain/fenced recovery | UNVERIFIED: no active-work restart experiment; process rejoin or terminal Run counts alone cannot prove recovery |
| 8 | Long exact-RC soak, rerun after changes | UNVERIFIED: preflight artifact gate rejects this runner; no >=4-hour selected-RC soak executed |
| 9 | Findings classified to earliest broken invariant | UNVERIFIED for completeness: no completed promotion soak; existing findings and new validation limits recorded here, no GitHub mutations |
| 10 | Machine/human evidence bound to exact hashes | UNVERIFIED for promotion: this report records starting HEAD and local validation, not a hash-bound production soak |

## Handoff

**BLOCKED**. Only this report changed. No production, test, gate, ledger or grant
changes were justified by the fresh results; no suite count delta, so no new
inventory note is required. Historical artifacts and implementation preserved.
The historical failure is resolved on the assigned starting HEAD, not repaired
by this round. Passing local checks is not integration approval.

Next needs an identified immutable RC/configuration and production-topology
workload, resolution of the replica-budget/reclaim-contract gaps through the
canonical owners, followed by the long soak with Attempt-correlated physical
work, active-work recovery and complete telemetry. Repeating this same CI-only
repair does not resolve those dependencies.

Progress: checked 1 issue, done 0 acceptance sets, skipped 0 issues, errors 0
validation commands. `git diff --check` passed; the only worktree change is
this report, committed locally as `docs: record issue 860 validation blockers (14ea7f72)`.
