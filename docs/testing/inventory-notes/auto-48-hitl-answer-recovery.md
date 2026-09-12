---
inventory-delta:
  packages/maistro-core/tests: +1
---
# auto-48-hitl-answer-recovery

Adds a canonical durable HITL regression for a crash after the accepted answer continuation is persisted and the canonical Run mirror has not yet transitioned. The test verifies targeted restart repair, successful resume, and preservation of physical Attempt history while a new Attempt completes.
