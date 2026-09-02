---
inventory-delta:
  tests/: +7
---
# chatgpt-merge-group-scope-outputs

Seven focused root-suite tests pin the event-to-scope output contract and the classifier dependencies used by the merge-group CI follow-up.

Pull requests preserve every specialized leg, merge groups consume changed-path classification, missing merge-group diff evidence fails closed to every specialized leg, rendered GitHub outputs include every leg plus the full JSON scope, rename detection is disabled so both sides of moves retain scope, changes to the scope-control scripts force every specialized leg, and the shared maistro-core PostgreSQL fixture enables each database-backed specialized leg that depends on it.

The output contract now lives in the already-reachable `scripts/ci_merge_group_scope.py` instead of a second temporarily-unreachable helper. That removes the temporary reachability baseline/disposition churn that would otherwise collide with #712's freshly merged ledger cleanup.

No existing test was moved, renamed, parametrized, or deleted, so this slice changes root-suite collection by exactly +7 node IDs.
