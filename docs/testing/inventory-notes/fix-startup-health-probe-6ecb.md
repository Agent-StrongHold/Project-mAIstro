---
inventory-delta:
  packages/maistro-server/tests: +7
---
# fix-startup-health-probe-6ecb

Startup health adds five endpoint cases for incomplete, complete, failed, and
dependency-independent probe behavior, plus two lifespan cases for bootstrap
failure and post-startup runtime failure. The resulting
`packages/maistro-server/tests` inventory delta is +7.
