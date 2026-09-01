---
inventory-delta:
  tests/: +5
---

# Merge-group specialized-job gating

Adds five focused root-suite checks for the final #655 workflow slice. They pin `workflow-lint` as the already-required scope-output producer, every specialized job-to-output mapping, develop-only merge-group gating, the distinction between merge-group base targeting and PR base filtering, and the absence of a new scope check that would expand the required/advisory contract.

Pull requests, protected pushes, and non-develop merge groups preserve the existing specialized validation semantics. For the develop merge queue, `ci_merge_group_scope.py` fails closed to every leg when base/diff evidence is unavailable.
