---
inventory-delta:
  packages/maistro-design/tests: +3
---
# Refactor the consistency evaluator's three C-complexity blocks (#1791)

Three new collected cases in `packages/maistro-design/tests/test_consistency.py`
pin the extracted decision paths of the #1663 consistency evaluator at their
observable behavior, so the #1791 decomposition (17/16/15 → 8/6/6) cannot
quietly change routing:

- `test_local_sibling_contradiction_targets_both_branches` — a sibling
  contradiction neither side grounds in a consumed decision must degrade to
  LOCAL origin with the union of the two local closures as impact, in both
  match orientations; refinement routes exactly both branches with nothing
  requiring unlock. Existing coverage only had the shared-origin sibling.
- `test_locked_decision_requires_unlock_on_consumers_only` — lock state flows
  to targets through consumption edges: an unlocked artifact consuming a
  locked decision is `requires_unlock` while its own `locked` stays false, a
  mere dependent of a consumer stays freely refinable, and the
  `locked_decisions` dimension cites the decision. Existing coverage only had
  artifact-locked targets.
- `test_target_reason_merges_every_finding_touching_the_artifact` — one
  artifact hit by several errors is proposed once, with one reason per finding
  joined in finding order and exactly those finding ids attached.

Both named regression suites (#1663's evaluator suite and the
hive-conductor consistency route) pass unchanged; a normalized
findings/refinement fingerprint over eight snapshot shapes is byte-identical
before and after the refactor. No grant is raised: the three radon ledger rows
and their #1682 grants are removed (the rows became stale when the blocks
dropped below C), and the xenon block floor moves 145 → 142 by the same
−3, following the #1674 precedent.
