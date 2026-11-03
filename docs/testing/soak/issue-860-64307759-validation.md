# Issue #860 — dispatched-round validation

The assigned worktree started clean at `c6b5d85e4b02e89586383fcea2616e007f01404c`. The supplied job directory contained no `check-*.log` files. Prior result `5c1ac5e92e2f4effb31d4eae2de7dafb` was independently inspected and reported a blocked outcome. Following the dispatch instruction, fetched and merged `origin/develop`; merge completed without conflicts. No source behavior or quality ledger was changed.

## Architecture and evidence review

Accepted [ADR-081626-f383](../../adr/ADR-081626-f383-execution-lease-fencing.md) sets durable lease/fencing as the execution authority for production Attempts; stale physical workers must not mutate newer Attempts. It intentionally leaves takeover/recovery beyond its original contract. The accepted lease-reclaim follow-up is ADR-082526-b36a. The soak's schedule probe is not proof of physical Attempt uniqueness, as `m3a-load-profile.md` itself notes under the Round-2 goal reconciliation scope.

The checked-in profile (`docs/testing/soak/m3a-load-profile.md`) explicitly calls the current runner a host-process preflight, says exact Compose RC identity is required, sets a 14,400-second minimum, and lists remaining profile/telemetry/fencing gaps. The runner's `preflight_artifact_check()` unconditionally reports `ok: false` for host uvicorn topology (`scripts/soak/run_soak.py`, around line 744). The round-109 evidence records only 420.05 seconds and `exact_rc_artifact.ok=false` (`docs/testing/soak/evidence/m3a-round109-shakedown.json`, around lines 221 onward). Therefore a passing synthetic gate test or longer host preflight cannot satisfy exact-RC promotion evidence.

## Validation executed

- `uv run pytest tests/test_soak_promotion_gates.py -x -q` — **84 passed**.
- `uv run ruff check scripts/soak/run_soak.py tests/test_soak_promotion_gates.py` — **passed**.
- `uv run ruff format --check scripts/soak/run_soak.py tests/test_soak_promotion_gates.py` — **passed**, both already formatted.
- Job-directory `check-*.log` inspection — **none present**.

No tests were added; no test-inventory delta applies. This validation did not run a 4-hour deployment soak, as the available harness explicitly cannot attest the production Compose artifact and no designated RC image/configuration was available in the dispatched evidence.

## Acceptance disposition

1. Representative RC workload including concurrent users/Workspaces, fan-out, applicable tool/model, Design/Canvas, and workers — **UNVERIFIED**; gaps are expressly listed in the profile.
2. At least two replicas running the exact supported RC topology — **UNVERIFIED**; existing host-process checks are not an immutable Compose RC.
3. Sustained soak long enough to assess saturation, queue/lease/retry/resource/leak/shutdown behavior — **NOT MET**; round 109 is 420.05 s versus 14,400 s minimum.
4. Exactly-once/fenced physical work across replicas, including schedule and recovery — **UNVERIFIED**; targeted schedule admission evidence does not prove active physical Attempt fencing/reclaim.
5. Concurrent security/rate-limit effectiveness without replica-selection bypass — **UNVERIFIED** at RC deployment grade; profile describes the present probes but no qualifying RC evidence.
6. Required telemetry and explicit thresholds — **UNVERIFIED** as RC evidence; preflight telemetry is not equivalent to the required production telemetry.
7. Kill/restart during active work with graceful drain/fencing/recovery — **UNVERIFIED** as RC evidence.
8. ≥4-hour soak of exact RC artifact/configuration — **NOT MET**; host runner fails `exact_rc_artifact` by design.
9. Load findings classified to earliest broken invariant — **UNVERIFIED** for an RC soak; no qualifying findings set supplied.
10. Machine- and human-readable evidence bound to exact image/package/commit/config hashes — **NOT MET**; no designated RC evidence supplied.

**Disposition: BLOCKED / NEEDS REPAIR.** To proceed, an RC owner must supply the selected immutable deployment artifact/configuration and execute the production-topology soak; changing host-preflight acceptance gates would contradict the documented contract and was not attempted. This report is not promotion approval.
