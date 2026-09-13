---
inventory-delta:
  packages/maistro-core/tests: +7
---

Adds canonical Invocation quota coverage: a governed model effect records provider usage once despite effect deduplication, missing provider usage is explicit unreported evidence, and verifier outages return reconciliation-unavailable evidence without raising. The production model adapter is exercised through the existing ModelChatEgress and Invocation authorities rather than independent Agent callbacks.
