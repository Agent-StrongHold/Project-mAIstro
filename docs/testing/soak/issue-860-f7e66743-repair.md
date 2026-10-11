# Issue #860 — bounded CI repair and acceptance verification

## Scope and checkpoint

- Assigned writer job: `f7e66743b17246e1b4773c61df2f12fe`.
- Frozen item: #860 only, branch `auto-860`, clean starting HEAD
  `514b39ae24dcfc15436427baccbabefd82f7caf5`; supplied develop base
  `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Edit scope: this report; the vulture ledger only if the exact scan reveals
  reviewed retained debt. No speculative code, test, grant or ledger changes.
- No current driver `check-*.log` files were supplied. Read the explicitly
  referenced prior `98a11313167b41a98a420abfda80c292/check-3.log` and prior result.
  The former is a pytest DDL-list mismatch, not a vulture violation.

## Fresh executed evidence

Logs reside under the assigned job directory
`/home/dev/maistro/jobs/f7e66743b17246e1b4773c61df2f12fe/`.

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  passed: 1323 findings / 1323 reviewed identities, zero unclassified and
  never-allowlist findings (`worker-vulture.log`). The checker reports its own
  baseline as `4aa68edc0b6b`, not the supplied develop SHA; this is the exact
  requested invocation without a baseline override. No ledger edit is justified.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py -x -q`
  passed: **102 passed, 6 skipped** (`worker-tests.log`). PostgreSQL integration
  skips are not evidence of deployed replica safety. The historical assertion
  expecting 21 statements while observing 24 is not reproducible at this HEAD.

## Architecture reconciliation

Read repository instructions and the documentation authority map, proposed
ADR-081, accepted ADR-081426-1f7c (ExecutionRuntime), and accepted
ADR-081626-f383 (Attempt execution leases/fencing). The physical execution
identity is Attempt, not Run. Admission deduplication does not prove unique
physical execution. The accepted lease ADR explicitly defers expiry takeover
and recovery-driven supersession; do not invent a competing reclaim authority
to satisfy issue wording. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`.
Proposed deployment ADR text is not an acceptance waiver.

## Remaining validation results

- `uv run ruff check .`: passed (`worker-ruff-check.log`).
- `uv run ruff format --check .`: passed, 3270 files already formatted
  (`worker-ruff-format.log`).
- `uv run python -` imported the current soak evaluator and checked the frozen
  historical artifact `docs/testing/soak/evidence/m3a-round5-final.json`:
  90.17 seconds; rejected for `rate_limit_enforced`, `sustain_duration`, and
  `exact_rc_artifact` (`worker-historical-evidence.log`). This validates rejection,
  not the old run's claimed operational observations.
- `git diff --check`: passed.
- Two discovery lookups included nonexistent paths (`docs/testing/soak/README*`
  and `maistro_server/middleware/rate_limit.py`); recorded as not found, skipped.
  The production import resolves instead to `maistro_server/api/rate_limit.py`.

## Acceptance assessment against reachable behavior

| Issue criterion | Fresh evidence / status |
|---|---|
| Representative RC users/Workspaces, request mix, fan-out, schedules, queue, tools/models, Canvas and workers | **UNVERIFIED.** The profile documents gaps. `scripts/soak/run_soak.py:1373-1395` uses one API key and a health/task/receipt/metrics mix; successful model/tool work and the other required surfaces are not represented. |
| At least two application replicas | **UNVERIFIED at RC grade.** The tested runner's artifact check identifies host-uvicorn preflight, not two promoted application images. No deployment was launched this round. |
| Sustained saturation, queue growth, lease/retry and leak observations | **UNVERIFIED.** No long-window run. The inspected historical artifact lasted 90.17 seconds; unit tests cannot establish these observations. Reclaim semantics must follow the accepted lease boundary above. |
| No duplicate physical work across schedule/task/Run/Attempt/Goal operations | **UNVERIFIED.** Run/receipt admission probes and `canonical_runs` counts (`run_soak.py:1507-1527`) are not Attempt physical-work evidence. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED for deployment; independent allowances reproduced locally.** `tests/test_soak_promotion_gates.py:439` tests real production middleware with the same identity on two instances, each returning `[200, 200, 429]`. Production registers that middleware at `maistro_server/main.py:648`; its constructor (`api/rate_limit.py:90-98`) creates per-instance in-memory state. Local burst rejection is not a cluster-wide allowance proof. No alternate authorization/rate authority was added. |
| Required telemetry and explicit thresholds | **UNVERIFIED in full.** Sampler/gate tests pass, but `run_soak.py:1410-1426` samples driver event-loop lag, not application loop lag. The profile acknowledges worker/cgroup and long-window gaps; no fresh deployed query/lock/pool telemetry was collected. |
| Active-work replica restart, drain, fencing and recovery | **UNVERIFIED.** CLI drain-gate regression tests passed; no active Attempt kill/restart was performed. Rejoin and terminal Run counts alone are insufficient. |
| Long soak of exact RC artifact/configuration | **BLOCKED / UNVERIFIED.** `run_soak.py:730-741` unconditionally returns `exact_rc_artifact.ok=false`, wired into main at line 1552. The executed CLI tests (`test_soak_promotion_gates.py:103`) reject otherwise-passing four-hour preflight evidence. The dispatch designates no immutable RC image/config identity for a production soak. |
| Findings filed/reclassified to earliest broken invariant | **UNVERIFIED externally.** Existing findings and this report remain local evidence; no GitHub mutation was authorized or performed. |
| Machine/human evidence bound to exact image/package/commit/config hashes | **UNVERIFIED for RC.** Existing human profile and JSON exist, but current evaluator rejects the inspected JSON. These validation logs and this commit are not an RC evidence pack. |

## Disposition and handoff

**BLOCKED for issue acceptance.** The named deterministic failure is stale at
this head and the exact vulture gate passes. The current DDL test independently
lists all three audit columns at `test_pg_learnings.py:175-177`, matching
`pg_learnings.py:116-118`; no production/test/ledger change is justified by the
reported failure. This round changes only this report; no tests were added or
removed, so no inventory delta note is needed. Existing work was preserved.

Next requires a designated immutable RC image/configuration, a representative
production-path workload and physical Attempt/recovery/telemetry evidence, then
at least the profile's four-hour deployed soak. Resolve the scope of the
non-bypass rate criterion against the documented process-local budget, without
claiming that per-replica 429s satisfy a cluster-wide budget. Do not repeatedly
rerun the host preflight expecting duration to remove its artifact blocker.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "designate and exercise exact RC production workload"}`.
The single issue is explicitly blocked; CI triage is complete. Local commit of
this report is the writer checkpoint, not integration or promotion approval.
