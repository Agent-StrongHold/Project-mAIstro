# Issue #860 — bounded repair 332d3f6d

## Frozen scope

- Issue #860 only; branch `auto-860`, starting HEAD
  `9e139b024f8bd07ab66ae1e92904e2b06de35051`, supplied base
  `8fbbbfb91d78d30d756cf675b7b1a4c1ccff06e5`.
- Clean worktree confirmed before edits; no incoming changes to salvage.
- Repair candidates: `packages/maistro-core/src/maistro/persistence/pg_learnings.py`,
  its adjacent `tests/persistence/test_pg_learnings.py`, and
  `quality/vulture-baseline.json` only if the requested exact scan supplies
  actionable evidence. Associated inventory note only if tests change.
- Read-only acceptance inspection: `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, `docs/testing/soak/m3a-load-profile.md`,
  `docs/testing/soak/evidence/m3a-round30-shakedown.json`, the referenced ADRs,
  production rate limiting and deployment configuration.
- Supplied dispatch snapshot is authoritative for the list of issues/PRs;
  no GitHub refresh or mutation. No other issue will be processed.

## Initial evidence / ambiguity

The current job directory has no `check-*.log` files. The supplied previous
`98a11313.../check-3.log` reports 24 schema statements versus 21 expected.
The supplied prior result reports BLOCKED, not CI failure. Neither claim is
accepted without fresh validation. Assumption: this is a writer CI-repair
round, not authorization to invent an RC artifact or replace canonical
execution/rate-limit authority. A green CI check alone cannot prove #860.

## Progress

- Exact vulture command PASS: 1,326 reviewed identities / 1,326 findings;
  unclassified=0, never_allowlist=0. It resolves merge-base `e46ad6708fda`.
  No retained unbanked identities exist to justify a ledger amendment.
- Current schema-fence test already expects all 24 DDL statements, including
  the three Gauntlet audit columns absent from the supplied old failure.
  Fresh execution PASS: `uv run pytest
  packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  37 passed, 6 PostgreSQL-dependent tests skipped (1.45 s). No test rewrite
  warranted. `uv sync --locked --extra dev` also passed.
- Prior BLOCKED report describes missing RC acceptance, not a develop-sync
  conflict. No merge is warranted on that evidence.
- Fresh acceptance tests PASS: `uv run pytest
  tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  packages/maistro-server/tests/api/test_rate_limit.py -x -q`:
  100 passed (2.72 s). Production middleware instances still reproduce
  independent allowances on replica selection; these are not deployed RC tests.
- Read accepted ADRs 081426-1f7c, 081626-f383, 082526-b36a and
  073126-c4e1. Attempt is physical execution identity; canonical persistence
  owns fences and expiring leases/renewal/reclaim. A branch preflight cannot
  substitute for promoted artifact provenance. No competing authority added.
- Frozen dispatch review/comment evidence inspected: prior BLOCKED comments
  add no selected RC/configuration; unrelated linked-PR findings are not
  instructions or additional repair scope.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3,195 files already formatted.
- `uv run python scripts/check-merge-markers.py`: PASS.
- Fresh `uv run python -` evaluation of preserved
  `evidence/m3a-round30-shakedown.json` through the current driver: PASS
  assertions that `sustain_duration` and `exact_rc_artifact` fail. Recorded
  duration is 420.08 seconds; required minimum is 14,400. Also asserted
  `preflight_artifact_check()['ok'] is False`. This is negative acceptance
  validation, not a new soak.

## Acceptance audit

| Issue criterion | Current reachable evidence and disposition |
| --- | --- |
| Representative RC profile | **UNVERIFIED complete.** `m3a-load-profile.md:145–164` identifies absent multi-user/Workspace, fan-out, successful model/tool, Canvas and Goal workloads. `scripts/soak/run_soak.py:1382–1395` implements the narrower mix with one credential. |
| Two application replicas | **UNVERIFIED for RC.** `deploy/docker-compose.prod.yml:1–12,76–77` defines the two-replica reference topology, not an immutable candidate. Boot-contract tests passed, but no RC deployment ran this round. |
| Sustained saturation, reclaim, retries, leaks | **UNVERIFIED.** Historical 420.08-second evidence fails the current 14,400-second requirement. Sampler regression tests passed; that is not sustained production observation. |
| No duplicate physical work / Goal reconciliation | **UNVERIFIED.** `scripts/soak/run_soak.py:1044–1072` cancels the admitted schedule probe Run without executing it. Run admission uniqueness is not physical Attempt uniqueness under the accepted execution/fencing ADRs. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED as a whole; contrary evidence to shared allowance.** Executed `tests/test_soak_promotion_gates.py:439–493` reproduces `[200,200,429]` independently from each production limiter for the same principal/IP. `packages/maistro-server/src/maistro_server/api/rate_limit.py:32–37` explicitly promises process-local, not cluster-wide enforcement. Contract reconciliation is needed, not an invented authorization path. |
| Complete telemetry and thresholds | **UNVERIFIED.** `scripts/soak/run_soak.py:1410–1430` samples driver loop lag, not application event-loop lag. The profile explicitly records missing pool saturation/worker/reclaim and long-window observations. |
| Active-work kill/restart, drain/fencing/recovery | **UNVERIFIED.** `scripts/soak/run_soak.py:1436–1489` observes exit/rejoin and HTTP counters; it does not establish an active-Attempt physical-work oracle. No kill/restart experiment ran this round. |
| Long soak of exact RC/config | **BLOCKED / UNVERIFIED.** Fresh historical evaluation fails duration and artifact checks. `scripts/soak/run_soak.py:730–741` always rejects the host preflight artifact. The supplied branch HEAD does not select an immutable promoted image/configuration. |
| Findings reclassified to earliest invariant | **UNVERIFIED completeness.** Historical profile amendments record findings, but no complete new production run or classification audit establishes all findings resolved/reclassified. No GitHub mutation performed. |
| Machine/human evidence tied to exact hashes | **UNVERIFIED for current candidate.** Historical artifacts remain untouched. This report identifies the inspected commit and commands, but cannot supply candidate image/config-bound soak evidence. |

## Handoff

**BLOCKED.** The supplied CI failure is stale on this HEAD; the mandated
vulture gate supplies no debt to fix or bank. Only this validation report
changes. No production code, tests, ledger, gate, authorization, or historical
evidence was modified. No test inventory delta is needed because no tests
were added, removed or modified. Validation commands used 1,200-second
ceilings. No remote mutations, destructive git operations, background commands
or release actions occurred.

Required next input/work: select the immutable RC/configuration through the
existing release process; complete representative production workloads,
application telemetry and active-Attempt observation; reconcile the local
rate-limit contract with replica-selection acceptance; then execute the
minimum four-hour exact-artifact soak. Re-running green CI cannot satisfy
these prerequisites. No acceptance waiver or integration approval is claimed.

Progress: {checked: 1, done: 0, skipped: 0, errors: 0,
next: exact-RC acceptance prerequisites}. This report is committed locally
as the required worker checkpoint.
