# #860 round-154 acceptance validation

**Disposition: BLOCKED; no promotion-grade soak evidence was produced.** This
round rechecked the working tree and retained evidence rather than treating the
previous result as proof. No exact release-candidate image/configuration or
production deployment target was designated, and the existing driver explicitly
runs host Uvicorn processes rather than that artifact. Running it as if it were
promotion evidence would not satisfy the acceptance criteria.

## Live checks

- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-core/tests/scheduling/test_pg_admission.py -x -q`
  — **110 passed, 2 skipped**, with one Starlette deprecation warning. These
  focused regression tests do not prove production-topology soak behavior.
- Re-read `docs/testing/soak/evidence/m3a-round109-shakedown.json`: the
  programmatic evidence values are `sustain_duration` = 420.05 seconds versus
  14,400 minimum (`ok: false`) and `exact_rc_artifact` = host-uvicorn preflight
  (`ok: false`). The recorded checks fail closed for both criteria.
- `scripts/soak/run_soak.py::preflight_artifact_check()` deliberately returns
  `ok: false` for the host-process runner; `failed_promotion_checks()` requires
  `exact_rc_artifact`. Do not change this fail-closed gate to disguise missing
  RC evidence.
- No `check-*.log` files were present in the supplied job directory, so no
  driver validation claim is inferred from missing logs.

## Acceptance disposition

- Representative release-candidate workload and supported multi-replica
  artifact: **UNVERIFIED**; the profile still documents representative workload
  gaps and no exact RC was designated.
- Sustained load for at least 14,400 seconds, including required telemetry:
  **NOT MET**; retained live evidence is a 420.05-second host-process run.
- Exactly-once/fenced physical work, restart recovery, graceful drain, and
  concurrency-safe aggregate rate limiting on the candidate artifact:
  **UNVERIFIED**. Focused tests are not artifact-level evidence. The current
  rate limiter remains process-local (`packages/maistro-server/src/maistro_server/api/rate_limit.py`),
  so the no-replica-selection-bypass criterion is not established.
- Hash-tied machine- and human-readable evidence for the promoted artifact:
  **NOT MET**.
- Findings classified to the earliest broken invariant from qualifying load
  evidence: **UNVERIFIED**; no qualifying soak was run.

ADR-073126-c4e1 §6 requires an RC cut from `develop` and soaked there; the
host-process harness cannot substitute for the RC. ADR-085 requires per-principal
rate limiting. Neither is a waiver of #860's stronger multi-replica aggregate
acceptance. No runtime code or promotion gate was changed. Next step is to
identify and freeze the actual RC/configuration, then close the documented
profile/fencing gaps and run the required soak against it.
