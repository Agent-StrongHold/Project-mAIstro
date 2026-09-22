---
inventory-delta:
  tests/: +3
---

# Issue #751 validator repair (immutable execution requirements)

Adds three collected regression tests: an `implemented` claim must reference at least one
immutable execution record, a forged (non-canonical) execution ID is rejected even when the
repository-owned receipt matches it, and an immutable execution ID without a receipt fails closed.

Correction (2026-09-22): this note originally recorded `tests/: +8`, padding the three real test
additions with five IDs to absorb an observed suite drift. That attribution was wrong — the drift
came from this branch's own notes recording +31 deltas for a file that collects 26 nodes, and the
padding left the ledger over-counting by five. The delta here is restored to the three tests this
change actually added; the branch's notes now sum to its real collection.
