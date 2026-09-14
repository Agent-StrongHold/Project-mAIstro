---
inventory-delta:
  tests/: +17
---

Issue #374 adds three root-suite checks for the governing-citation ratchet's
second corpus: the convergence matrix. They cover a Proposed matrix authority,
an explicitly historical supersession note, and a Superseded authority resolving
to its active replacement. The checks share the registry status graph rather
than maintaining a second citation policy.

The recorded net delta is +17: +3 is this repair's new coverage, while +14
reconciles node IDs already present at the starting head but not represented by
the earlier #374 inventory note. The value was produced by
`check-suite-inventory.py --update`, not estimated from `def test_` counts.
