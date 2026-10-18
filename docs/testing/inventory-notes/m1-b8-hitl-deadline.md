---
inventory-delta:
  packages/maistro-core/tests: +15
---

# M1-B8 HITL deadline preservation

Adds durable SQLite restart coverage for all three human verdict nodes: repeated
blank verdicts at advancing pre-deadline times retain the original pause
`resume_at` and expire at that deadline, while valid pre-deadline verdicts still
complete. Adds one focused unit regression proving malformed verdict re-pauses
reuse carried durable pause evidence.
