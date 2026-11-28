# Issue #860 — validation checkpoint (`baf0c8d44fa0`)

**Disposition: NEEDS-REPAIR; no promotion approval.** Scope was frozen to issue #860 at the assigned head. The job directory supplied no `check-*.log` files; therefore all evidence below was inspected or run in this worktree. No GitHub actions were taken and no tests were added.

## Fresh checks

- `uv run pytest tests/test_soak_promotion_gates.py -x -q` — **84 passed**. Harness gate regressions pass; this does not establish a qualifying production soak.
- `uv run ruff check .` — **passed**.
- `uv run ruff format --check .` — **passed**, 3413 files.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — **passed**, 1321 reviewed identities / 1321 findings against base `9cc5d1aca141`.
- `uv run python scripts/check-reachability.py` — **passed**, 1434 production modules, 168 unreachable; no reported ratchet violation.
- Fresh Python evaluation of `m3a-round109-shakedown.json` with current `failed_promotion_checks()` returned `['sustain_duration', 'exact_rc_artifact']`; current `preflight_artifact_check()` returned `ok: false`, topology `host-uvicorn-preflight`. Evidence reports 420.05 seconds, not 14,400.

## Acceptance audit

1. Representative release-candidate workload (users/Workspaces, Graph fan-out, tools/models, Design/Canvas, workers) — **UNVERIFIED**; documented gaps remain in `m3a-load-profile.md`.
2. Two replicas on supported exact production topology — **UNVERIFIED**. Historical two-host-process preflight is not the exact Compose RC.
3. Sustained saturation, queue/reclaim/retry, resource/leak/shutdown observations — **NOT MET**; the supplied run is 420.05s against the 14,400s floor. No new four-hour run occurred.
4. Exactly-once/fenced physical operations and recovery across replicas — **UNVERIFIED**. Schedule admission probing is not proof of physical Attempt fencing/recovery; preserve canonical `Goal -> Graph -> Run -> NodeRun -> Attempt` authority.
5. Rate/security behavior that cannot be bypassed via replica selection — **UNVERIFIED / conflicting contract**. `packages/maistro-server/src/maistro_server/api/rate_limit.py` describes process-local limits; accepted ADR-085 requires principal-keyed limiting but does not itself demonstrate shared multi-replica state. Do not change semantics without reconciling that contract.
6. Full required telemetry with explicit thresholds — **UNVERIFIED** at RC grade; existing harness telemetry cannot substitute for application event-loop, promoted worker/container, and long-window observations.
7. Active-work replica kill/restart with drain, fencing and recovery proof — **UNVERIFIED**; no new production experiment or physical-effect oracle was run.
8. Long soak of exact immutable RC/configuration — **NOT MET**; current host preflight intentionally fails exact-artifact identity and the available evidence is short.
9. Findings filed/reclassified before promotion — **UNVERIFIED** externally; no GitHub mutation performed.
10. Human and machine evidence tied to exact RC image/package/commit/config — **UNVERIFIED**; existing historical evidence is not a current exact-RC soak.

## Governance and next step

Accepted ADR-073126-c4e1 requires an RC from `develop` and soak there; ADR-081626-f383 places durable lease/fencing authority in canonical Attempt persistence and explicitly does not establish expiry takeover/recovery; ADR-085 defines per-principal rate-limiting. None waives the production evidence above. `preflight_artifact_check()` is correctly fail-closed (`scripts/soak/run_soak.py`); weakening it or lowering the duration gate would not satisfy acceptance. A release owner must select the immutable RC/configuration and authorize the production topology/window, resolve the documented profile and fencing gaps, and publish a qualifying run. No test-inventory delta applies because no tests were added.
