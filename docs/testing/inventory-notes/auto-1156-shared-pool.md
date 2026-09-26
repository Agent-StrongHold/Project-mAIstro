---
inventory-delta:
  packages/maistro-core/tests: +3
---
# auto-1156 shared-pool widening repair

Merging develop surfaced a real regression from this branch's scope
alignment: the exact-match agent predicate dropped the
`(agent_id = ? OR agent_id = '')` widening both SQL twins shipped, so an
agent-scoped read no longer saw the org-wide shared pool —
`tests/migrations` failed on `test_an_agent_scoped_read_still_sees_shared_rows`.
The shared predicate (`persistence/learning_scope.py`) and
`similarity_query` now carry one rule across all three backends: `agent_id = ''`
is the org-shared pool an agent-scoped read still sees; `team_id`/`user_id`
stay exact identity axes (empty there means "not recorded", which must not
republish unknown-provenance rows). One parametrized conformance case
(memory, SQLite, PostgreSQL) pins the widening so the backends cannot drift
apart again; the PostgreSQL query-shape test pins the restored clause.
