# Issue #860 validation — job 2efe6f27

**Disposition: BLOCKED; acceptance is not established.** No code or gate change is justified: the missing prerequisite is an operationally designated immutable RC artifact/configuration and a real ≥4-hour soak of that artifact. Host-process preflight evidence cannot stand in for it.

## Instructions, ADRs, and evidence

- Reviewed the repository instructions, issue acceptance snapshot, and accepted ADR-073126-c4e1 §6: an RC is cut from `develop`, soaked there, and any fix requires a newly numbered immutable RC.
- Reviewed accepted ADR-085: request-rate limiting is per principal. `rate_limit.py` documents that its state is process-local, so its per-replica limits multiply across replicas; cluster-wide resistance to replica selection is not shown.
- `run_soak.py::preflight_artifact_check()` hard-codes `ok: false` and `topology: host-uvicorn-preflight`; `failed_promotion_checks()` requires `exact_rc_artifact` (`scripts/soak/run_soak.py:744-775`). Preserving this fail-closed behavior is required absent actual artifact-specific evidence.
- Read `docs/testing/soak/evidence/m3a-round109-shakedown.json`: `sustain_duration` is 420.05 seconds against 14,400 required, and `exact_rc_artifact.ok` is false.
- `docs/testing/soak/m3a-load-profile.md` explicitly states the representative-profile gaps and that they are blockers, not waivers. No exact RC designation is present in the recorded evidence.
- No `check-*.log` files exist in the supplied job directory; driver check outcomes are unavailable and not presumed to pass.

## Validation run

- `uv run pytest tests/test_soak_promotion_gates.py -x -q` — **84 passed**. These validate the fail-closed harness/gates, not production soak acceptance.
- No soak launched: without an exact RC image/configuration, host-process measurements cannot satisfy the acceptance criterion and would misrepresent preflight as promotion evidence.

## Acceptance status

- Representative RC profile, ≥2 RC replicas, required sustained duration and telemetry, fenced exactly-once work/recovery, replica-selection-resistant rate limits, and exact-image/configuration hash evidence: **UNVERIFIED / NOT MET**.
- Human- and machine-readable evidence is present for the short round-109 shakedown, but it explicitly fails the duration and exact-RC criteria; it is not acceptance evidence.

Next step: operationally designate the immutable RC and Compose configuration, address the documented profile and fencing gaps, run the required soak against that exact artifact, and publish hash-tied evidence. No promotion gate was weakened.
