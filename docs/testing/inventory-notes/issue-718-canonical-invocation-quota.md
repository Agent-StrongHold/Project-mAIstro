---
inventory-delta:
  packages/maistro-core/tests/agents: +2
  packages/maistro-core/tests/capabilities: +2
  packages/maistro-core/tests/quota: +1
---

Adds canonical Invocation quota coverage: a governed model effect records provider usage once despite effect deduplication, missing provider usage is explicit unreported evidence, and verifier outages return reconciliation-unavailable evidence without raising. The production model adapter is exercised through the existing ModelChatEgress and Invocation authorities rather than independent Agent callbacks.
