---
inventory-delta:
  packages/maistro-design/tests: +26
---
<!-- Measured by scripts/check-suite-inventory.py --update; see README.md. -->
# 793-design-pack-tests-ledger-reconcile

Ledger reconciliation, not a new test change: commit `fb89d5fb2` (M7-A4,
issue #793, "domain packs — product/game/book as bundles of one Run") added
`packages/maistro-design/tests/test_packs.py` (+559 lines, 26 collected node
IDs) and touched `test_importer.py`, but recorded no
`inventory-delta` note, so `packages/maistro-design/tests` has been drifting
+26 against the ledger since that commit landed (`check-suite-inventory.py`
reports `expected 351, collected 377`).

Recorded by the #794 (M7-A5) lane while validating its own inventory: the
drift predates this lane's work (the fork point `0fb3dc69ed95` collects
exactly 351; the branch head after `fb89d5fb2` collects 377) and blocks the
branch-wide gate regardless of #794's changes. The number is #793's, measured
here as `pytest packages/maistro-design/tests --collect-only -q` → 377 vs
baseline 161 + prior deltas 190 = 351. No production or test file changed for
this note.
