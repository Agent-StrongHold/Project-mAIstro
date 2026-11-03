# Issue #860 validation — job f7ee21f7

## Disposition

**NEEDS-REPAIR; no promotion evidence produced.** The required exact release-candidate Compose artifact/configuration is not designated in this worktree. A host-process preflight cannot substitute for that artifact, so a genuine ≥4-hour soak and hash-tied evidence cannot be produced here. Existing gates correctly fail closed; changing them to claim acceptance would falsify the evidence.

## Evidence checked

- The assigned job directory contains no `check-*.log` files; deterministic-driver logs were therefore unavailable and are not treated as passing evidence.
- `scripts/soak/run_soak.py::preflight_artifact_check()` returns `ok: false` and identifies `host-uvicorn-preflight`; `failed_promotion_checks()` requires `exact_rc_artifact` to pass.
- The retained round-109 evidence records 420.05 seconds against the 14,400-second minimum.
- A scan of 20 evidence JSON files found 12 `exact_rc_artifact` records and zero `ok: true` records.
- `m3a-load-profile.md` continues to list gaps in representative concurrent users/Workspaces, Graph fan-out, model/tool calls, Canvas/Design, Goal/background reconciliation, fencing, and production-grade telemetry.
- `rate_limit.py` documents process-local per-replica buckets. The passing tests do not demonstrate a shared aggregate per-principal allowance or prevent replica-selection multiplication. ADR-085 requires per-principal limiting; ADR-073126-c4e1 requires soaking the RC cut from `develop`. Neither ADR authorizes treating host-process evidence as RC evidence.

## Validation performed

- `uv run pytest tests/test_soak_promotion_gates.py -q -x` — **84 passed**.
- Retained acceptance evidence scan — **20 JSONs inspected; 0 exact-RC passes**.
- No load soak launched: absent exact RC designation means any run here would be non-acceptance preflight evidence, as the harness states.

## Acceptance status

The acceptance criteria remain unproven: representative profile completeness **UNVERIFIED**; two RC replicas **UNVERIFIED**; sustained 14,400-second RC soak and required resource telemetry **NOT MET**; cross-replica physical-work fencing/recovery **UNVERIFIED**; non-bypassable aggregate rate limiting **NOT MET**; exact-image/configuration evidence **NOT MET**; earliest-invariant classification **UNVERIFIED**.

Next step is operational, not an evidence waiver: designate an immutable RC and its Compose configuration, resolve the profile/fencing gaps, execute the required soak against that artifact, and publish machine-readable and human-readable evidence tied to its hashes. No promotion gate was weakened.
