---
inventory-delta:
  packages/maistro-design/tests: +19
  tests/: +4
---
# claude-issue-326-design-project-scope-175e

Both deltas are new tests; nothing was deleted or moved. Two existing cases in
`packages/maistro-design/tests/test_stores.py` changed in place (they now pass
`org_id` to `delete` and give the update double a `rowcount`), so they do not
move the count.

**`packages/maistro-design/tests/test_project_scope.py`, +19** — the store and
route half of SPEC-083026-6bc5:

- AC-2, 6 cases: `create`, `update` and the four scoped reads each refusing a
  blank scope, and doing so before touching the session.
- AC-3, 2: `get` matching on the scope as well as the id, and answering
  absence rather than a refusal.
- AC-4, 4: an update that matched nothing raising, and the scope reaching the
  `WHERE` clause of update, delete and the insert.
- AC-5, 5: read from the protocol and implementation *signatures*, so a fourth
  by-id method added later is held to the rule a test naming today's three
  would not catch; plus an AST scan asserting no statement in the store selects
  `design_projects` by id without naming `org_id`.
- AC-6, 2: the Conductor route parsed as a file, because `maistro-design` does
  not depend on `hive-conductor` and must not start to.

**`tests/migrations/test_migration_chain.py`, +4** — the half that needs a real
server, since a `CHECK` is only a claim until one enforces it. The scope the
product supplies being writable, a scope-less project refused, no table left
standing whose only purpose was to be referenced, and the down-and-up round
trip with a row present.

## Mutations run

Twelve, all killed.

Store and route (8): `get` dropping the scope from its `WHERE`; `update`
dropping the `rowcount` check; `update` dropping the scope; `create` accepting
a scope-less project; `delete` dropping the scope; the protocol giving `org_id`
a default; the route no longer passing the scope; the route going back to the
inline literal.

Migration (4): the org foreign key not dropped (8 of 9 fail); the `CHECK` not
added (2); the placeholder tables left standing (3); the downgrade skipping the
`orgs` backfill (4).

The last one left the scratch database mid-downgrade, so the restored run also
showed four failures until the database was recreated — the mutation, not the
code. Re-verified from a fresh database: 9 passed.
