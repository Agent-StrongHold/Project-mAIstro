---
inventory-delta:
  packages/maistro-core/tests: +22
---
# 1827-canonical-model-identity

Adds 22 collected cases in `test_governed_llm_execution_identity.py` for exact
canonical Run/NodeRun/Attempt forwarding, missing/whitespace identity refusal,
explicit-run conflicts, implicit turn setup, ended/changed context refusal,
failure-atomic turn state, per-task isolation, and unchanged effect-key resets.

The existing direct adapter and Agent quota-hook cases retain their count and
quota assertions, now with explicit bound context and exact persisted Invocation
identity assertions. No tests are removed, skipped, or weakened. Production
caller admission remains owned by #1084; these adapter fixtures do not prove it.
