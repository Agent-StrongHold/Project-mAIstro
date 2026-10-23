# #860 round-154 validation

**Disposition: BLOCKED.** This validation confirms that the current tree still
cannot produce promotion-grade evidence. No exact immutable Compose RC image,
configuration, or deployment target is designated, so no soak was launched and
no run was represented as acceptance evidence.

## Evidence reviewed

- `scripts/soak/run_soak.py::preflight_artifact_check()` always returns
  `ok: false` with topology `host-uvicorn-preflight`; the promotion gate
  requires `exact_rc_artifact`.
- `docs/testing/soak/evidence/m3a-round109-shakedown.json` records
  `sustain_seconds: 420.05` and `exact_rc_artifact.ok: false`. The profile
  requires at least 14,400 seconds (`docs/testing/soak/m3a-load-profile.md`,
  lines 141-151).
- The profile explicitly lists representative workload/fencing and production
  telemetry gaps as blockers, not waivers (`m3a-load-profile.md`, lines
  165-184).
- Rate limiting remains process-local by explicit implementation contract in
  `packages/maistro-server/src/maistro_server/api/rate_limit.py`; ADR-085
  requires per-principal rate limiting. This does not prove a cluster-wide
  aggregate limit or resistance to replica selection.
- ADR-073126-c4e1 permits an RC tag on `develop`; that release path does not
  establish that an exact RC artifact is currently available for this run.
- No `check-*.log` files were present in the supplied job directory; no
  driver-produced result is inferred from absent logs.

## Validation executed

`uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-core/tests/scheduling/test_pg_admission.py -x -q`

Result: **110 passed, 2 skipped**, one existing Starlette deprecation warning.
These focused tests exercise gate and admission/rate-limit behavior; they are
not a substitute for the requested multi-replica production soak.

## Acceptance disposition

The representative RC workload; two-replica exact-artifact execution; sustained
14,400-second telemetry; physical-work fencing/admission/reconciliation;
replica termination and recovery; thresholded production telemetry; and
hash-tied machine/human evidence remain **UNVERIFIED** or **NOT MET**. Rate
limiting's aggregate resistance to replica selection is **NOT MET** by the
process-local implementation. No production fix or waiver is claimed here.

Next evidence needed: designate the immutable RC and production configuration,
resolve the documented workload/fencing gaps, execute the ≥4-hour soak, and
publish its hash-tied evidence. Do not promote based on this validation.
