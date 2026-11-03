# Issue #860 — repair validation 08fb759d

## Scope and disposition

Only issue #860 in `/home/dev/Git/wt/auto-860`, branch `auto-860`.
Starting HEAD: `a21e2921d4830b2d9d962955175ae493abd27ef1`;
assigned base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
Both resolved locally; initial worktree clean. No salvage or merge conflict.
The frozen repair scope was the cited schema-fence failure, exact vulture
scan, existing soak safeguards, and this handoff. No other issue was processed.

Read repository instructions, docs authority map, supplied issue body/latest
captured comments, prior result, and the cited historical check log. The current
job directory contained no `check-*.log` files. Historical
`98a11313167b41a98a420abfda80c292/check-3.log` failed because its schema test
expected 21 DDL statements but observed 24. The current independent ordered
expectation already contains all three validation audit columns
(`packages/maistro-core/tests/persistence/test_pg_learnings.py:175–177`).
Fresh execution passes. No test weakening or production repair is warranted.

**BLOCKED:** the brief does not designate the immutable RC artifact/configuration
that #89 would promote. Assumption: do not invent that release identity or
substitute host-process/unit results for a production soak. This is not a sync
conflict and does not call for fetching or merging a different base.

## Fresh validation

Executed in the assigned worktree, with 1200-second command timeouts:

| Command | Outcome |
|---|---|
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1323 reviewed identities / 1323 findings; zero unclassified or never-allowlist findings; checker base `4aa68edc0b6b` |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped; skipped DB checks are not production evidence |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 66 passed |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS: 3270 files already formatted |

The exact vulture arguments match `.github/workflows/quality.yml:1078`.
No unbanked identity exists to review or amend. No ledger/grant changes.
No tests added, removed, or edited; no inventory delta is needed.
Only this handoff file changes in this round. Inherited branch changes were
preserved, not discarded; these focused checks do not certify all inherited work.

## Architecture reconciliation

Read accepted ADR-081426-1f7c, ADR-081626-f383, ADR-082526-b36a and
ADR-082826-08f0. Attempt is physical execution identity. The later renewal,
reclaim and disposition decisions fill the older fencing ADR's explicitly
deferred takeover semantics. Recovery must use the canonical lifecycle seam;
terminal Run/admission counts cannot prove physical-work uniqueness.
No change to `Goal -> Graph -> Run -> NodeRun -> Attempt`, scheduler, event,
Goal-store or authorization authority was made.

## Acceptance assessment

All rows concern current exact-RC acceptance, not historical preflight claims.

| Criterion | Executed evidence / remaining gap |
|---|---|
| Representative release workload | **UNVERIFIED.** Source `scripts/soak/run_soak.py:1373–1395` uses one credential and health/task/receipt/metrics traffic without LiteLLM. `m3a-load-profile.md` records missing concurrent users/Workspaces, Graph fan-out, successful model/tools, Design/Canvas and Goal/background-worker coverage. RC applicability remains unsettled. |
| At least two deployed replicas | **UNVERIFIED.** `run_soak.py:730–741` identifies the harness as host-uvicorn preflight, not production Compose. No fresh RC replicas were deployed. |
| Sustained saturation, queue growth, reclaim, retries and leaks | **UNVERIFIED.** Sampler/accounting regressions passed; no sustained production observations were collected. |
| Physical-work uniqueness across schedule/task/Run/Attempt/Goal paths | **UNVERIFIED.** Admission-probe regressions passed. `run_soak.py:1507–1527` observes Run status/admission counts, not physical Attempt execution across those paths. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED for deployment; local allowance independence reproduced.** Executed `tests/test_soak_promotion_gates.py:439` gets `[200,200,429]` separately from each middleware instance for the same authenticated or unauthenticated identity. Production constructs an `InMemoryRateLimiter` per middleware at `packages/maistro-server/src/maistro_server/api/rate_limit.py:90–98`, registered at `main.py:648`. Local enforcement is not a cluster-wide budget. |
| Complete DB/application-loop/process/RSS/FD/queue/error telemetry and thresholds | **UNVERIFIED.** `run_soak.py:1410–1426` samples driver-loop lag, not application-loop lag. No complete RC telemetry window exists from this round. |
| Restart active work and prove drain/fencing/recovery | **UNVERIFIED.** Drain regressions passed, but exit/rejoin and terminal Run counts do not establish live Attempt recovery. No RC active-work restart was performed. |
| Long soak of the exact promoted RC/configuration | **BLOCKED / UNVERIFIED.** No designated artifact/configuration. The executed `test_four_hour_preflight_cannot_pass_cli` at `tests/test_soak_promotion_gates.py:103` rejects otherwise-passing four-hour host evidence. `preflight_artifact_check` always returns false and is wired into thresholds at `run_soak.py:1552`. |
| Findings filed/reclassified before promotion | **UNVERIFIED externally.** Local findings are recorded here; no GitHub mutation was performed or authorized. |
| Machine/human soak evidence bound to image/package/commit/config hashes | **UNVERIFIED for RC.** This report binds fresh local validation to the starting source head, not to an RC deployment. No promotion evidence pack was generated. |

## Handoff

The historical CI failure does not reproduce; the explicitly requested scanner
passes. A cosmetic code edit or ledger amendment would manufacture work rather
than address evidence. Release acceptance still requires owner-designated
immutable RC/configuration, workload applicability, resolution of rate-budget
semantics through existing policy authority, and a long production soak with
physical Attempt/recovery observations and complete telemetry. Any runtime or
configuration change requires a new soak. Do not repeat short host runs as a
substitute or retry this lane on the stale check log without new inputs.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "exact-RC prerequisites and production soak"}`.
Local commit completes the writer handoff only, not issue acceptance or integration approval.
