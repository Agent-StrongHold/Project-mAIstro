# Issue #860 — eed82880 repair checkpoint

## Frozen scope

- Issue: #860 only; branch `auto-860`, starting HEAD
  `43b0d2ac5cebe8941b821dfe228715a25344e2c1`; supplied base
  `435dc1937e0407ab4de198ffcced49860bb14ad2`. Both resolve locally.
- Starting worktree was clean; no incoming uncommitted work to salvage.
- Review targets: supplied dispatch context and prior result/check-3 log;
  relevant ADRs; `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, adjacent production middleware/tests,
  `scripts/check-vulture-baseline.py`, and `quality/vulture-baseline.json`.
- Write scope: this report and, only if the requested exact scan identifies
  reviewed retained identities, `quality/vulture-baseline.json`.
- Ambiguity: dispatch describes both verifier and writer. The assigned repair
  lane and mandatory local commit identify this as writer work. No GitHub
  mutations, new execution authority, or release-candidate designation.
- Current job directory contains no `check-*.log` files. Prior check log is
  historical evidence, not a result for the current HEAD.

## Progress

- Requested exact vulture scan: PASS, 1323 reviewed identities / 1323
  findings; zero unclassified. Trusted baseline resolved by the gate to
  `4aa68edc0b6b`. No ledger amendment justified.
- Historical `check-3.log` reports 24 schema DDL statements versus 21 expected.
  Re-executed `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  -x -q -rs`: 37 passed, 6 PostgreSQL-dependent skips. Failure does not reproduce.
- Captured issue has ten acceptance criteria; the profile explicitly labels
  the runner preflight-only, with no exact-RC artifact or complete workload.
  Continuing focused acceptance validation, not inventing a candidate to promote.

## Additional executed validation

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3270 files.
- `uv run pytest tests/test_soak_promotion_gates.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  -x -q -rs`: 66 passed. Includes real production middleware instances,
  child-process sampling, observed admission identities, backpressure, and
  missing/null/preflight artifact rejection.
- `uv run python scripts/check-deployment-claims.py`: PASS.
- `uv run python scripts/check-execution-lifecycles.py`: PASS, 19 classified /
  19 discovered lifecycles. Gate invocations checked against CI workflows.
- `uv run python` import/replay of `failed_promotion_checks` against
  `docs/testing/soak/evidence/m3a-round43-shakedown.json`: asserted rejection
  on `sustain_duration` and `exact_rc_artifact`. Recorded duration 420.09 s;
  promotion minimum 14400 s. Also asserted the current preflight artifact
  check returns false. This verifies rejection, not historical measurements.
- `git diff --check`: PASS before final report completion; repeated at commit.

## Architecture reconciliation

Read ADR-081 (Proposed), ADR-085 (Accepted), accepted execution runtime
ADR-081426-1f7c and lease-fencing ADR-081626-f383, plus the existing load
profile, probe tests and reachable production rate middleware. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`; Attempt is the physical
execution identity. Admission deduplication alone is not physical-work proof.
The accepted lease ADR explicitly does not define expiry takeover: do not
invent a competing reclaim authority to satisfy issue wording. ADR-085
requires principal-keyed limiting but does not prescribe a shared store;
this does not waive #860's replica-selection acceptance criterion.

## Acceptance matrix

| Issue criterion | Evidence and disposition |
| --- | --- |
| Representative RC profile | UNVERIFIED. Existing profile explicitly lacks concurrent users/Workspaces, Graph fan-out, successful model/tool traffic, Design/Canvas and background reconciliation. No designated RC applicability contract supplied. |
| At least two deployed application replicas | UNVERIFIED for RC. Executed tests use two middleware instances, not deployed candidate replicas. |
| Sustained saturation, queues, reclaim, retries, resource leaks and restart | UNVERIFIED. Historical 420.09-second evidence fails the executed four-hour gate; no long-running production soak executed here. |
| No duplicate physical work across admission, schedules and Goal reconciliation | UNVERIFIED. Passing admission/probe tests cannot prove physical Attempt effects or sustained reconciliation. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | Aggregate allowance claim falsified by executed `tests/test_soak_promotion_gates.py:439`: same identity receives `[200, 200, 429]` independently from each production middleware instance, for both authenticated and unauthenticated cases. `main.py:648` installs the middleware; `api/rate_limit.py:94` allocates its local limiter. Remaining production-load security properties UNVERIFIED. |
| Required metrics and explicit thresholds | UNVERIFIED. Child-process sampler tests pass; profile acknowledges driver loop lag is not application loop lag and missing worker/pool/long-window evidence. |
| Kill/restart during active work with drain/fencing/recovery | UNVERIFIED. No deployed replica restarted this round; process-exit and terminal Run counts alone cannot establish physical-work recovery. |
| Long-running exact RC artifact/config | BLOCKED / UNVERIFIED. No immutable RC designated. `scripts/soak/run_soak.py:730` rejects the host-process preflight, exercised by CLI regression tests. More preflight runtime cannot satisfy this criterion. |
| Findings filed/reclassified before promotion | UNVERIFIED externally. Local findings retained; no GitHub mutation performed or permitted. |
| Published machine/human evidence tied to exact hashes | UNVERIFIED for RC. Historical JSON fails the current evaluator. This report is validation evidence, not promotion evidence. |

## Handoff

Only this report changed. No production, test, ledger or gate modifications:
no reproducible CI failure justifies them. The historical schema failure is
already addressed by the three audit columns in the current test at lines
177–179. No tests added or modified, so inventory delta is zero and no new
inventory note is needed. Six DB-dependent tests skipped; live PostgreSQL
concurrency remains unverified by this round.

Verdict: BLOCKED. Next: designate immutable RC/configuration, resolve the
replica allowance acceptance contract, and provide an exact-topology runner
with physical Attempt correlation and application metrics before executing
and publishing the sustained window. No integration approval or issue closure.
Do not repeat this obsolete CI repair as if it were a missing ledger amendment.

Progress: checked 1 issue; done 0 acceptance-complete issues; skipped 0 issues;
errors 0 validation commands. Preserve report with local commit; no remote
mutation, branch deletion, or work discarded.
