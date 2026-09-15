---
inventory-delta:
  tests/: +24
---

Issue #374 adds three root-suite checks for the governing-citation ratchet's
second corpus: the convergence matrix. They cover a Proposed matrix authority,
an explicitly historical supersession note, and a Superseded authority resolving
to its active replacement. The checks share the registry status graph rather
than maintaining a second citation policy.

The recorded net delta is +24: +1 is this repair's historical-context regression,
+1 is the parenthetical-followed-by-governing-authority regression, while +22 covers
the existing status-graph and matrix coverage whose collected node IDs were not fully
represented by the earlier #374 note. The value was produced by `check-suite-inventory.py
--update`, not estimated from `def test_` counts.
