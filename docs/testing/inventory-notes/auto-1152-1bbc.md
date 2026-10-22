---
inventory-delta:
  packages/maistro-core/tests: +2
  packages/maistro-server/tests: +1
  tests/: -3
---
# auto-1152-1bbc

Post-develop-sync reconciliation of the #1152 branch against
develop@c29e0ea70 (merges a0f572bef + 144465814), recorded as one
correction note because the three movements net against each other:

- `packages/maistro-core/tests: +2` — the branch's own Run-access tests
  (`tests/runs/test_access.py` cases and the authz-tier-ladder and
  container-wiring additions) as they stand on top of develop's suites.
- `packages/maistro-server/tests: +1` —
  `test_cancel_stays_with_the_initiator_or_an_administrator` pins that
  Workspace membership admits Run reads, never cancellation (#1152
  review): a peer member's cancel is refused with the read seam's 404,
  the initiator and a Workspace administrator still succeed.
- `tests/: -3` — the branch's parallel readiness-gate tests
  (`test_wait_for_postgres_*` from e8971bad1) are dropped: develop
  converged on a stricter bounded TCP `SELECT 1` readiness probe with its
  own already-baselined decision-rule tests (in-file fakes plus the
  stub-docker `test_restore_oracle_readiness_gate.py`). The root `tests/`
  tree is byte-identical to develop@c29e0ea70 after the merge, so the -3
  retires the branch-side baseline row, not any develop test.
