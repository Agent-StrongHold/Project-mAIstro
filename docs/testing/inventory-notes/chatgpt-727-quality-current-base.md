---
inventory-delta:
  tests/: +3
---
# Long-lived PR wiring-ratchet base selection

Issue #727 adds three root-tool tests that pin the event boundary for the wiring-reads ratchet: pull-request Quality runs use the current integration target instead of the PR object's historical base SHA, shallow/local pull-request test jobs without an explicit ratchet base keep their existing fallback behavior, and non-PR events preserve the exact revision supplied by their workflow.
