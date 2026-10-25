---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---

# 1049 — Attention degrades when HITL spine is unavailable

Adds `test_attention_answers_when_the_hitl_spine_is_unavailable`: standalone /
e2e Conductor without a wired graph spine returns Attention 200 with
`summary.hitl_unavailable` rather than raising `CanonicalGraphUnavailable`
into a 500. Failed-Run projections still answer when present.
