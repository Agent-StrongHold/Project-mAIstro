---
inventory-delta:
  tests/: +21
---

# Issue #85: live merge-boundary verification

Complete the salvaged, truncated read-back tests and add negative checks for
inactive/evaluate rulesets, wrong branch targets, strictness and review-policy
drift, stale default-branch metadata, missing verification credentials,
unreadable classic protection, ambiguous selectors/overlapping rulesets, and
generated live-document drift. A documented divergence must still make live
verification fail: recording evidence is not authorization to weaken policy.

The inventory is collection-based; no baseline or quality grants are changed.
Live GitHub differences require a separately authorized settings decision; the
local implementation is not evidence that those acceptance criteria are met.
