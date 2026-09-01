---
inventory-delta:
  packages/maistro-core/tests: +2
---
# Circuit-breaker review follow-up

Adds two collected regression tests for the PR #828 review findings: late success after the probe lease deadline is refused without requiring an intervening state poll, and explicit resolution of a probe owned by a long-lived task removes the registered done callback.

No existing test node is removed or moved.
