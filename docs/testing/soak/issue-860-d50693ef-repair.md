# Issue #860 — d50693ef repair checkpoint

## Frozen scope and initial evidence

- Only issue #860; assigned worktree `/home/dev/Git/wt/auto-860`, branch
  `auto-860`, starting HEAD `aff68f0a5e4507e31b82c67a46875784487c0acb`;
  supplied develop base `82097f6b7acca58ffc27a934b305faaee7a37915`.
- Initial worktree clean. No salvage, unresolved ref, or merge conflict.
- Candidate repair files frozen to `quality/vulture-baseline.json` (only
  demonstrated scanner drift), `scripts/soak/run_soak.py` and
  `tests/test_soak_promotion_gates.py` (only demonstrated regressions), and
  this checkpoint; an inventory note only if tests change. Adjacent production
  wiring, tests, ADRs and supplied dispatch artifacts are read-only context.
- Writer assignment assumed, rather than verifier-only. No remote enumeration
  or GitHub mutations. Current job directory contains no `check-*.log` files.
- Supplied historical `98a11313/check-3.log` fails the learnings schema-fence
  test (24 observed DDL statements versus 21 expected), not vulture.
- Fresh required vulture command passes: 1,326 reviewed identities and 1,326
  findings; zero unclassified/never-allowlist identities. No ledger amendment
  justified. Command: `uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (600 s timeout).
- Prior BLOCKED result is not a develop-sync conflict. Exact-RC acceptance
  must be checked independently; green static checks cannot certify it.

## Validation and acceptance

- `uv sync --locked --extra dev`: PASS.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  -x -q`: **37 passed, 6 skipped** (1.65 s). Historical schema-fence failure
  does not reproduce; PostgreSQL-dependent cases remain skipped.
- `uv run pytest tests/test_soak_promotion_gates.py
  tests/test_prod_stack_boot_contract.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  packages/maistro-server/tests/api/test_rate_limit.py -x -q`:
  **100 passed** (3.02 s), including independent real production middleware
  instances accepting `[200, 200, 429]` each for the same identity.
- Read accepted ADRs 081426-1f7c, 081626-f383, 082526-b36a and 073126-c4e1.
  Attempt identity/lease fencing remains canonical. Admission deduplication
  cannot substitute for physical execution recovery. RC provenance must follow
  the existing release path, not an arbitrary local build. No new scheduler,
  execution authority, authorization path, or release waiver is introduced.

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS (3,195 files).
- `uv run python scripts/check-merge-markers.py`: PASS.
- `uv run python -` imported the actual driver and evaluated preserved
  `evidence/m3a-round30-shakedown.json`: observed 420.08 seconds versus the
  14,400-second minimum; failed gates exactly `sustain_duration` and
  `exact_rc_artifact`. Assertions confirmed both failures, insufficient duration,
  and `preflight_artifact_check()['ok'] is False`. This is fresh negative
  validation of historical evidence, not a new production soak.
- Validation batches after the initial scan used 1,200-second timeouts.
  Captured last issue comments and PR #1672 body establish no selected RC or
  resolved prerequisite; no live remote status was fetched.

## Every acceptance criterion

| Criterion | Evidence and disposition |
| --- | --- |
| Representative RC load profile | **UNVERIFIED complete.** `m3a-load-profile.md:145–164` names missing users/Workspaces, fan-out, successful model/tool calls, Canvas and Goal/background workloads. Current driver `scripts/soak/run_soak.py:1372–1395` still uses one credential and the narrower traffic mix. |
| At least two application replicas | **UNVERIFIED on the RC.** `deploy/docker-compose.prod.yml:26–77` defines two services and boot-contract tests pass; no deployed exact-RC replica experiment ran here. |
| Sustained saturation, queues, reclaim, retry/backoff and leaks | **UNVERIFIED.** Fresh evaluation rejects historical 420.08-second evidence. Real child-process sampler regression passes, but does not establish four-hour application behavior. |
| No duplicate physical work, including Goal reconciliation | **UNVERIFIED.** `scripts/soak/run_soak.py:1044–1072` cancels the unexecuted schedule admission probe Run. ADR-081426-1f7c identifies an Attempt, not admission, as physical execution identity. |
| Effective rate/security/degraded behavior without replica-selection bypass | **UNVERIFIED overall; independent allowances reproduced.** Executed `tests/test_soak_promotion_gates.py:439–493` observes `[200, 200, 429]` on each production limiter instance for the same credential/IP. `packages/maistro-server/src/maistro_server/api/rate_limit.py:32–37` explicitly promises process-local scope. Passing local enforcement/backpressure tests cannot prove a shared budget. |
| Full telemetry with explicit thresholds | **UNVERIFIED.** `scripts/soak/run_soak.py:1410–1424` records driver loop lag, not application event-loop lag. Profile gaps include saturation, worker counts and lease reclaim. |
| Kill/restart during active work with drain/fencing/recovery | **UNVERIFIED.** `scripts/soak/run_soak.py:1436–1489` records process exit/rejoin and HTTP counters; no active-Attempt physical-work oracle was executed. |
| Long-running exact-RC/config soak | **BLOCKED / UNVERIFIED.** `scripts/soak/run_soak.py:730–741` explicitly rejects the host preflight artifact; fresh historical evaluation fails duration and artifact checks. No immutable promotion image/configuration is identified by this assignment. |
| Findings filed/reclassified to earliest invariant | **UNVERIFIED completeness.** Historical findings remain in the profile. No complete new load run or classification audit occurred; GitHub mutations are prohibited. |
| Machine/human evidence tied to exact image/package/commit/config hashes | **UNVERIFIED for current RC.** Preserved artifacts and this commit-bound validation note are not an exact-image/config production evidence pack. |

## Handoff

**BLOCKED, not merge-ready.** The supplied CI failure is not reproducible and
vulture has no unbanked identities, so no scanner-driven repair is justified.
Only this checkpoint changes. No tests added, so no inventory delta is required.
Production code, ledgers, authorizations and historical artifacts are untouched.
No develop merge was required; no GitHub mutation was performed.

Before another implementation attempt, supply the selected immutable RC and
runtime configuration through the existing release process. Complete the
representative workload, application telemetry and active-Attempt observation;
resolve the replica-budget acceptance mismatch; then execute the minimum
four-hour exact-artifact soak. A repeated green CI run cannot resolve these
prerequisites. The six skipped database tests and all unexecuted production
acceptance above remain explicit residual risks.

Progress: {checked: 1, done: 0, skipped: 0, errors: 0,
next: exact-RC acceptance prerequisites}. CI diagnosis complete; issue acceptance
remains blocked. Local documentation commit is a handoff, not integration approval.
