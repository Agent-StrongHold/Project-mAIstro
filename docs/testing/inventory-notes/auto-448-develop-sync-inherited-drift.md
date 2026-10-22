---
inventory-delta:
  tests/: +1
---
# auto-448-develop-sync-inherited-drift

Lane L448 (issue #448) was required to resolve its develop-sync block by merging
origin/develop (2f56be40a) into `auto-448`. After that merge the root `tests/`
suite collects **5261** node IDs against an expected **5260** (net **+1**).

This delta is **inherited, not authored**: the drift reproduces identically on
pure origin/develop at 2f56be40a (throwaway worktree, `pytest tests/
--collect-only -q` → 5261 collected; `check-suite-inventory.py` → same
`DRIFT tests/: expected 5260, collected 5261`). `git diff origin/develop HEAD
-- tests/` is empty, so this branch's own changes did not move the suite. Some
earlier develop landing recorded no note; for example #2154's
`1881-restore-oracle-snapshot-consistency.md` records exactly its `tests/: +19`
and those files collect exactly 19, so the orphan +1 predates that PR's
accounting. Naming the authoring PR belongs to develop integration, not to
this lane.

Recorded here so the branch is green after its mandated sync. The direction is
the safe side — more nodes collect than the ledger knows, so no coverage is
silently lost. Any branch syncing develop after this drift landed will need
the same one-line inheritance (or the integration compaction that folds it).
