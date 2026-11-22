---
inventory-delta:
  tests/: -8
---

# auto-891-develop-sync-inventory-reconciliation

The develop sync (merge of `ed44fa44b` + `774ae42fc` into auto-891) collapsed
a same-file twin: this branch's #2238/#891 CI-repair round had added
`tests/test_pinned_digest_references.py` (8 collected nodes, recorded as
`tests/: +8` in `2238-container-gate-base-pin-refresh.md`), and develop landed
its own independent copy of the same suite through #1152 with the identical
`tests/: +8` recorded in `1152-container-gate-base-pin-refresh.md`.

The merged tree carries the file once (this branch's version — same eight
test functions; the merge resolution only kept its richer provenance
docstrings), so the duplicate `+8` now double-counts against the baseline:
`check-suite-inventory.py` expected 5818 for `tests/` while collection yields
5810. No test is missing — the 8 node IDs are present at HEAD
(`tests/test_pinned_digest_references.py::test_*`); the ledger merely holds
one delta too many for the same nodes. This note records `tests/: -8` to
cancel the second copy's delta, per the same convention as
`auto-465-merge-forward-reconciliation.md`.
