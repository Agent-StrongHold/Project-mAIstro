---
inventory-delta:
  packages/maistro-core/tests: +4
---
# claude-m1-251-unresolvable-runs-e4b4

Four new tests in `tests/runs/test_consumption.py` for #251's second
acceptance criterion — a Run this process cannot resolve must fail visibly
rather than sit unstarted — all purely additive:

- an owned Run whose single node names an unregistered kind is terminalized
  `FAILED` with `unresolvable_node_kind` and the offending kind in its error,
  where before it was filtered out before the claim and stayed QUEUED forever;
- a multi-node Run still waits, because traversal (#44/#34) will run it —
  "not yet" must not be disposed of as "never";
- a Run from an admission source outside the allowlist is untouched, whether
  its kind resolves here or not;
- two concurrent ticks dispose of one unresolvable Run exactly once, the
  claim serving as the mutex for disposal as it already does for execution.
