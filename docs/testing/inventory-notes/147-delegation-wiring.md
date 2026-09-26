---
inventory-delta:
  packages/hive-conductor/backend/services/dag_agents.py: ~
---
# 147-delegation-wiring

Fix the resolver for `agent.delegate_remote` to use the container's dependencies when available, ensuring the node is wired with an A2A delegator and guest peer manager in production. This prevents the node from being constructed with None for these dependencies, which would cause delegation to fail with a wiring error rather than being mistaken for a remote agent declining the work.

The change replaces the module-level fallback resolver (built once at import time with no arguments) with a per-execution resolver that is built from the container's dependencies when available, or built with no arguments only in standalone mode.