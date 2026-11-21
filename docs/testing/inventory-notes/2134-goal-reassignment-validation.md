---
inventory-delta:
  packages/maistro-core/tests: +23
---

# 2134-goal-reassignment-validation

PR #2134 pins invalid Goal owner reassignment at the scoped and PostgreSQL
boundaries and refuses alternate-store fallback when a deployment requires
PostgreSQL.

`test_goal_store_conformance.py` gains parametrized invalid-owner refusals
across memory/SQLite/PostgreSQL (blank, whitespace, padded ids), plus
PostgreSQL-only proofs that a successful reassignment keeps the owner column,
JSONB payload, and transition history consistent; concurrent reassignments
elect one winner with matching evidence; and sequential reassignments record
both owner changes. `test_goal_wiring.py` gains the require-postgres refusal
paths (memory and SQLite fallbacks) and the container wiring that selects
PostgreSQL when the deployment URL or pool demands it.
