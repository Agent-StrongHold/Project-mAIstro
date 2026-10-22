# #860 round-153 acceptance review

**Disposition: BLOCKED; no promotion evidence produced.** This review treats the
supplied claims as unverified and checks the current harness, retained evidence,
profile, and accepted release-candidate process. No production-code or gate
changes were made: this worktree has no designated immutable Compose RC artifact
or deployment target from which to produce valid promotion evidence.

## Findings

- `scripts/soak/run_soak.py::preflight_artifact_check()` intentionally records
  `ok: false` and `host-uvicorn-preflight`; it cannot establish exact-artifact
  acceptance. `docs/testing/soak/evidence/m3a-round109-shakedown.json` records
  420.05 seconds against the profile's 14,400-second minimum.
- `docs/testing/soak/m3a-load-profile.md` explicitly leaves representative
  concurrent users/Workspaces, Graph fan-out, successful tool/model calls,
  Design/Canvas, Goal/background reconciliation, and physical-work fencing as
  gaps or unverified evidence.
- `packages/maistro-server/src/maistro_server/api/rate_limit.py:32-35,93-96`
  states and implements process-local rate-limit state; the configured limit
  multiplies with replicas. This does not prove a shared aggregate principal
  limit or inability to increase allowance through replica selection. ADR-085
  requires per-principal limiting, while ADR-073126-c4e1 §6 says an RC is cut
  from and soaked on `develop`; this is a reconciliation of test harness scope,
  not permission to waive acceptance.
- The job directory supplied for this review contains no `check-*.log` files;
  no deterministic-driver result is inferred from absent logs.

## Executed validation

- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-core/tests/scheduling/test_pg_admission.py -x -q`
  — **110 passed, 2 skipped**, one Starlette deprecation warning. Regression
  tests do not constitute a long exact-RC soak.
- Inspected ADR-085, ADR-073126-c4e1 §6, `m3a-load-profile.md`, the round-109
  JSON, and the live preflight gate implementation.
- No soak launched: no exact RC artifact/configuration was designated. The
  profile states that this host-process driver always fails exact-artifact
  acceptance, even when run for four hours.

## Acceptance disposition

- Representative release-candidate workload: **UNVERIFIED**; profile gaps remain.
- Two replicas of supported production artifact: **UNVERIFIED**; prior host
  processes are not Compose-artifact evidence.
- Sustained load for ≥14,400 seconds with required telemetry: **NOT MET**;
  retained run is 420.05 seconds and does not cover all required measurements.
- Exactly-once/fenced physical work across replicas and kill/restart recovery:
  **UNVERIFIED at RC level**; prior admission/host probes do not prove physical
  execution fencing on the promoted artifact.
- Rate limiting effective under concurrency and not bypassable by replica
  selection: **NOT MET** for aggregate allowance; current limiter is
  process-local by documented design.
- Machine- and human-readable evidence tied to exact image/config hashes:
  **NOT MET**; no exact RC soak evidence exists.
- Findings classified to earliest invariant: **UNVERIFIED**; no qualifying
  production soak was performed in this round.

Next required evidence: designate the immutable RC and production Compose
configuration, close the profile's representative-workload and fencing gaps,
run the ≥4-hour exact-artifact soak, and publish its hash-tied evidence. No
acceptance waiver is implied by this note.
