---
inventory-delta:
  packages/maistro-core/tests: +7
  packages/hive-conductor/backend/tests: +2
---
# 989-pack-fixtures

Issue #989 (M7-A13) seeds two inspectable pack fixture Runs — `book` (accepted)
and `game` (parked) — through the canonical spine only
(`ProjectScopeStore` + `RunStore` create/transition APIs; no fixture JSON, no
frontend store). Seven new tests in
`packages/maistro-core/tests/graph/seeds/test_pack_fixtures.py` and two in
`packages/hive-conductor/backend/tests/test_pack_fixture_run_list.py` pin the
lineage a reviewer must be able to query without executing explore/judge:

- book: Goal/Rubric revisions plus the wave-1 → wave-2 redirect in
  `Run.provenance`, ≥2 wave-1 rejected theses each carrying an eval record,
  a wave-2 `BookPages` winner with per-spread `turn` notes, the planted
  earlier failure still queryable as the winner's failed Attempt 1, the
  refine Attempt 2 the accepted outcome names, and the accept fence.
- game: a scored thesis with a failing dimension (`taught_by_play`), the park
  fence (Run + fence NodeRun `WAITING`), and resume restoring the same
  identities — including after a SQLite reconnect, which also re-reads the
  accepted book lineage from disk.
- ontology: both fixtures resolve in one canonical Workspace/Project scope.
- anti-fixture-store: the seeders must take canonical stores (a frontend-only
  fixture cannot), and no frontend tree may carry fixture identity or copy, so
  a fixture that exists only as JSON/zustand/localStorage fails the suite.
- host open path: with the fixture Workspace visible through the workspace
  authority's canonical-membership import (#37), both fixture Runs list and
  open through `services.dag_run_inspection` — the door `GET /v1/dag-runs`
  answers through — a member sees them, a non-member cannot, and opening
  changes no canonical status.

No existing node IDs moved; the deltas are purely additive.
