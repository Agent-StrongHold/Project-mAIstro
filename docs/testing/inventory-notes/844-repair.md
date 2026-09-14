---
inventory-delta:
  packages/maistro-core/tests: +1
  packages/hive-conductor/backend/tests: +3
---
# Issue #844 repair evidence

The repair suite proves that Agent outcome writes retain the canonical
Project and Run/NodeRun/Attempt provenance, and that feedback first passes the
canonical Run/Workspace inspection door. Feedback cannot override the Run's
Project with a caller-controlled body value, and missing or unscoped Runs are
refused before an Outcome write.
