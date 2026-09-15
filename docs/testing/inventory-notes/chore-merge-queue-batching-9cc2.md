---
inventory-delta:
  tests/: +19
---
# chore-merge-queue-batching-9cc2

Merge-queue batching posture change (`.github/merge-queue.json`
`max_entries_to_merge` 1 → 3, `min_entries_to_merge_wait_minutes` 0 → 2) with
the audit gate (`scripts/check-required-checks.py`) moved from pinning the
rollout value `== 1` to enforcing the reviewed batching bounds.

Net +19 node IDs in `tests/` (root), all in `test_check_required_checks.py`:
the single-PR-group rollout test (1 ID) was replaced by the invariant family
for the new posture — max=3/wait=2 accepted, shipped conservative max=1/wait=0
still accepted, group sizes outside 1–3 rejected including non-integer and
boolean JSON values (5), `min_entries_to_merge` > max and = 0 rejected (2),
reviewed wait values {0, 2, 3, 5} accepted (4), unreviewed waits including
non-integers rejected (5), and malformed-JSON contracts for both
`branch-protection.json` and `merge-queue.json` now fail closed with a typed
gap instead of a traceback (2). One pre-existing assertion was also tightened
from `any("no merge_group" …)` to exact gap equality. Validation coverage
strictly increases: every value the old gate accepted it still accepts, and
several it silently crashed on are now typed failures.
