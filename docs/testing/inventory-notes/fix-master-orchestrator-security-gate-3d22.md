---
inventory-delta:
  packages/maistro-core/tests: +1
---
# fix-master-orchestrator-security-gate-3d22

One maistro-core node ID covers master orchestrator progress: the canonical
WorkItem must stay `IN_PROGRESS` while the handler runs on an isolated copy,
so `get_progress()` reflects long-running work instead of a stale pre-handler
status.
