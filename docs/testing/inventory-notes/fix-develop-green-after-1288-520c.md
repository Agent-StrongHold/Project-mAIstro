---
inventory-delta:
  packages/maistro-core/tests: +1
  tests/: +5
---
# fix-develop-green-after-1288-520c

Two deltas with two different owners; only the first is this branch's.

- `packages/maistro-core/tests`: +1 —
  `tests/runs/test_execution.py::test_a_launch_refused_by_the_store_settles_the_attempt_as_cancelled`
  pins the executor fix. A store that refuses the Attempt's RUNNING write used
  to surface `InvalidLifecycleTransition` (FAILED is not reachable from
  CREATED) instead of the refusal itself. The Attempt now settles as CANCELLED
  with the refusal as its error, the refusal propagates, and the NodeRun parks
  exactly as it would after a FAILED Attempt.

- `tests/`: +5 — not this branch's. `develop` already collects 3442 node IDs
  under `tests/` against a recorded 3437: #1400 (`e8aef373`,
  `tests/test_ac_state_review_slack.py`, +3) and #1360 (`2c118402`, +2) landed
  without an inventory note, behind a `quality` job that was already failing
  at its radon step and so never reached the inventory check. Recorded here
  because the gate is per-tree and this is the first branch measured against
  a base that carries them. No test was removed or renamed anywhere.
