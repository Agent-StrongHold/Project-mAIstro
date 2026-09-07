---
inventory-delta:
  packages/maistro-core/tests: +10
---
# issue-56-governed-model-egress

M1-D2 governed model egress (#56). `packages/maistro-core/tests` gained a net
10 node IDs:

- `tests/capabilities/test_model_chat_egress.py` (new file, +10 after
  collection): the focused egress suite — Invocation creation with
  usage/cost/model/provider metadata attached, Binding-pin vs cost-aware
  router selection parity (default and budget-constrained), pinned-but-
  unavailable refusal (fallback cannot widen authorization), unregistered
  gateway-alias passthrough with cost absent rather than zero, completed-
  effect deduplication, unreachable-gateway `EffectNotApplied` with one
  retryable re-attempt, and UNKNOWN-outcome blocking (`UnsafeEffectRetry`).
- `tests/graph/nodes/test_sync_kinds.py` / `test_sync_kinds_branch_coverage.py`
  / `test_sync_kinds.py` catalog tests: no count change — the existing
  llm.summarize tests were re-pointed at the governed contract (registered
  model.chat Binding via a fixed-`created_at` idempotent fixture, distinct
  NodeRun ids so each test owns its effect identity) and assert the same
  request/response shapes as before the migration.

No suite silently stopped collecting — the 10 IDs are all tests the egress
boundary intentionally added.
