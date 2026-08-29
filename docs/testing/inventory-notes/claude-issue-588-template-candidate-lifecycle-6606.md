---
inventory-delta:
  packages/maistro-core/tests: +39
---
# claude-issue-588-template-candidate-lifecycle

Thirteen added tests, no removals, nothing renamed or moved. Thirty-nine
node IDs because they land in `tests/graph/test_node_template_store.py`,
whose `backend` fixture is parametrised over memory, SQLite and
PostgreSQL — so each test is three.

They are there rather than in a new file precisely for that: the candidate
lifecycle is a store contract, and this suite is where "the durable stores
behave like the reference" stays a comparison rather than a claim. A new
database-free file would have been one node ID per test and proved a third
as much.

Six for the lifecycle itself:

- `test_an_improvement_produces_a_candidate_and_leaves_the_published_version_alone`
  carries the AC-11 marker
- `test_promotion_does_not_change_the_content_hash` holds
  ADR-082926-65bf's hash exclusion
- three on the audit discipline, one on the deliberate absence of a
  fallback when every version is a candidate

Seven more after Codex's review of the first version, one per finding, so
none can regress silently:

- re-registering a candidate does not activate it, and re-registering an
  active version does not demote it — the hash excludes `lifecycle`, so an
  idempotent `put` was writing it through
- a promotion is not observable until its commit is recorded (asserted
  from a reader's side, mid-audit)
- a cancelled promotion is rolled back (`CancelledError` is not an
  `Exception`)
- execution refuses a candidate even when its version is named
- a candidate-only template is not reported as unregistered
- an approval must name an approver and a reason
