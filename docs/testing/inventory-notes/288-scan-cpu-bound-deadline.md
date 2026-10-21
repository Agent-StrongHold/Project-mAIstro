---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
---
# 288-scan-cpu-bound-deadline

## What moved

`packages/hive-conductor/backend/tests` +3 node IDs (3885 → 3888): two in
`test_agents_routes.py`, one in `test_agent_materialization.py`. No nodes
removed or relocated elsewhere — this is purely additive.

## Why

Added `test_a_cpu_bound_scanner_cannot_outrun_the_deadline`, parametrized
over the two agent scan routes (`/v1/agents/scan` and `/v1/agents/a1/scan`).
It installs a Warden whose `scan` is a non-yielding, synchronous busy-loop
(that is the shape a regex/heuristic walk takes on the request loop) and
asserts the route returns the explicit-unknown `503` rather than a `200`
clean verdict returned *after* the deadline. The status (not a timing
assertion) distinguishes the off-loop implementation from a blocking one:
pre-fix the route answered `200` once the synchronous call returned.

This is the behavioral proof that the fake-clean path is gone — the scan
runs on a worker thread with `wait_for` able to cancel, so a CPU-bound
detector cannot silently starve the timeout.

Added `test_a_scan_that_finishes_after_the_deadline_is_a_no_op`, which
drives `_run_scan_off_loop` directly: the deadline wins, the abandoned
worker later delivers its result onto the request loop, and that delivery
finds the request already resolved. The assertions are structural — the
request is already resolved when the delivery lands, and the loop still
runs work afterwards — not a latency bound. It is the coverage for the
guard that makes a late delivery a no-op: `set_result` on a cancelled
future raises `InvalidStateError`, and the guard is what keeps that from
escaping into the event loop.

## Compensating changes

None. The three extra node IDs are the two parametrized paths of the first
test function plus the second test function; `test_skills_routes.py`
provenance assertions were added to existing tests, not as new collected
nodes.
