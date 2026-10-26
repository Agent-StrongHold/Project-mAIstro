# #860 round-155 validation

**Disposition: BLOCKED; no product code change is justified by this run.** The
acceptance target is promotion evidence for an exact, immutable RC artifact. The
current harness deliberately runs host Uvicorn preflights, and this repository
snapshot does not designate an RC image/configuration or provide operational
evidence that a four-hour exact-artifact run has occurred. Calling the existing
preflight evidence acceptance would weaken the gate rather than repair it.

## Instructions and architecture reviewed

- Accepted ADR-073126-c4e1 §6 says an RC is cut from `develop`, soaked there,
  and any fix requires a newly numbered RC; tags are immutable.
- Accepted ADR-085 requires per-principal rate limiting. The production
  middleware explicitly documents that its limiter is process-local and its
  aggregate configured budget scales with replica count; issue #860's stronger
  requirement to resist replica selection remains unproven.
- The canonical execution flow and existing tests were preserved; this run made
  no scheduler, execution-authority, or authorization-path changes.

## Evidence and validation

- `preflight_artifact_check()` in `scripts/soak/run_soak.py` always emits
  `ok: false` and `topology: host-uvicorn-preflight`; the promotion check list
  requires `exact_rc_artifact` (`run_soak.py:744-775`).
- Independently reread `docs/testing/soak/evidence/m3a-round109-shakedown.json`:
  `sustain_duration` is 420.05 seconds versus the 14,400-second minimum and
  `exact_rc_artifact.ok` is false. Passing preflight measurements do not satisfy
  the artifact-specific acceptance criterion.
- `packages/maistro-server/src/maistro_server/api/rate_limit.py:32-37,93-98`
  documents and constructs a process-local limiter; therefore cluster-wide
  aggregate resistance to replica selection is not established.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: passed; 1,314 reviewed
  identities match 1,314 findings, with zero unbanked identities. No ledger
  change is warranted.
- `uv run pytest tests/test_soak_promotion_gates.py
  packages/maistro-server/tests/api/test_rate_limit.py
  packages/maistro-core/tests/scheduling/test_pg_admission.py -x -q`: **110
  passed, 2 skipped**, one existing Starlette deprecation warning.
- The supplied job directory contains no `check-*.log` files; no driver check
  result is inferred from their absence.

## Acceptance disposition

- Representative release-candidate workload and two-replica execution on the
  exact immutable RC artifact/configuration: **UNVERIFIED**.
- Sustained soak for at least 14,400 seconds with required thresholded
  production telemetry: **NOT MET** (available evidence is 420.05 seconds).
- Fenced exactly-once work across replicas, recovery during active work, and
  replica-selection-resistant aggregate rate limiting: **UNVERIFIED / NOT MET**.
- Hash-tied machine-readable and human-readable acceptance evidence:
  **UNVERIFIED** for the exact RC.

Next required step is operational: designate and build the immutable RC image
and config under ADR-073126-c4e1, close documented workload/telemetry gaps, run
the full soak, and publish its hash-tied evidence. No acceptance waiver is
claimed.
