---
inventory-delta:
  packages/hive-conductor/backend/tests: +31
  packages/hive-conductor/tests/e2e: +0
---

# Fixem — Attention dismiss, #1036 writers, learned landing, chat continuity

- `test_attention_projection.py` — dismiss hides item + route authz (+2);
  ValueError→400, blank/unknown action helpers, include_dismissed (+3)
- `test_dag_run_projection_lifecycle.py` / `test_dag_run_canonical_lifecycle.py`
  — nonterminal status exact + spy `record_status` (assertions, not new files)
- `test_dag_execution_transport_parity.py` — live nonterminal (+5) + no-failed
  coerce (+3)
- `test_workspace_learned_landing.py` — streak / suppress / explicit policy (+7
  with parametrize)
- `test_chat_run_admission.py` — `_client_turn_id` + admit_turn records it (+2)
- `test_home_routes.py` — `_goal_items` skip/title/runs map (+1)
- Playwright: `workspace-conversation-continuity.spec.ts` (new), Attention
  dismiss round-trip, learned-landing accept/dismiss e2e. Suite inventory
  collects pytest only — e2e stays +0 here.
