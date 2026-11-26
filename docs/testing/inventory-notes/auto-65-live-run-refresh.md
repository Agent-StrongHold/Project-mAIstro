---
inventory-delta:
  packages/hive-conductor/tests/e2e: 0
---

# Issue 65 — live canonical Run inspection

Three Playwright regressions extend the existing Goal/Run navigation spec:
canonical Attempt/status polling without legacy events, reconnect/resync reads,
and a delayed detail response after deselection. These are browser contract
tests with network fixtures, not production producer-to-browser integration.
The pytest inventory for this directory is unchanged (zero delta); Playwright
collects the three additional cases separately.

Validation and remaining acceptance gaps are recorded in
`docs/testing/auto-65-live-run-repair.md`.
