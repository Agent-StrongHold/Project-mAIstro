---
inventory-delta:
  packages/hive-conductor/backend/tests: +11
  packages/maistro-design/tests: +24
  tests/: +6
---
# claude-issue-326-design-project-scope-175e

All three deltas are new tests; nothing was deleted or moved. Two existing
cases in `packages/maistro-design/tests/test_stores.py` changed in place — they
pass `org_id` to `delete` and to `update`, and give the update double a
`rowcount` — so they do not move the count.

**`packages/maistro-design/tests/test_project_scope.py`, +24** — the store and
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

**`tests/migrations/test_migration_chain.py`, +6** — the half that needs a real
server, since a `CHECK` is only a claim until one enforces it. The scope the
product supplies being writable, a scope-less project refused, no table left
standing whose only purpose was to be referenced, and the down-and-up round
trip with a row present.

## The Codex review and the first CI round, +14 more

Three findings, all real, and one of them a genuine authorization hole.

- **`update` took its scope off the payload.** `WHERE id = :id AND org_id =
  :org_id` sounds like a check, but both values came from the same
  `DesignProject` the caller supplies — so a caller who knows a victim's
  project id *and* org id satisfied it. `update` takes the caller's `org_id`
  as a separate keyword argument now, like `get` and `delete` already did, and
  refuses a payload that names a different scope rather than silently
  rescoping the row. Four new cases in `test_project_scope.py`, and `update`
  joins `BY_ID` in the signature test so the rule holds for it too.
- **A present-but-blank request scope defaulted.** `or CONDUCTOR_ORG_ID`
  treated `org_id = ""` like a missing attribute, so middleware setting it to
  mean "unresolved" was handed the deployment's own scope. Absent and empty
  are distinguishable now; empty is a 403.
- **An empty `team_id` aborted the rollback.** `team_id` is nullable and
  unchecked, so `''` and `NULL` both meant "no team" — and the downgrade has
  to give every non-null `team_id` an anchor row before restoring the foreign
  key, which `''` cannot have. 024 normalizes it to `NULL` on the way up and
  again before the backfill on the way down. Two migration cases.

**`packages/hive-conductor/backend/tests/test_design_scope.py`, +11 — new
file.** The diff-coverage gate reported `routes/design.py` at 37.5% of its
changed lines, which was the honest reading: nothing in the suite ran those
handlers at all. It drives all four, with the store, engine and preview
service replaced.

**Writing them found a fourth defect, mine.** Each route ends in a blanket
`except Exception` that returns 500, and I had put `_get_org_id` *inside* the
`try` — so the new 403 came back as `"Generation failed: 403: No design scope
resolved"`. That is a 500 for an authorization decision, and it is the exact
hazard `_require_ready`'s own docstring documents (#413). The scope now
resolves before the `try` in all four routes.

## Mutations run

Sixteen, all killed.

The review round added four: `update` taking the scope off the payload again;
`update` no longer comparing the two scopes; the protocol dropping `update`'s
scope argument (2 fail); and the route defaulting a blank request scope.

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
