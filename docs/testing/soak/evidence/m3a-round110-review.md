# #860 round-110 independent repair review

**Disposition: blocked; no promotion evidence produced.** This review rechecked the
current tree rather than treating the prior verification as an acceptance pass.

## Executed checks

- `uv run pytest tests/test_soak_promotion_gates.py -q -x` — **84 passed**.
- `uv run pytest packages/maistro-server/tests/api/test_soak_promotion_gates.py -q -x` — attempted the previously cited path; **exit 4**, file does not exist in this tree. The actual suite is the root `tests/` path above.
- Parsed `docs/testing/soak/evidence/m3a-round109-shakedown.json`: `sustain_seconds` is **420.05**; `exact_rc_artifact` is `{ok: false, topology: host-uvicorn-preflight, reason: not the exact production Compose image and configuration}`.

## Acceptance disposition

1. Representative release-candidate profile: **UNVERIFIED** as complete. `docs/testing/soak/m3a-load-profile.md` explicitly lists user/Workspace population, Graph/node fan-out, tool/model calls, Design/Canvas and Goal/background reconciliation gaps.
2. Two production application replicas: **UNVERIFIED**. Existing host preflight is not evidence for the production Compose artifact.
3. Sustained load: **NOT MET**. 420.05 seconds is below the documented 14,400-second minimum.
4. Exactly-once/fenced physical execution across replicas: **UNVERIFIED** by soak. The accepted ADR-081626-f383 defines stale-fence rejection, but does not itself constitute runtime soak evidence.
5. Rate limit cannot be bypassed by replica selection: **NOT MET** by the current design. `packages/maistro-server/src/maistro_server/api/rate_limit.py` documents and implements process-local limiter state; each replica independently enforces its allowance. This is consistent with ADR-085's per-principal identity requirement but does not establish an aggregate cross-replica budget.
6. Required resource/latency/queue/error telemetry with thresholds: **PARTIAL / UNVERIFIED at promotion grade**; host-preflight telemetry cannot substantiate production artifact behavior or the required long-window observations.
7. Kill/restart drain/fencing/recovery: **UNVERIFIED at promotion grade**; prior host SIGTERM observations do not establish exact-artifact recovery/fencing.
8. Long-running exact-RC soak: **NOT MET**; the harness identifies itself as host-uvicorn preflight and emits `exact_rc_artifact.ok=false`.
9. Findings reclassified to earliest broken invariant: **UNVERIFIED**; no newly observed production-load finding to classify in this run.
10. Hash-tied machine/human exact-RC evidence: **NOT MET**; the available round-109 artifact is host preflight, not the promoted artifact/configuration.

No production Compose RC image/configuration, deployment target, or four-hour execution window was available in this attempt. Fabricating a passing evidence artifact or weakening the harness gates would be invalid. No production-code changes were made; the blocker is missing required runtime evidence plus the observed per-replica rate-limit allowance, not a harness test failure. This note is a review checkpoint, not release authorization.
