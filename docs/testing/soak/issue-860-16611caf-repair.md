# Issue #860 repair checkpoint (16611caf)

## Frozen scope

- Only issue #860, branch `auto-860`, starting HEAD
  `737136aeb1505655d44ce678e22b155204834378`, supplied base
  `3c761d14db944a727fa0744444bc67cfe36d49f7` (HEAD verified; clean tree).
- Inputs: supplied dispatch-context.json, prior result 27cec39d,
  prior failed check-3.log (98a11313), repository instructions and relevant ADRs.
- Review: scripts/soak/run_soak.py, tests/test_soak_promotion_gates.py,
  docs/testing/soak/m3a-load-profile.md, previous 27cec39d handoff,
  production rate-limit wiring and applicable CI gates.
- Candidate edits: this checkpoint; quality/vulture-baseline.json only if the
  requested exact scan demonstrates reviewed retained identities needing repair.
  No speculative production changes or unrelated historical diff cleanup.
- Current job directory contained no check-*.log files at start. The supplied
  prior failed log is the only named driver failure; it will be inspected.
- Assumption: writer repair, not read-only verifier. No designated exact RC
  image/configuration is stated in the lane assignment. Do not substitute host
  preflight or unit tests for the required deployed long soak.

## First executed results

- Required exact vulture scan: PASS, 1323 reviewed identities / 1323 findings,
  zero unclassified or never-allowlist findings. Scanner provenance base is
  `4aa68edc0b6b`. No ledger amendment is justified.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  PASS, 37 passed / 6 skipped. The supplied check-3.log fails because the
  expected schema DDL count was 21 versus 24; that failure does not reproduce
  at this HEAD. Database skips are not live concurrency evidence.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3270 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  PASS, 66 tests. Includes fail-closed preflight rejection, real middleware
  replica-selection behavior, real child-process resource sampling and task
  backpressure. This is not an elapsed four-hour or deployed-image soak.
- `uv run python scripts/check-suite-inventory.py`: PASS, 17 suites / 31128
  unique identities, zero duplicated evidence. No test edits or inventory delta.
- `git diff --check`: PASS.
- Previous report and current load profile both describe missing exact-RC
  execution; neither is accepted as proof. Production/gate inspection completed.

## Architecture and reachable behavior

Read accepted ADR-081226-69ee (Graph/Node), ADR-081626-f383 (execution fencing),
ADR-082526-b36a (renewal/reclaim), and ADR-085 (rate limiting). The later renewal
contract extends the earlier lease boundary; this review does not treat reclaim
as deferred. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt` and the
canonical execution/authorization authorities. No replacement mechanism added.

`maistro_server/main.py:648` installs `RateLimitMiddleware`, whose constructor
in `api/rate_limit.py:93` allocates an instance-local limiter. The executed test
`tests/test_soak_promotion_gates.py:439` uses that production middleware and the
same identity against two instances: both return 200, 200, 429. This proves local
allowances, not a shared budget. ADR-085's per-principal keying is not proof of
cross-replica enforcement. The issue's stronger non-bypass criterion remains
unproven; changing that architecture is not a speculative CI repair.

`scripts/soak/run_soak.py:730` always reports `exact_rc_artifact.ok=false`.
The executed CLI regression rejects missing, null and host-preflight artifact
records even with synthetic four-hour duration. Those fixtures did not actually
run for four hours. The historical schema failure already has its three missing
DDL expectations at `packages/maistro-core/tests/persistence/test_pg_learnings.py:176`.

## Acceptance assessment

| Issue criterion | Fresh evidence / disposition |
| --- | --- |
| Representative RC load profile | UNVERIFIED. Profile at `m3a-load-profile.md:155` acknowledges absent concurrent users/Workspaces, fan-out, successful model/tools, Design/Canvas and background workloads. No designated RC scope supplied. |
| Two deployed application replicas | UNVERIFIED. ASGI middleware instances are not two deployed exact-RC application replicas. |
| Sustained saturation, growth, reclaim, retry and leak observation | UNVERIFIED. Real child-process sampling regression passes; no sustained production observation was run. |
| Physical-work uniqueness across schedules/tasks/Run/Attempt/Goal | UNVERIFIED. Receipt/probe validation passes, but admission identity does not prove unique physical execution. |
| Security/rate/degraded behavior cannot be bypassed by replica selection | UNVERIFIED at deployment grade. Independent allowances reproduced; task backpressure tests pass, not cluster-wide budget proof. |
| Complete telemetry and explicit thresholds | UNVERIFIED. Profile contains thresholds but driver-loop lag is not application-loop lag; pool saturation and worker/reclaim observations remain absent. |
| Active-work kill/restart, drain, fencing and recovery | UNVERIFIED. Boot cleanup and gate tests pass; no active RC replica was killed or restarted. |
| Long soak of exact RC/configuration | BLOCKED / UNVERIFIED. Existing runner deliberately cannot sign promotion; immutable RC/configuration and exact-topology runner required. |
| Findings filed/reclassified before promotion | Local disposition recorded: aggregate allowance belongs to rate/security correctness, not throughput. External filing/reclassification UNVERIFIED; no GitHub mutations permitted. |
| Machine/human evidence bound to image/package/commit/config hashes | UNVERIFIED for RC. This report identifies tested source HEAD, not a promoted artifact/configuration or completed soak. |

## Handoff

Only this report changed. No reproducible CI failure or new scanner identity
justifies source, ledger or grant edits. No test counts changed, so no inventory
note is needed. No merge conflict was present; no develop fetch/merge performed.
Existing historical diff was preserved, not certified by these focused checks.

**BLOCKED**: designate the immutable RC/configuration and applicable workload
scope; provide an exact-topology runner with complete telemetry and physical-work
witnesses; execute the minimum four-hour soak including active-work recovery;
disposition invariant failures before promotion. Repeating this clean CI scan
or another host preflight will not resolve those prerequisites.

Progress: checked 1, done 0 (acceptance incomplete), skipped 0, validation errors 0.
Next: RC designation and exact-topology acceptance execution. Local commit is a
handoff only, not integration approval.
