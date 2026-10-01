---
inventory-delta:
  packages/maistro-core/tests: +30
---
# auto-25-d3c0

Delta recorded for branch `auto-25` (EPIC M4-E, issue #25 — "Harness
components as evolvable targets"). All +30 node IDs come from the new
`packages/maistro-core/tests/graph/test_harness_targets.py` suite (21 test
functions; 13 of them run against all three template-store backends, hence
30 net new collected IDs over the recorded baseline). Rationale and per-test
breakdown are in [m4e-harness-targets.md](m4e-harness-targets.md), written in
the same round; nothing was removed and no other suite moved.
