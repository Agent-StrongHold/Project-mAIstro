# #860 round 144 — dispatched-head re-verification

- Dispatched head: `34ffd08f97a25010bcebc9d7e5c75d6ccf82b79e`; branch
  `auto-860`; declared develop base `e20e9f52ea94b393184f210cc9379f9f693f13d0`.
  Worktree was clean before validation. No `check-*.log` files were present in
  the dispatched job directory, so the checks below were run directly.
- Scope is limited to issue #860. No production or test code changed. The
  accepted execution spine remains Goal → Graph → Run → NodeRun → Attempt.
- Relevant accepted decisions read: ADR-085 (per-principal rate limiting) and
  ADR-081626-f383 (durable Attempt lease/fencing authority). The profile's
  declared process-local limiter is consistent with its documented #842 scope,
  but does not establish the issue's stronger cross-replica non-bypass claim.

## Fresh validation

| Command | Outcome |
| --- | --- |
| `uv run pytest tests/test_soak_promotion_gates.py -x -q` | **84 passed** |
| `uv run ruff check scripts/soak/run_soak.py packages/maistro-server/src/maistro_server/api/rate_limit.py tests/test_soak_promotion_gates.py` | **All checks passed** |
| `git status --short --branch` at start | clean, branch `auto-860` |

The focused middleware test in `tests/test_soak_promotion_gates.py` explicitly
shows same principal requests exhausting replica 1 while replica 2 independently
accepts its allowance. This is observed behavior, not a hypothetical scanner
finding. ADR-085 defines principal identity but does not authorize bypassing the
issue's replica-selection criterion; implementing shared budgets would require
a deliberate architecture/configuration decision rather than changing the
canonical execution authority.

## Promotion evidence rechecked

`docs/testing/soak/evidence/m3a-round109-shakedown.json` records
`sustain_seconds: 420.05`, below the required 14,400 seconds, and
`thresholds.checks.exact_rc_artifact.ok: false`. The profile explicitly says
that the host-process preflight is not the promoted Compose artifact. These
records cannot prove the required long-running exact-RC promotion soak.

Additional known limitations remain material: the profile documents missing
concurrent user/Workspace, Graph fan-out, successful tool/model, and Design/
Canvas loads; the schedule probe only admits then cancels a queued Run; and the
profile says production-grade worker/pool/lease-reclaim and physical Attempt
fencing/recovery observations remain unverified. Therefore no additional
acceptance surface is claimed complete based merely on the passing unit suite.

## Acceptance disposition

- Representative workload and two production replicas — **UNVERIFIED** at
  exact-RC artifact/configuration.
- Sustained pool/queue/lease/retry/leak/shutdown observation — **UNVERIFIED**;
  supplied shakedown is ~7 minutes, not ≥4 hours.
- Exactly-once physical execution, Attempt fencing/recovery, and kill/restart
  during active work — **UNVERIFIED**; schedule probe is admission-only.
- Rate limiting cannot be bypassed by replica selection — **FAIL**, reproduced
  by the focused production-middleware test (84-test suite passes while
  asserting independent replica allowance).
- Required application/runtime telemetry and thresholds — **PARTIAL**; profile
  defines several checks, but exact production evidence is absent.
- Exact RC soak and hash-bound promotion evidence — **UNMET**; the supplied
  artifact check is false and duration is below threshold.
- Findings filed/reclassified to earliest broken invariant — **UNVERIFIED** in
  this round.

Disposition: **NEEDS-REPAIR**. No gate was weakened and no evidence was
fabricated. This record is a validation checkpoint, not a production repair or
promotion approval. No tests were added; no inventory delta is required.
