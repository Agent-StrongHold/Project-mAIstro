# Issue #860 — repair job 28482ebb

## Frozen scope and initial state

- Assigned issue only: #860; writer on `auto-860` in `/home/dev/Git/wt/auto-860`.
- Starting HEAD: `5df89071cce3a571a3432a678d97e4c52f664aac`; supplied develop base: `2ef76025e50b226a109d06bca0ae67fa14689afe`.
- Initial working tree clean; no salvage needed.
- Snapshot: inspect repository instructions, relevant execution/deployment/rate-limit ADRs, `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`, production rate middleware, the load profile and round6 evidence. Run the assigned exact vulture gate; edit only genuinely evidenced dead code or reviewed retained ledger identities if it reports any, plus this validation record. Existing package regressions are included in focused validation. No new workload or authority is assumed.
- Job directory contained no `check-*.log` files at initial inspection. Validation will be executed locally rather than relying on earlier claims.
- Prior result read: job 848814a4 reported BLOCKED. This is a claim to revalidate, not acceptance evidence for this head.
- Ambiguity: this is a writer repair assignment despite generic verifier wording; proceed with focused validation and a local commit. No develop conflict exists in the clean starting tree; no fetch/merge is necessary.

## Results

- Exact assigned vulture command passed: 1,342 findings matched 1,342 reviewed identities, zero unclassified/never-allowlist. CI arguments confirmed in `.github/workflows/quality.yml:963-966` and `vulture-ratchet.yml:82-85`. No unbanked identities exist to amend; changing the ledger would be speculative.
- Architecture reviewed: accepted ADR-081626-f383 (canonical Attempt leases), ADR-082426-82c7 (occurrence claim on the Run), ADR-085 (principal rate limits). ADR-081 is Proposed, not an accepted deployment override. Preserve Goal → Graph → Run → NodeRun → Attempt; a claim-only race is not proof of physical exactly-once execution.
- Current production middleware still creates a process-local limiter; the profile expressly excludes multiple representative workloads and the host runner always rejects exact-RC promotion. No four-hour host rerun can resolve that artifact mismatch.

## Executed validation

All commands were run in the assigned worktree with 1,200-second timeouts:

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1,342 exact reviewed identities, no ledger changes warranted |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 2,891 files already formatted |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q` | PASS; 60 tests |
| `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | PASS; 1 test |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 27 passed, 5 PostgreSQL tests skipped; no live database proof claimed |
| `git diff --check 2ef76025e50b226a109d06bca0ae67fa14689afe...HEAD` | PASS; earlier whitespace finding is not present at this head |
| `uv run python scripts/check-backlog-consistency.py` | PASS; 168 items |

An additional `uv run python` check imported the current runner, loaded
`evidence/m3a-round6-shakedown.json`, and invoked `failed_promotion_checks`.
It returned `sustain_duration` and `exact_rc_artifact`. Assertions verified
both failures and `preflight_artifact_check()['ok'] is False`. Historical
identity is `b31c5fdaa63b40506335bbb288889e87bdb9ba0c`; duration is 90.43 seconds,
not the required 14,400 seconds and not evidence for the assigned head.

## Acceptance disposition

| #860 criterion | Executed evidence / remaining gap |
| --- | --- |
| Representative release profile | PARTIAL: profile exists, but `m3a-load-profile.md:152-164` excludes concurrent users/Workspaces, Graph fan-out, successful tool/model, Canvas and reconciliation workloads. Representative completeness UNVERIFIED. |
| Two application replicas | UNVERIFIED for production RC; historical host preflight and two ASGI middleware instances are not deployed production replicas. |
| Sustained saturation, reclaim, retry, leaks and restart | UNVERIFIED; current evaluator rejects the 90.43-second historical run. |
| Schedule/task/Run/Attempt physical-work uniqueness and Goal reconciliation | UNVERIFIED under qualifying load. Admission-probe unit tests passed, but claim-only races do not execute physical work (`m3a-load-profile.md:197-200`). |
| Rate/security/degraded behavior cannot be bypassed by replica selection | NOT MET: executed `test_replica_selection_has_an_independent_production_allowance` for authenticated and unauthenticated identities. Each real production middleware instance accepts two requests then returns 429; replica 2 grants a fresh allowance after replica 1 is exhausted. The backpressure regression proves local 429/Retry-After and subsequent admission, not cluster-wide security. |
| Required telemetry and thresholds | PARTIAL: process-group sampler regressions passed, including real child RSS/descriptor growth; qualifying application-loop, worker, database and long-window measurements remain UNVERIFIED. |
| Kill/restart with physical fencing/recovery | UNVERIFIED for exact RC under active representative load; historical rejoin/terminal counts do not establish physical-work recovery. |
| Long soak of exact RC/configuration | NOT MET: current evaluator rejects both duration and artifact. Runner explicitly identifies itself as host-uvicorn preflight (`scripts/soak/run_soak.py:635-647`). No new soak was run. |
| Findings filed/reclassified before promotion | Existing local backlog consistency passed. No new load findings were generated; external issue filing/reclassification is UNVERIFIED and no GitHub mutations were performed. |
| Machine/human evidence with exact hashes | Historical documents exist, but qualifying RC image/config evidence is UNVERIFIED. Historical commit does not equal assigned head. |

## Handoff

BLOCKED for promotion, not a vulture failure. The exact CI-repair request has
been checked and needs no source or ledger amendment. This round changes only
this validation record; existing code, tests and historical evidence are
preserved. No tests were added or removed, so no inventory delta is required.
No scheduler, execution authority, Goal store, event authority or authorization
path was introduced.

Remaining work requires the production-artifact runner and representative
workloads, resolution of cluster-wide rate-budget behavior through the existing
authorization path, complete application/database telemetry, and a fresh
qualifying soak after all runtime/configuration changes. Do not promote this
branch based on unit/preflight checks. A local commit of this record is the
writer handoff only, not integration approval.

Progress: checked 1 assigned issue; done 0 acceptance-complete issues; skipped 0
issues; errors 0 validation commands. Next: resolve the production soak and
replica-rate blockers; do not repeat speculative ledger amendments.

