---
inventory-delta:
  tests/: +1
---
# Inherited `tests/` suite drift absorbed at the #12 develop merge

This change adds **zero** test nodes to `tests/`: the collected node-ID set of
`pytest --collect-only -q tests/` on this branch's merge of `origin/develop`
(2f56be40a) is byte-identical to the same collection on `origin/develop`
itself. The +1 below records drift this candidate inherits, not a test it
adds.

Evidence (2026-10-18): on `origin/develop` at 2f56be40a, the gate already
reports `DRIFT tests/: expected 5260, collected 5261` — the ledger on develop
is off by one before this branch touches anything. The most recent `tests/`
addition is f277bae57 (#2154, note `1881-restore-oracle-snapshot-consistency.md`,
claimed `tests/: +19`); the merged tree's collection is one node above the
recorded sum, so that note (or an earlier one) undercounts by one. This is the
parametrization-interaction case the suite-inventory docstring predicts: the
sum stops matching collection, the check fails loudly, and the candidate that
sees it re-records the delta.

A candidate tree must satisfy `expected == collected`, so this note carries
the inherited +1 to make the merged tree's ledger true again. The identity of
the extra node is not attributed here because the ledger stores counts, not
IDs; if a later compaction wants the row exact, re-run
`scripts/check-suite-inventory.py --update` on the tree where the node
actually appeared.
