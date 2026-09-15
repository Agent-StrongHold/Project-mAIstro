---
inventory-delta:
  packages/maistro-core/tests: +0
---

# Issue 1241: Sentinel residual schema errors

One existing collected test node in
`packages/maistro-core/tests/security/test_sentinel_validator.py` was rewritten
and renamed in place: an unrelated fuzzy enum repair must not override a residual
type error. The regression now asserts that the verdict is denied and exposes no
repaired payload. No test nodes were added or removed; one node was renamed, so
the suite delta is zero.
