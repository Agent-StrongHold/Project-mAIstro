---
inventory-delta:
  packages/maistro-core/tests: +3
  tests/: +12
---
# Test discovery and scheduling reconciliation (#2537)

CI run 45959922342 measured +3 core and +7 root collected IDs on 31de0a7. PostgreSQL job 140374642735 passed all three new backend cases. This follow-up adds five unparametrized root regression tests for collection outcomes, Git enumeration and CLI dispatch, predicting +12 root total; the next CI run must confirm the exact count. No shared baseline edit. Removing the root orphan changes no collected IDs.
