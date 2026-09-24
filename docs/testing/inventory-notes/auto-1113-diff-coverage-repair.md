---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
---

# auto-1113 diff-coverage repair: no-spine truth through tool surfaces

Closes the `check-diff-coverage.py` gaps left by the #1113 cutover itself:
the commit that retired the standalone Graph fallback added unavailable/
failed-shape handling to three execution-adjacent tool surfaces but drove
none of them, so the branch failed its own changed-line coverage gate
(`substrate_tools.py:43,46`, `chat_completion.py:1649`, `optimizer.py:109`).

Adds three collected tests:

- `tool_run_workflow` projects `CanonicalDagExecutionError` whose result says
  `unavailable` as the same degraded status (with `run_id=None`), never a
  generic tool failure or a `node_results` read off an exception
  (`test_substrate_tools.py`).
- the chat `_tool_run_workflow` producer keeps the unavailable shape through
  the status decision: `status=unavailable`, `run_id=None`, the spine error
  verbatim (`test_dag_run_history_durability.py`, alongside the existing
  producer-status cases).
- the optimizer route treats a failed baseline Run as *no baseline*: it does
  not short-circuit like the unavailable shape, but `baseline_score` is 0.0
  and no proposal validates because every variant run fails identically
  (`test_optimizer.py`).
