---
inventory-delta:
  packages/maistro-core/tests: +68
---
# claude-issue-588-template-candidate-lifecycle

No removals, nothing renamed or moved. The count is large because these
land in the three parametrised store suites -- memory, SQLite and
PostgreSQL -- so most tests are three node IDs.

**`test_node_template_store.py`**, thirteen tests. Six for the lifecycle
itself (the AC-11 marker, the hash exclusion, three on the audit
discipline, one on the deliberate absence of a fallback) and seven added
after Codex's review, one per finding: re-registration does not activate
or demote, a promotion is not observable until its commit is recorded, a
cancelled promotion is rolled back, execution refuses a named candidate,
a candidate-only template is not reported as unregistered, and an
approval must name an approver and a reason.

**`test_template_store.py`**, nine tests -- the GraphTemplate half of the
same lifecycle. It had none. The lifecycle was implemented on both
families and proved on one, which is how four code paths reached a PR
untested, including the `put` guard Codex found could silently activate a
candidate. The diff-coverage gate is what surfaced it; the tests are what
close it.

**`test_template_adapter.py`**, two tests, on the branch that exists
because `**identity` was removed to fix the pyright ratchet: a snapshot
with no `id` still projects and takes a generated identity, and one with
no `name` falls back to its id.

Changed-line coverage on the three source files this touches:
`graph/templates.py` and `graph/sqlite_templates.py` at 100%,
`graph/template_adapter.py` at 98%. `graph/pg_templates.py` measures 0%
without a database and is covered by CI's PostgreSQL leg.
