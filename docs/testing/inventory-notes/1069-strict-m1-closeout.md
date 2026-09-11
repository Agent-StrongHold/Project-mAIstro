---
inventory-delta:
  tests/: +3
---
# Issue #1069 strict M1 closeout parity

Adds three focused tests to `tests/cross_product_parity/test_cross_product_parity.py`:
one proves a missing dependency emits machine-readable `FAILED` evidence without invoking
the producer, and one proves a source-ready scenario that abstains still fails in
strict mode. The existing product scenario tests now use the closeout runner;
development mode retains named diagnostic blockers, while the release workflow
runs `MAISTRO_PARITY_MODE=m1-closeout` and cannot treat `BLOCKED` as green.
