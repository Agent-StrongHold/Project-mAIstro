# Issue #860 — job 27b6b5c4 repair validation

## Frozen scope and initial checkpoint

- Only issue #860 in `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD verified: `b72da8fc715c27459d6c97916924e4c38b25db6d`.
- Assigned base resolved: `045cfdfbe3eaa0c84493eb02754d7410b0c69378`.
- Initial working tree clean. No incoming uncommitted work to salvage.
- Review snapshot: repository instructions and relevant execution, schedule,
  deployment and rate-limit ADRs; `scripts/soak/run_soak.py`;
  `tests/test_soak_promotion_gates.py`, `tests/test_prod_stack_boot_contract.py`;
  production rate middleware, task backpressure and PostgreSQL learning-schema
  code/adjacent tests; `deploy/docker-compose.prod.yml`; current load profile,
  human evidence and four historical JSON packs (`m3a-soak-evidence`,
  `m3a-repair-validation`, `m3a-round5-final`, `m3a-round6-shakedown`);
  exact vulture CI gate and relevant provenance/shipped-surface checks.
- Edit surface: this report; genuinely dead source or vulture ledger only if the
  requested exact scan supplies actionable evidence. No runtime changes planned.
- Prior job result and report read, not adopted as current validation.
- Job directory initial listing contains no `check-*.log` files. Driver logs
  unavailable; run focused validation independently.
- Ambiguity: this is the assigned writer/CI-repair round. No merge conflict
  exists. No immutable RC image/configuration is supplied; do not invent one or
  relabel a host-process preflight as release evidence.

## Executed results

- Exact required command, 600-second timeout:
  `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  PASS, **1360 findings / 1360 reviewed identities**, zero unclassified and
  zero never-allowlist findings; base `045cfdfbe3ea`. No ledger amendment or
  dead-code deletion is supported by this output.
- Current `m3a-load-profile.md` explicitly describes the host-process emulator,
  four-hour minimum, independent replica budgets and representative-workload
  gaps. Acceptance remains open pending fresh validation below.
- `uv run ruff check .`: PASS. `uv run ruff format --check .`: PASS,
  2809 files already formatted (1200-second timeout).
- Docker daemon reachable at the assigned Unix socket, version 29.7.2.
- The prior H3 shared-store claim is already corrected in the current human
  evidence (`m3a-soak-evidence.md:171`). Production still installs
  `RateLimitMiddleware` (`main.py:588`), with a per-instance in-memory limiter
  (`api/rate_limit.py:72`). Existing regressions test replica-selection budgets
  for authenticated and unauthenticated callers; run them below.
- ADR reconciliation: accepted ADR-085 requires canonical per-principal identity
  but does not establish shared replica state. ADR-081 is Proposed guidance,
  not an accepted waiver of #860. Accepted ADR-081626-f383 requires Attempt
  fences and explicitly leaves takeover to a later contract; ADR-082126-f69c
  routes schedule fires into canonical Runs, not another scheduler. An
  admission-only race cannot prove physical-work recovery. No alternate
  execution or authorization authority is introduced.
- Created only this job's scratch PostgreSQL container
  `maistro-860-27b6b5c4-pg` (`03cdc8304d96`), image `pgvector/pgvector:pg18`,
  loopback port 45723, database `maistro_860`. This is not an RC deployment.
- With `DATABASE_URL=postgresql://postgres@127.0.0.1:45723/maistro_860`,
  `uv run alembic upgrade head`: PASS, full chain through 050.
- With `MAISTRO_TEST_PG_DSN` set to the same scratch DSN,
  `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs`:
  **93 passed in 5.31s, zero skipped** (1200-second timeout).
- Both production-middleware replica-selection cases reproduce `[200, 200, 429]`
  on each independent instance for the same identity. Replica 1 stays exhausted
  while replica 2 grants more requests (`tests/test_soak_promotion_gates.py:439–488`).
  This disproves a shared principal allowance, not the documented local budget.
  ASGI middleware tests are not a live two-application RC soak.
- CI command verified in `.github/workflows/vulture-ratchet.yml:76–85`.
  `uv run python scripts/check-ratchet-provenance.py`: PASS (46 quality JSON
  consumers and delegated gates, assigned base `045cfdfbe3ea`).
  `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- Executed a `uv run python` audit importing current `failed_promotion_checks`
  against all four frozen historical JSON packs. Every pack fails
  `sustain_duration` and `exact_rc_artifact`. Runs 5/6 record 90.17/90.43 seconds
  versus 14400; the older packs lack duration-gate records. Assertions PASS;
  promotion does not. The current driver deliberately returns
  `exact_rc_artifact.ok=false` (`scripts/soak/run_soak.py:635–645`).
- Stopped only `maistro-860-27b6b5c4-pg`; retained container/data. No other
  Docker resources changed. `git diff --check`: PASS.

## Acceptance assessment

| Criterion | Executed evidence and remaining gap |
| --- | --- |
| Representative RC load profile | PARTIAL, completion UNVERIFIED. Profile inspected; `m3a-load-profile.md:151–166` explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and Goal/background-worker coverage. No selected RC configuration justifies exclusions. |
| At least two application replicas | UNVERIFIED under RC load. The reference Compose defines two servers, and boot-contract tests pass, but no two-application deployment was executed in this round. Scratch PostgreSQL is not an application replica. |
| Sustained saturation, growth, reclaim, backoff, leaks, shutdown | UNVERIFIED. Current evaluator rejects all four historical packs for duration. Focused tests cannot prove sustained behavior. |
| Exactly-once/fenced physical work and reconciliation | UNVERIFIED under load. Admission-oracle regressions pass, but the schedule probe cancels its queued Run without physical execution (`m3a-load-profile.md:191–196`). No Attempt-correlated recovery run was executed. |
| Replica-selection non-bypass; security/degraded behavior | NOT MET for a shared principal allowance. Production middleware regressions reproduce independent budgets on both replicas. Broader RC-load security/degraded acceptance remains UNVERIFIED. |
| Complete telemetry and pass/fail thresholds | UNVERIFIED for the RC. Process-group sampler tests pass, but no fresh application-loop, pool saturation, lease, worker/leak and long-window telemetry was captured. The profile labels several resource thresholds soft rather than hard gates. |
| Kill/restart during active work, drain/fencing/recovery | UNVERIFIED. Historical process exit/rejoin is not physical Attempt correlation; no RC failure injection was executed. |
| Long-running exact-RC soak | NOT MET. Four historical packs rejected for artifact and duration; no immutable RC image/configuration supplied and current runner cannot certify one. No new soak claimed. |
| Findings filed/reclassified at earliest milestone invariant | PARTIAL; external filing UNVERIFIED. Existing local F11/F12 classify evidence defects as M3-A evidence validity. No new load finding or prohibited GitHub mutation. |
| Machine/human evidence bound to exact artifact/config hashes | UNVERIFIED for promotion. Historical packs remain unchanged and fail current gates. This report records focused validation only. |

## Handoff

**BLOCKED for issue #860 acceptance.** No evidence-backed vulture repair exists:
1360 reviewed identities exactly match the scan. The prior false H3 statement is
already corrected. Do not amend a green ledger or invent additional runtime
changes to make this round appear repaired.

Only `docs/testing/soak/issue-860-27b6b5c4-repair.md` changes in this round.
No production, runtime-config, test, ledger or grant edits. Existing meaningful
regressions were executed; no new tests or suite-count changes, so no inventory
delta note is necessary. Canonical Goal → Graph → Run → NodeRun → Attempt is
unchanged. This is a locally committed blocked handoff, not integration approval.

Next work requires the immutable RC image/configuration #89 intends to promote,
a representative production-path runner with complete telemetry and physical
Attempt correlation, resolution of replica-budget/non-bypass semantics through
canonical enforcement, and a fresh ≥14400-second exact-artifact soak including
active-work failure injection. Any code/runtime-config change requires another
soak. Repeating the already-green vulture gate cannot remove those blockers.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "#860 RC identity, representative runner, replica non-bypass and qualifying soak"}`.
