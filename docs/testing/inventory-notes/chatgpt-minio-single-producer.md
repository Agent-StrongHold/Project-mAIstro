---
inventory-delta:
  tests/: +1
---

# MinIO single-producer ownership

Adds one root-suite contract test for #654. The test proves that the canonical
`coverage (MinIO)` workflow remains the sole executor of the archive conformance
suite, keeps strict S3-leg and branch-coverage evidence, and stays required while
the legacy `object storage (MinIO)` context delegates to that proof.

The same test tampers each load-bearing boundary so duplicate execution, a
weakened MinIO producer, or removal of the canonical required check fails closed.
Image-version policy is deliberately unchanged by this execution-dedup tranche.
