---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
---

# 1049 — MERGE MessageBoard + OptimizationInbox into Attention

- Projects unread messages + pending optimizer proposals into
  `services/attention.py` (proactive/Waiting default for optimizer).
- Deletes `MessageBoard.tsx` / `OptimizationInbox.tsx`; redirects old URLs
  to `/attention`; retirement ledger MERGE rows `deleted: true`.
- Unit: priority ladder, age-not-escalation, message/optimizer class map (+3).
- Playwright: legacy `/messages` `/optimizer` land on Attention without module
  revival (`workspace-attention-shell` + `navigation-coverage`) — Playwright
  specs do not move the pytest-collected e2e count.
