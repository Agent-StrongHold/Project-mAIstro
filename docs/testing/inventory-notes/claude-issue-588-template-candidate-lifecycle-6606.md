---
inventory-delta:
  packages/maistro-core/tests: +18
---
# claude-issue-588-template-candidate-lifecycle

Six added tests, no removals, nothing renamed or moved. Eighteen node IDs
because they land in `tests/graph/test_node_template_store.py`, whose
`backend` fixture is parametrised over memory, SQLite and PostgreSQL — so
each test is three.

They are there rather than in a new file precisely for that: the candidate
lifecycle is a store contract, and the whole point of putting it in this
suite is that "the durable stores behave like the reference" stays a
comparison rather than a claim. A new database-free file would have been
one node ID per test and proved a third as much.

- `test_an_improvement_produces_a_candidate_and_leaves_the_published_version_alone`
  carries the AC-11 marker
- `test_promotion_does_not_change_the_content_hash` holds ADR-082926-65bf's
  hash exclusion
- three tests on the audit discipline (`..._commit_cannot_be_recorded_is_undone`,
  `..._sink_that_is_down_blocks_the_promotion_entirely`,
  `..._version_that_does_not_exist_says_so`)
- `test_a_template_whose_every_version_is_a_candidate_resolves_to_nothing`
  pins the deliberate absence of a fallback

No existing test changed, on any backend.
