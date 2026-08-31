---
inventory-delta:
  tests/: +4
---

# Merge-group specialized-job gating

Adds four focused root-suite checks for the final #655 workflow slice. They pin the cheap scope producer, every specialized job-to-output mapping, the distinction from the required `integration-scope` verdict, and the unconditional core jobs that must never wait on specialized scope.

The workflow policy remains fail-closed: pull requests and protected pushes receive all `true` outputs from `ci_merge_group_scope.py`, while merge-group ambiguity also enables every specialized leg.
