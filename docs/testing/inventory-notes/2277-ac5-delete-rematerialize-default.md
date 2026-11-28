---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---
# 2277 AC-5 delete + re-materialize default

Focused re-validation of merged #2277 / PR #2292: pin the AC-5 flow — after a
Workspace delete (whose cascade removes the Workspace Agent row outright) and a
later re-materialization for a successor Workspace, the fresh Agent row is born
with the default `program_manager` persona, a swapped persona never ghosts onto
the successor, and the successor swaps like any other.

## packages/hive-conductor/backend/tests: +1

- `test_workspace_agent_identity.py` (+1)
  `test_after_delete_and_re_materialization_the_default_persona_returns`:
  resolve → swap to `delivery` → delete workspace (row gone) → new Workspace
  resolves a fresh row (`program_manager`, different id) → swap again holds.
  Red-checked: mutating the fresh-materialization default makes the test fail.
