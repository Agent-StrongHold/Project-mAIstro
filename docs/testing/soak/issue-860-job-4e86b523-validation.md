# Issue #860 validation — job 4e86b523

## Scope and governing contracts

Frozen scope: issue #860 only, starting at `51e0947971b1a20a5b29df43c9b5212492d826e4`.
The dispatch directory contains no `check-*.log` files, so no driver-supplied check
claims were treated as evidence. Reviewed the issue acceptance from
`dispatch-context.json`, `docs/testing/soak/m3a-load-profile.md`,
`docs/adr/ADR-081-deployment-backup-dr.md`, and accepted
`docs/adr/ADR-081626-f383-execution-lease-fencing.md`. The latter assigns lease
identity/fencing to the canonical Run store and AttemptExecutionService; this
validation does not introduce another execution authority.

## Executed validation

- `uv run ruff check .` — passed.
- `uv run ruff format --check .` — passed (3,404 files already formatted).
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — passed, 1,321 reviewed identities and 1,321 findings; no unbanked identity.
- `uv run pytest tests/test_soak_promotion_gates.py -x -q` — passed, 84 tests.
- Re-evaluated `docs/testing/soak/evidence/m3a-round109-shakedown.json` with the live `failed_promotion_checks` function — `sustain_duration` and `exact_rc_artifact` fail. It records 420.05 seconds (requested 420), and explicitly labels topology `host-uvicorn-preflight` with `exact_rc_artifact.ok=false`.

These deterministic tests establish fail-closed gate behavior only; they are not
production soak evidence. The job directory did not provide check logs. No
production Compose RC run was initiated: the current host-process driver cannot
represent or attest the exact promoted artifact, and a short run cannot satisfy
the four-hour minimum. Changing the gate or describing emulator output as RC
proof would contradict the documented evidence contract.

## Acceptance disposition

1. Representative users/Workspaces, request mix, Graph/node fan-out, schedules,
   tasks, tool/model calls, Design/Canvas and workers — **UNVERIFIED**. Profile
   explicitly records these workload omissions.
2. Two production application replicas — **UNVERIFIED**. Two host processes in
   historical preflight do not prove the supported production image/topology.
3. Sustained soak long enough for saturation, queues, reclaim/retry, leaks and
   shutdown/restart — **NOT MET**. Round 109 ran 420.05 seconds, below 14,400;
   exact RC not exercised.
4. Exactly-once/fenced schedule, task/Run/Attempt, Goal reconciliation and
   physical work across replicas — **PARTIAL/UNVERIFIED**. Existing admission
   probes do not prove sustained reconciliation or physical Attempt fencing.
5. Rate-limit/security/degraded behavior under concurrency without replica
   selection bypass — **UNVERIFIED for production**. Historical process-local
   probes do not prove aggregate deployed behavior; profile says cluster-wide
   budget is not established.
6. Required production telemetry and thresholds — **PARTIAL**. Some emulator
   metrics exist, but they are not production artifact/cgroup evidence and do
   not cover all required workload dimensions.
7. Kill/restart during active work proving deployed drain/fencing/recovery —
   **UNVERIFIED**. Historical host process behavior is not production proof.
8. Four-hour exact-RC soak and mandatory re-soak after code/config changes —
   **NOT MET**. `failed_promotion_checks` reports both `sustain_duration` and
   `exact_rc_artifact` for round 109.
9. Findings from a qualifying load run filed/reclassified to earliest broken
   invariant — **UNVERIFIED**; no qualifying RC soak was executed.
10. Human-/machine-readable evidence tied to exact RC image/package/commit/config
    hashes — **NOT MET**; existing evidence identifies the host preflight, not
    an immutable production image/configuration.

Disposition: **BLOCKED / NEEDS-REPAIR** for release acceptance. No source code or
tests were changed; no suite inventory delta applies. This record is a validation
checkpoint, not a promotion waiver.
