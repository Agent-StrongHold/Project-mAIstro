# Issue #860 — bounded repair 5e8aef08

## Frozen scope

- Only issue #860, branch `auto-860`, starting HEAD
  `e32ceb5b29aad5eec3c8fcd4fdfa29b9aec6bd30`, supplied base
  `d7fb3baa6837a1a6ccb9aa5c2a1288cef6eb7743`.
- Clean worktree at admission; no incoming edits to salvage.
- Inspect repository instructions, relevant accepted ADRs, supplied dispatch and
  prior failure evidence, `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, existing load-profile/evidence documents,
  and vulture checker/workflow. Amend `quality/vulture-baseline.json` only if the
  exact requested scan identifies reviewed retained debt; no speculative edits.
- Deliverable: this handoff plus evidence-backed CI repair if needed. No new
  execution authority, deployment, GitHub mutations, or integration approval.
- Ambiguity: this is a writer repair lane, not a read-only verifier lane.
  Exact-RC designation is not supplied; historical host preflight is not assumed
  to satisfy the release soak.
- Job directory listing contains no `check-*.log`; supplied prior failure log
  and result will be inspected instead. Prior result is BLOCKED, not proof.

## Progress

- Exact requested vulture scan passed: 1,326 reviewed identities and findings,
  zero unclassified / never-allowlist entries. No ledger repair is warranted.
- Supplied historical `check-3.log` failed on 24 schema statements versus 21
  expected. Fresh `uv run pytest
  packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` passes:
  **37 passed, 6 skipped**. The historical failure is not current.
- `uv run ruff check .`: passed. `uv run ruff format --check .`: passed,
  3,170 files. Each validation command has a 1,200-second timeout.
- `uv run pytest tests/test_soak_promotion_gates.py
  tests/test_prod_stack_boot_contract.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  packages/maistro-server/tests/api/test_rate_limit.py -x -q`: **100 passed**.
- `uv run python scripts/check-suite-inventory.py`: passed, 17 suites,
  29,499 unique identities, no duplicate evidence.
- `uv run python scripts/check-merge-markers.py`: passed.
- `uv run python -` imported the current soak driver, loaded
  `evidence/m3a-round30-shakedown.json`, and asserted that reevaluation fails
  `sustain_duration` and `exact_rc_artifact`. Actual historical duration is
  **420.08 seconds**, versus **14,400 seconds** required. The current driver's
  artifact check returns `ok: false`, topology `host-uvicorn-preflight`.
  This reevaluates historical evidence; it is not a new soak.
- `git diff --check`: passed.

## Architecture and reachable behavior

Read accepted ADR-081426-1f7c (physical identity is Attempt), ADR-081626-f383
(canonical-store lease fencing), ADR-082526-b36a (renewal and reclaim), and
ADR-073126-c4e1 (immutable RC release provenance). The later reclaim contract
extends the earlier fencing contract's deferred takeover boundary; that deferral
cannot waive recovery acceptance. Preserve `Goal -> Graph -> Run -> NodeRun ->
Attempt`; an admission counter is not physical-work uniqueness evidence.

`packages/maistro-core/tests/persistence/test_pg_learnings.py:175-177` already
asserts the three Gauntlet column upgrades absent in the historical failure.
Production `pg_learnings.py:216` takes the advisory lock before those upgrades.
Passing fake-connection tests establish statement order, not live multi-replica
PostgreSQL correctness; six database-dependent tests skipped.

The exact scan arguments match `.github/workflows/quality.yml:1038-1041`.
The successful ledger scan reports its own baseline `34795962548a`; it is not
claimed to be a separately forced comparison against the dispatch develop base.
There are no unbanked identities to review or amend. No code, tests, grants,
ledger or inventory notes changed. No new tests means no inventory delta.

Production installs `RateLimitMiddleware` in
`packages/maistro-server/src/maistro_server/main.py:648`. Its constructor creates
an `InMemoryRateLimiter`; its documented contract at `api/rate_limit.py:32-37`
is process-local. The freshly executed
`test_replica_selection_has_an_independent_production_allowance` at
`tests/test_soak_promotion_gates.py:439-488` observes `[200, 200, 429]` on each
instance for the same identity. It demonstrates independent allowances, not a
shared-budget guarantee. This is a scope/acceptance mismatch needing resolution
through the existing security seam, not permission to introduce another auth path.

## Acceptance disposition

| #860 criterion | Executed evidence / unresolved gap |
| --- | --- |
| Representative RC load profile | **UNVERIFIED complete.** Read `m3a-load-profile.md:153-172`: concurrent users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal/background-worker coverage are missing. No selected RC configuration justifies exclusions. |
| Two deployed application replicas | **UNVERIFIED.** Two independent middleware instances exercised via ASGI, not two deployed RC replicas. |
| Sustained saturation, queue growth, reclaim, retries, leaks and shutdown | **UNVERIFIED.** Reevaluated 420.08-second evidence fails duration; no new sustained production observations. |
| No duplicate physical schedule/task/Run/Attempt/Goal work | **UNVERIFIED.** Admission probe tests and schema ordering do not establish physical Attempt fencing or Goal reconciliation under sustained multi-replica load. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED as stated.** Real middleware tests reproduce independent per-replica allowances. Shared-budget non-bypass is not proven; broader deployed security remains unverified. |
| Complete production telemetry and explicit thresholds | **UNVERIFIED complete.** Profile specifies thresholds; no candidate telemetry collected. Driver-loop lag does not establish application-loop latency. |
| Active-work kill/restart, drain, fencing and recovery | **UNVERIFIED.** Passing boot cleanup tests are not active physical-work takeover/stale-effect rejection evidence. |
| Long soak of exact promoted RC/configuration | **BLOCKED / UNVERIFIED.** Current driver deliberately rejects host preflight (`run_soak.py:730-741`); historical evidence freshly fails duration and artifact gates. No immutable RC image/configuration is selected in the assignment. |
| Findings filed/reclassified before promotion | **UNVERIFIED completeness.** No new load campaign or GitHub mutations; historical findings cannot establish completeness for a new RC. |
| Machine/human evidence tied to exact artifact/configuration hashes | **UNVERIFIED for candidate.** Historical pack preserved, not certification of current HEAD. This report records local validation only. |

## Handoff

**BLOCKED**, not integration-ready. Only this report changed. The supplied CI
failure is already repaired and no current vulture failure exists. Repeating
that historical failure does not justify changing code or banking fictitious debt.

Next: supply the selected immutable RC image/configuration and representative
workload exclusions; resolve replica-budget semantics; execute at least four
hours of production-path load with active-work fault injection, canonical
Attempt fencing/reclaim observations, complete telemetry and hash-bound evidence.
Neither a longer host emulator run nor these passing unit tests fulfills that.
No replacement scheduler, execution/event/Goal authority or authorization path
was introduced. No deployment, merge, push, PR, or issue mutation performed.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "selected RC and production acceptance execution"}`.
This report is the locally committed checkpoint; acceptance remains unfinished.
