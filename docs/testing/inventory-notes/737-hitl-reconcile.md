---
inventory-delta:
  packages/maistro-core/tests: +1
---
# HITL terminal mirror recovery

Issue #737 adds one focused regression test proving that a crash after durable
HITL settlement evidence is written but before canonical Run mirroring is
restart-repairable without creating another Attempt.
