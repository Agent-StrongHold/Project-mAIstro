---
inventory-delta:
  packages/maistro-core/tests: +63
  tests/: +2
---
# claude-ws-1572-canonical-goal-store-8ff2

**+63 `packages/maistro-core/tests`**, all in the new `tests/goals/`
directory. No existing test was removed or renamed.

- `test_goal_store_conformance.py` (42): 14 tests, each run against the
  memory, sqlite and postgres Goal stores. They cover: create/get round
  trip of the Goal and revision 1, and absent reads; a Project outside the
  Workspace and a duplicate goal_id are refused; revisions are append-only,
  a stale expected_revision is refused, and two concurrent revises produce
  exactly one winner; a terminal transition is final, and transitions are
  compare-and-set on state and revision; Subgoal lineage stays in its
  Project, and a cross-Project or missing parent is refused;
  `list_owned_by_agent` returns only ACTIVE Goals; `reassign_owner` is
  recorded in the revision history.
- `test_goal_service.py` (15): 5 tests, each run against the memory,
  sqlite and postgres URLs through `create_container()`. They cover: the
  Container exposes the expected `goal_store` class and a working
  `goal_service`; a foreign Goal and a missing Goal raise the identical
  `GoalNotFound` with no cause or context; a foreign Workspace cannot list
  or create; a CONTRIBUTOR member can read but not mutate; an OWNER's
  mutations record their principal.

- `test_goal_wiring.py` (6): each Project backend yields its matching Goal
  store. An unmigrated PostgreSQL pool is refused, as is PostgreSQL with no
  pool or SQLite with no connection, rather than falling back to in-process
  Goals. `SqliteGoalStore` refuses a Project store it cannot share a
  transaction with.

**+2 `tests/`**: the new `tests/migrations/test_goals_migration.py`.
One test checks that 041 is the single head after `036_audit_log_org_scope`.
The other runs `upgrade()`/`downgrade()` on SQLite and checks the
same-Project parent key, the state CHECK constraint, the revision primary
key and the cascade from `canonical_projects`.
`test_audit_scope_migration.py`'s head test was renamed in place: it now
checks that the audit revision is on the path to the single head, so its
node count does not change.
