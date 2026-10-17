# Issue #860 repair checkpoint — e6df1833

## Frozen scope

Only issue #860, branch `auto-860`, starting HEAD
`81226785249823aa30386081fcb4c34f4ca4e0e0`, supplied base
`3c761d14db944a727fa0744444bc67cfe36d49f7`. Initial worktree clean.
No GitHub mutation or integration approval.

Repair targets: the reported schema-fence regression in
`packages/maistro-core/tests/persistence/test_pg_learnings.py`, its production
schema implementation `packages/maistro-core/src/maistro/persistence/pg_learnings.py`,
and reviewed identities in `quality/vulture-baseline.json` only if the required
scan identifies debt. Supporting scope: existing soak harness/tests/docs, relevant
ADRs and CI gate instructions; this report and a test inventory note if needed.

The current job directory contains no driver `check-*.log`. Supplied prior
`98a11313167b41a98a420abfda80c292/check-3.log` reports 24 DDL statements versus
21 expected in the schema-fence test. Prior result reports no designated exact RC
artifact/configuration. Assumption: repair the reproducible gate failure without
claiming host/unit checks prove the ten release-soak acceptance criteria.

## Progress

- Inspected repository instructions, dispatch issue body, prior result and failed
  check log. The ordered test expectation already includes the three validation
  audit columns; no production/test change is warranted for the historical failure.
- Fresh exact Vulture scan: PASS, 1323 reviewed identities / 1323 findings,
  zero unclassified or never-allowlist findings (checker base `4aa68edc0b6b`).
  No ledger amendment is justified.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  37 passed, 6 skipped (database skips are not soak evidence).
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  66 passed.
- `uv run ruff check .`: PASS. `uv run ruff format --check .`: PASS,
  3270 files already formatted. All validation commands used 1200-second timeouts.
- Only this report changes. No tests added/changed; no inventory delta.
  These checks do not certify inherited branch changes.

## Architecture and acceptance

Read accepted ADR-081426-1f7c, ADR-081626-f383, ADR-082526-b36a and
ADR-082826-08f0. Physical execution identity is Attempt; the later renewal/reclaim
and recovery-disposition decisions fill the original fencing contract's deferred
recovery boundary. Terminal Run counts cannot substitute for physical-work
uniqueness. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`; no competing
authority or runtime change was introduced.

The supplied brief does not designate the exact immutable RC image/configuration
for #89. Latest captured comments only repeat blocked attempts. No new release
identity is inferred from branch HEAD. **BLOCKED**, not a develop-sync conflict.

| #860 acceptance criterion | Fresh evidence / disposition |
|---|---|
| Representative release workload | **UNVERIFIED.** `scripts/soak/run_soak.py:1373–1395` uses one credential and health/task/receipt/metrics traffic with no LiteLLM. `m3a-load-profile.md` explicitly identifies missing users/Workspaces, Graph fan-out, successful model/tools, Design/Canvas and Goal/background-worker coverage. |
| Two deployed application replicas | **UNVERIFIED.** `run_soak.py:730–741` identifies host-uvicorn preflight, not exact production Compose; no RC deployment executed here. |
| Sustained saturation, queue growth, reclaim, retries and leaks | **UNVERIFIED.** Sampler/accounting regression tests passed, but no sustained production telemetry collected. |
| No duplicate physical work across schedule/task/Run/Attempt/Goal paths | **UNVERIFIED.** Admission probe regressions passed; `run_soak.py:1507–1527` observes Run counts/status, not physical execution across these paths. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED for deployment; independent allowances reproduced locally.** Executed `tests/test_soak_promotion_gates.py:439` yields `[200,200,429]` independently on both real middleware instances for the same identity. `api/rate_limit.py:90–98` constructs a process-local limiter; production registers it at `maistro_server/main.py:648`. Local enforcement is not a cluster budget. |
| Complete DB/application-loop/process/RSS/FD/queue/error telemetry and thresholds | **UNVERIFIED.** `run_soak.py:1410–1426` measures driver-loop lag, not application-loop lag. No complete RC observation window. |
| Active-work restart/drain/fencing/recovery | **UNVERIFIED.** Drain regression tests passed; process rejoin and terminal Run counts do not prove active Attempt recovery. No RC restart performed. |
| Long soak of exact promoted RC/configuration | **BLOCKED / UNVERIFIED.** RC not designated. Executed `test_four_hour_preflight_cannot_pass_cli` (`tests/test_soak_promotion_gates.py:103`) rejects otherwise-passing four-hour host evidence. `preflight_artifact_check` is wired into thresholds at `run_soak.py:1552`. |
| Findings filed/reclassified before promotion | **UNVERIFIED externally.** Local findings recorded; GitHub mutations prohibited and not performed. |
| Machine/human evidence tied to image/package/commit/config hashes | **UNVERIFIED for RC.** This local validation report names source HEAD, not a promoted image/configuration. No RC evidence pack generated. |

## Handoff

The historical failed command now passes; the exact CI Vulture scan passes
(arguments confirmed at `.github/workflows/quality.yml:1078`). No genuinely
unbanked identity or reproducible schema failure exists to repair in this round.
No tests or gates weakened. Existing branch work preserved.

Next requires owner-designated immutable RC/configuration, workload applicability,
rate-budget semantics resolved through existing policy authority, and a long
production soak with physical Attempt/recovery observations and complete telemetry.
Do not retry the stale schema log or short host preflight as an RC substitute.
Any code/runtime-configuration change requires a new soak.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "exact-RC prerequisites and production soak"}`.
Commit records the writer handoff only; no issue closure or integration approval.
