---
inventory-delta:
  packages/maistro-core/tests: +5
---
# Issue 1114

Five tests cover the restart-safe task admission contract: task payload fields
are committed on the queued Run, a new queue rehydrates and notifies from that
Run, two rehydrated receipts are fenced by the canonical transition, and a
malformed payload is terminalized visibly on the Run.
