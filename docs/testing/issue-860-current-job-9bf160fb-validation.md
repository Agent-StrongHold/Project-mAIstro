# Issue #860 validation — job 9bf160fb

## Scope and state

- Frozen scope: issue #860 only, as supplied in
  `/home/dev/maistro/jobs/9bf160fb70e64e3fbe00af7b96c38659/dispatch-context.json`.
- Worktree: `auto-860`; starting HEAD `8499ef6933ed95c28096efbb39b1fe29cc28d60e`.
- The assigned job directory contains no `check-*.log` files. No local changes
  were present at inspection. No production deployment, image/configuration
  selection, or four-hour soak was made available in this worktree.
- No code or gate change is justified by the current evidence. No tests or
  inventory changed in this validation pass.

## Executed validation

`uv run pytest tests/test_soak_promotion_gates.py -x -q` — **84 passed**.
These are harness/gate tests, not evidence of deployed multi-replica behavior.

## Acceptance gaps verified from repository evidence

- `docs/testing/soak/evidence/m3a-round109-shakedown.json` binds to git head
  `5a59c724a20ef1241d57c048df90758f2c2e1e25`, not this candidate, and reports
  only 420.05 seconds against the 14,400-second minimum; its exact-RC result is
  false. It cannot establish the required soak for this candidate.
- `docs/testing/soak/m3a-load-profile.md` (remaining representative-profile
  gaps) explicitly reports no concurrent user/Workspace population, Graph/node
  fan-out, successful tool/model calls, Design/Canvas or Goal/background-worker
  reconciliation. It also says driver loop lag is not application event-loop
  lag and calls these blockers, not waivers.
- `tests/test_soak_promotion_gates.py:480-483` explicitly tests independent
  production allowance per replica, not a shared principal budget. Its passing
  test means replica selection can multiply a principal's allowance; it does
  not satisfy the issue's non-bypass security criterion.
- `scripts/soak/run_soak.py:1064-1088` probe cleanup cancels the probe Run;
  this does not execute or fence a physical Attempt across replicas.
- No evidence supplied or executed in this job establishes production telemetry
  thresholds, sustained saturation/reclaim/leak observations, or active-work
  kill/restart physical fencing/recovery for an exact RC artifact.

## Acceptance status

The test suite validates local harness behavior only. Representative supported
workload, two deployed application replicas, long exact-RC soak, physical-work
fencing/recovery, replica-selection-resistant rate limiting, findings
reclassification, and hash-bound promotion evidence remain **UNVERIFIED**.
This validation does not authorize promotion. A selected RC and configuration,
production topology runner with representative workloads, and a complete
hash-bound long soak are required before these criteria can be accepted.
