---
inventory-delta:
  tests/: +6
---

# 1572-goal-installed-base-upgrade

The 2026-10-06 clarification on #1572 added an acceptance boundary this
branch's earlier migration numbering violated: develop merged the user-model
tables as `056_user_model_facts` (#1951's merge `c560d4c`) and planner
stability as `057_run_store_planner_stability` (#1914's merge `4675101`), so
those identities are already installed on real databases. The candidate had
renumbered them — Goals at `056`, user-model `057`, planner `058` — which
would make `alembic upgrade head` on such a database treat the Goal DDL as
already applied and silently skip it.

**+6 `tests/`**, all in the new `tests/migrations/test_goal_installed_base_upgrade.py`.
No existing test was removed or renamed.

- `test_merged_ids_keep_their_meaning_and_goals_appends_after_them` — the
  revision graph is the installed-base contract: `056` parents on the quota
  door, `057` on `056`, the Goal store takes a fresh `058` off the integrated
  head, single head `058`, and the filenames carry the merged identities. No
  server needed; fails on the renamed tree at two assertions.
- `test_restored_files_are_byte_identical_to_the_merged_snapshots` — pins the
  restored `056`/`057` files byte-for-byte against `git show c560d4c:…` /
  `git show 4675101:…`; skips when a shallow checkout lacks those commits.
- `test_a_database_at_merged_056_has_user_model_tables_and_no_goal_tables` —
  the regression named directly: at `056` the catalog must hold user-model
  tables and none of the Goal tables, then the ordinary `upgrade head` (no
  stamp edit, no reset) adds the Goal DDL and preserves inserted rows.
- `test_an_installed_base_built_by_develop_c560d4c_forward_upgrades` — the
  actual snapshot tree's alembic directory is extracted (`git archive`) and
  runs the upgrade itself, so schema, DDL and stamp are exactly what that
  develop merge produced; the candidate then takes the same database forward.
- `test_an_installed_base_built_by_develop_4675101_forward_upgrades` — the
  same walk from the planner snapshot: stamped `057`, planner indexes and the
  status CHECK already in place, only the Goal DDL left to apply.
- `test_the_upgraded_base_serves_the_durable_goal_composition` — after the
  upgrade the durable composition works on the migrated schema: Goals,
  revisions and a Run bound at admission are written through the shipped PG
  stores, everything closes, and fresh stores read the same Goal chain and
  the immutable `goal_id`/`goal_revision` provenance back.

The PostgreSQL legs need `MAISTRO_TEST_DATABASE_URL` and skip without it
(deliberately, like the rest of `tests/migrations/`); CI's `postgres (pg17)`
and `postgres (pg18)` jobs own migrated servers, so both supported majors
exercise the upgrade walk. Verified locally against a live PostgreSQL: the
snapshot upgrades stamp `056`/`057`, the candidate forward upgrade stamps
`058` with user-model rows, the Run row, planner artifacts and Goal tables
all present, and the composition read-back green on the upgraded schema.
