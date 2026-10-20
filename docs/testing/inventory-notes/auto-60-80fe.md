---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
  packages/maistro-core/tests: +2
---
# auto-60-80fe

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

Hive-conductor +2 reflects new sentinel-gated host execution paths in test containers
(canonical_graph_spine, chat_run_spine, transport-parity/sqlite spines). maistro-core +2
is collection-environment variance, not source changes.
