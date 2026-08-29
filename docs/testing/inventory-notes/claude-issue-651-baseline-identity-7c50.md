---
inventory-delta:
  tests/: +13
---
# claude-issue-651-baseline-identity-7c50

All thirteen are `tests/test_reachability_baseline_identity.py`, the suite for
SPEC-082926-f1c3: the reachability baseline stores the scoped module identities
the walk produces, not the labels the report prints.

Nothing was removed, and no existing test was replaced by a new one — the delta
is the whole of the new file. Four existing tests changed their case analysis
from labels to identities in place (`test_check_reachability.py`,
`test_reachability_scanner.py`, `TestToolingReachesTheTopRung` in
`test_check_ac_state.py`), which moves no node IDs.

One of those four is worth naming: `test_the_real_ledger_agrees_with_both` asked
the committed baseline whether a dead script grades below `reachable`, and
answered correctly only while both sides used the label spelling. It is the
defect this change fixes, caught by a test written before there was a second
reader of the baseline.
