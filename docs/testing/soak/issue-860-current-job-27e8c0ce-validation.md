# Issue #860 validation — job 27e8c0ce

## Scope and evidence

- Frozen item: issue #860 only; starting HEAD `a2262d964f715836d82112bdd4f2d561cd1ececc`; worktree was clean.
- Read the repository instructions, issue acceptance text from the captured dispatch context, `docs/testing/soak/m3a-load-profile.md`, the soak promotion-gate implementation/tests, and ADR-081 plus accepted ADR-081626-f383 (lease/fencing contract). The canonical execution ownership remains unchanged; admission and schedule probes do not claim physical Attempt execution/fencing.
- Supplied deterministic logs: ruff check and format pass; targeted tests report 63 passed, 6 skipped; core/server suite inventories match. Prior verifier result failed at the model/provider layer after these checks; that provider error is not product evidence.
- Fresh `uv run pytest tests/test_soak_promotion_gates.py -x -q`: **84 passed**. These unit tests establish the gate behavior, not production soak acceptance.

## Acceptance review

1. Representative RC workload across users/Workspaces, Graph fan-out, schedules, tasks, tools/models, Design/Canvas and workers — **UNVERIFIED**. The current profile documents omissions in its remaining-profile-gaps section; the exercised preflight does not cover these workloads.
2. At least two application replicas — **PARTIAL, not RC acceptance**. Historical preflight has two host Uvicorn processes, not the production Compose image/configuration.
3. Long sustained load observing saturation, queue/reclaim/retry, memory/fd/process leaks and restart behavior — **UNVERIFIED**. Round 109 ran 420.05 seconds versus the documented 14,400-second minimum; no qualifying four-hour production run was executed here.
4. Exactly-once/fenced schedule, task/Run/Attempt, Goal reconciliation and physical work across replicas — **PARTIAL/UNVERIFIED**. Prior preflight records task and schedule admission probes, but the profile explicitly says it does not execute the probe Run or prove sustained Goal reconciliation / physical Attempt fencing.
5. Rate limit/security/degraded behavior under concurrency without replica-selection bypass — **UNVERIFIED for production**. Preflight probes do not establish deployed RC behavior; profile notes process-local rate limiting and does not establish a cluster-wide aggregate budget.
6. Required telemetry with explicit thresholds — **PARTIAL**. The preflight has telemetry/thresholds, but lacks production image/cgroup scope and several workload dimensions; it is not qualifying RC evidence.
7. Kill/restart during active work proving drain/fencing/recovery — **UNVERIFIED for RC**. A host-process SIGTERM check is not deployed active-work recovery/fencing proof.
8. Four-hour soak of exact RC artifact/config and re-soak after code/config changes — **NOT MET**. `scripts/soak/run_soak.py:744-755` unconditionally marks its host-uvicorn preflight `exact_rc_artifact.ok=false`; round-109 JSON records 420.05 seconds and `exact_rc_artifact.ok=false` (`m3a-round109-shakedown.json:221-228`).
9. Load findings filed/reclassified to earliest broken invariant — **UNVERIFIED** for findings from a future qualifying RC soak; no qualifying run occurred.
10. Human- and machine-readable evidence tied to exact RC image/package/commit/config hashes — **NOT MET**. Existing host preflight cannot supply promoted image/config identity, as stated in `m3a-load-profile.md:16-30`.

## Disposition

**BLOCKED / NEEDS-REPAIR.** The current evidence supports that the preflight fail-closes the promotion decision; it does not prove the issue's release acceptance. No production soak was initiated: the available harness cannot exercise/sign the exact RC artifact, and a short run could not satisfy the duration criterion. Do not weaken the gate or relabel preflight evidence as RC evidence. No tests or production code were added, so no suite inventory delta applies. No GitHub actions were taken.
