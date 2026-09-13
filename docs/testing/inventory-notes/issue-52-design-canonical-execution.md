---
inventory-delta:
  packages/maistro-design/tests: +2
  packages/hive-conductor/backend/tests: +1
---
# Issue #52 Design canonical execution

Adds two integration tests proving a Design Studio operation is admitted as a canonical Run over one NodeRun and Attempt, and that a provider failure remains a failed Attempt while the adapter terminalizes the logical NodeRun and Run truthfully.
