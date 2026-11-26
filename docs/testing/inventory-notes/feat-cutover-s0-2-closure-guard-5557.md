---
inventory-delta:
  tests/: +27
---
# feat-cutover-s0-2-closure-guard-5557

Adds `tests/test_check_closure_targets.py` (27 node IDs, all new; nothing
removed or moved) for `scripts/check-closure-targets.py`, the Workspace Cutover
S0.2 guard that refuses a PR whose `Closes/Fixes/Resolves #N` targets an epic,
milestone, initiative or an issue with sub-issues (#56). The GitHub lookup is
monkeypatched, so the suite stays offline.
