# Issue #860 validation — 5ef0dc46

Validation was performed against `a1c2b564d97ea6b3e921427ccce32980db303fe6`.
The job directory did not contain any `check-*.log` files to inspect.

## Findings

- The retained round-109 evidence is a 420.05-second host-uvicorn preflight, not
  the exact production Compose RC: its `thresholds.checks.exact_rc_artifact.ok`
  is `false` and identifies `host-uvicorn-preflight`; the requested sustain
  duration is 420 seconds, below the four-hour minimum in
  `docs/testing/soak/m3a-load-profile.md`. It cannot prove promotion readiness.
- `RateLimitMiddleware` constructs an `InMemoryRateLimiter` per process. Its
  module documentation explicitly states the aggregate budget is replica count
  multiplied by the configured limit. That does not meet the issue's
  replica-selection-resistant security criterion.
- The accepted scheduler decision in ADR-046 explicitly deferred multi-process
  leader election. Do not treat the single-conductor schedule model as proof of
  that unsupported multi-replica claim. The RC deployment topology and
  relevant cross-replica invariants still need a designated artifact and
  qualifying observation.

## Executed validation

- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_rate_limit.py -x -q`
  — **110 passed**, one existing Starlette deprecation warning. This confirms
  the local promotion gates/tests and rate-limit behavior, but does not turn
  process-local limiting into a cluster-wide guarantee or substitute for a
  production RC soak.
- Read the live round-109 JSON and load-profile minimum. The soak is explicitly
  provisional and reports no exact-RC proof.

## Acceptance status

A representative exact-RC, two-replica, >=14,400-second soak with the required
telemetry, invariant observations, restart/fencing evidence, and hash-tied
machine/human report remains **unverified**. No qualifying exact RC artifact or
configuration is designated in this worktree. This validation records the
blocker; it is not a promotion approval or an acceptance waiver.
