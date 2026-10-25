---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
---
# 2276 tool-binding diff coverage

Diff-coverage follow-up for #2276 / PR #2286 after reachability banking.

## packages/hive-conductor/backend/tests: +2

- `test_tool_binding.py` (+1): `binding_prompt_fragment` / missing-presentation
  paths against the presentation store.
- `test_agent_materialization.py` (+1): runtime materialization appends sticky
  `prompt_fragment` into the upserted soul body.
