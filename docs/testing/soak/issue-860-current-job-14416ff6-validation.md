# Issue #860 validation — job 14416ff6604a4113b3334b772f039ed3

Scope: assigned issue #860 only, branch `auto-860`, starting HEAD
`95c715365273c2bde9f49350c15bea0db9e213f8`, dispatch base
`8a9139bc5fc19f0d35ee28036a201dc8f721d28c`. Worktree was clean at intake.
The job directory contains no `check-*.log` files; claims from prior jobs were
not treated as current validation. No source or test edits were needed. No
GitHub mutations were performed.

## Fresh validation

- `uv run pytest tests/test_soak_promotion_gates.py -x -q` — PASS, 84 passed.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — PASS, 1,326 reviewed identities / 1,326 findings, zero unclassified and zero never-allowlist. No ledger edit is warranted.
- `uv run ruff check .` — PASS.
- `uv run ruff format --check .` — PASS, 3,373 files.
- `uv run python scripts/check-backlog-consistency.py` — PASS, 168 items.

Read repository instructions and accepted ADR-062 and ADR-081626-f383. Preserve
the canonical `Goal -> Graph -> Run -> NodeRun -> Attempt` execution spine.
ADR-081626-f383 establishes durable Attempt leases and stale-writer fencing;
it does not prove lease expiry/reclaim or physical exactly-once behavior. No
competing scheduler, execution authority, Goal store, event authority, or
authorization path was introduced.

## Acceptance evidence and blockers

- The load profile is not representative of the full issue workload: the profile's
  documented gaps at `docs/testing/soak/m3a-load-profile.md:167-183` include
  multiple users/Workspaces, Graph fan-out, successful tool/model calls,
  Design/Canvas and Goal/background workloads.
- No live deployment of two immutable RC replicas, long-duration saturation
  run, or active-work shutdown/recovery experiment was run in this job. Unit
  tests cannot substitute for those deployment observations.
- `scripts/soak/run_soak.py:19-21` explicitly says its host-process preflight
  cannot sign promotion; `:774-776` requires `exact_rc_artifact` and
  `sustain_duration` checks. The historical round-109 artifact's recorded
  duration is 420.05 seconds against a 14,400-second minimum and its RC check
  fails (`docs/testing/soak/evidence/m3a-round109-shakedown.json:221-227,283-284`).
- Replica-selection non-bypass is not proven. The executed
  `tests/test_soak_promotion_gates.py:480-526` regression observes independent
  `[200, 200, 429]` allowances on two limiter instances for the same identity;
  production source documents that these budgets are process-local at
  `scripts/soak/run_soak.py:1048-1051`. This is negative evidence, not a passing
  cluster-wide rate-limit proof.
- Physical-work fencing/recovery remains unverified by the schedule admission
  probe: `scripts/soak/run_soak.py:1064-1088` terminalizes/cancels the queued
  probe Run rather than executing a physical Attempt.
- The required complete PostgreSQL, app-loop, worker, resource, queue and error
  telemetry series with explicit RC thresholds, earliest-invariant finding
  classification for a new soak, and hash-bound human/machine evidence for the
  exact RC were not produced here.

Disposition: BLOCKED for #860 acceptance. The focused promotion-gate tests and
quality checks pass, but they do not prove release-candidate production
acceptance. Do not promote based on this validation. A designated immutable RC
and configuration, representative multi-replica workload, at least four-hour
exact-artifact soak, full telemetry, and physical Attempt failure/recovery
observations remain required. No tests were added; test inventory delta is
zero. This is a local handoff only, not integration approval.
