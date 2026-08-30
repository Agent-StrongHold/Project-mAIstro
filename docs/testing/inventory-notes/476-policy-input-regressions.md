---
inventory-delta:
  tests/: +5
---

# Autonomous merge policy-input regressions

Adds five focused regressions for the remaining #476 P1 findings: all quality policy inputs, quality checker scripts, imperative pytest/unittest skips, and `.gitattributes` as a trusted diff-control surface. Workflow lint covers the added `edited` pull-request activity used to rerun the gate after base-branch changes.
