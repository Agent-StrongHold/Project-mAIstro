---
inventory-delta:
  tests/: +0
---
# auto-390-develop-sync-union

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

## Develop-sync merge union on the root suite (tests/)

The in-flight merge of develop (`b4b9e187e`) into `auto-390` united two test
trees that had each moved the root suite independently. The merged `tests/`
directory is exactly the union of both parents' `tests/` directories (verified
by `git ls-tree` comparison: 226 files on the auto-390 parent, 233 on the
develop parent, 233 in the merge, union == merged, nothing deleted or moved).

The seven develop-side files new to this branch are
tests/security/test_sentinel_permission_table_armed.py,
tests/test_check_closure_targets.py, tests/test_check_image_pins.py,
tests/test_check_principal_identity.py, tests/test_check_route_permissions.py,
and tests/test_check_workspace_retirement.py (plus a shared-file change). No
test was added or removed by this lane; the original delta recorded the merge
arithmetic.

## Superseded: the +18 became a double-count (delta retired to +0)

When written at 79b118c63 this note was true: the union collected 4410 root
node IDs against an expected 4392 (4392 + 18 = 4410, verified by collecting
`tests/` at that head). The 18 nodes were develop-side content the merged
ledger did not yet have rows for.

The later develop syncs (15157c6f merged at b155d677, then 8c8fc8d6 merged at
db25f6ea4) brought develop's OWN inventory-note rows covering those same
nodes. From b155d677 onward the ledger therefore expected the union nodes
twice — once via develop's rows, once via this note — and the root suite
reported a constant `net -18` drift that corresponded to no missing test:
collected went 4410 -> 4419 -> 4423 in lockstep with develop's own ledger
(4419 + 18 = 4437 expected at b155d677; 4423 + 18 = 4441 at db25f6ea4).

Evidence at db25f6ea4, the head that retires the delta:

- The collected node-ID set of `tests/` on this branch is byte-identical to
  develop at 8c8fc8d6 (diff of sorted `pytest tests/ --collect-only -q` output
  is empty; both collect 4423 on the same machine), and develop's own ledger
  expects exactly 4423 for `tests/`.
- The delta-row set of this branch differs from develop's ONLY by this note's
  +18 row; retiring it to +0 makes expected == collected (4423).
- All 212 `tests/` files contribute collected nodes (no silently skipped
  module), and the six union files named above are present and collect
  9/38/38/5/6/19 node IDs respectively.
- Develop itself passes this gate with expected == collected == 4423, so the
  corrected ledger matches reachable collection on both this machine and CI.

No test was added or removed by retiring the delta; the front-matter now
records the note's current (zero) contribution instead of a superseded one.
