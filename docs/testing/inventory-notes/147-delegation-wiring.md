---
inventory-delta:
  packages/hive-conductor/backend/services/dag_agents.py: ~
---
# 147-delegation-wiring

Fix the resolver for `agent.delegate_remote` to use the container's dependencies when available, ensuring the node is wired with an A2A delegator and guest peer manager in production. This prevents the node from being constructed with None for these dependencies, which would cause delegation to fail with a wiring error rather than being mistaken for a remote agent declining the work.

The change replaces the module-level fallback resolver (built once at import time with no arguments) with a per-execution resolver that is built from the container's dependencies when available, or built with no arguments only in standalone mode.

Two `test_dag_agents.py` tests pinned the removed module-level singleton identity
(`dag_agents._fallback_node_resolver`) rather than the behavior the AC-5 marker
names. They now assert the per-execution contract: the no-bridge resolver is a
fresh callable per invocation (so it cannot freeze process defaults at import
time), the engine-error path returns a working resolver instead of propagating,
and both still resolve the delegate node unwired in standalone mode. No test
functions were added or removed.
