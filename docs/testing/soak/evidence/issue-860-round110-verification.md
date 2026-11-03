# Issue #860 — round 110 verification (not promotion evidence)

**Commit under review:** `56c6f510f15303b19f5b96267f99ca7a5db10608`  
**Outcome:** blocked; no production release-candidate soak was run in this attempt.

This is a bounded verification record, not a claim that #860 acceptance is met.
The assigned job directory contained no `check-*.log` files. No exact RC image,
production config identity, or soak-run artifacts were supplied for this attempt;
therefore a promotion-grade run could not be executed or attested here.

## Rechecked production behavior

- `packages/maistro-server/src/maistro_server/api/rate_limit.py` constructs an
  `InMemoryRateLimiter` per middleware instance. Its module documentation
  explicitly says each process/replica gets an independent allowance.
- Re-ran
  `uv run pytest tests/test_soak_promotion_gates.py -k replica_selection_has_an_independent_production_allowance -q -x`:
  **2 passed** (authenticated and unauthenticated). Both replicas accepted two
  requests each with a limit of two, then rejected the third request on each.
  Selecting a second replica therefore gives the identity another allowance;
  this does not satisfy #860's anti-bypass acceptance criterion.
- Re-ran
  `uv run pytest packages/maistro-server/tests/api/test_rate_limit.py -q -x`:
  **26 passed**. These cover the middleware's existing behavior, not shared
  cross-replica enforcement.

## Acceptance status

The tracked profile in `docs/testing/soak/m3a-load-profile.md` requires at
least 14,400 seconds and an exact production Compose RC artifact; it also says
the host-process preflight always fails the exact-artifact gate. Existing
round-109 evidence records a 420.05-second run with `exact_rc_artifact.ok=false`.
The profile itself lists the unverified representative-user/Workspace,
Graph/tool/model, Design/Canvas, Goal reconciliation, application-loop,
pool/lease, and physical-work recovery evidence. Accordingly this attempt
cannot establish the requested representative workload, sustained saturation
and recovery, exact RC soak, telemetry thresholds, replica restart/fencing,
or finding filing/reclassification criteria. Prior round evidence is not
silently promoted as evidence for this commit/configuration.

No test or production code was changed in this verification-only attempt.
The failing acceptance conditions above remain blockers for #860; this record
must not be read as a release or merge approval.
