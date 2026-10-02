---
inventory-delta:
  tests/: +14
---
# feat-cutover-s0-1-retirement-ledger-c421

All 14 are new, in `tests/test_check_workspace_retirement.py`, covering the
Workspace cutover retirement ledger gate (`scripts/check-workspace-retirement.py`,
#1046 cutover S0.1). They pin schema rejection, deleted-but-present and
missing assets, new importers of a retiring page/router/store, stale importers
that must be pruned, and that the real repository passes; nothing was removed.
