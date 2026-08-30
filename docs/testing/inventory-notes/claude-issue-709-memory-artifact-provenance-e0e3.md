---
inventory-delta:
  packages/maistro-core/tests: +36
  packages/maistro-design/tests: +7
---
# claude-issue-709-memory-artifact-provenance-e0e3

All 43 are new; nothing was removed or merged, so the delta is the addition.
Two existing tests changed in place rather than being added to: both pin the
exact argument tuple an INSERT binds, and both gained three `None`s for the new
producer columns — `test_pg_learnings.py` and `test_pg_outcomes.py`. Those are
edits, not additions, which is why the count is 35 and not 37.

**`packages/maistro-core/tests/persistence/test_record_provenance.py` (+31, new).**
Four cases for the resolution rule itself — the caller's answer beating the
ambient one, the context filling blanks, a record made outside any execution
naming none. Eighteen for learnings, parametrized over in-memory, SQLite and
PostgreSQL, because a twin that silently drops what PostgreSQL persists passes
every test written against the twin alone (#696 found three such drops in one
store). Four for outcomes across SQLite and PostgreSQL, reading the three
columns straight out of the row rather than through a mapper: a mapper that
dropped them would agree with a write that dropped them. One for the outcome
round trip through `_row_to_outcome`, which is the only place a mapper *can*
drop what the writer stored. Two for SQLite files created before the columns
existed — learnings and outcomes separately, because they are separate code
paths and a test of one says nothing about the other — each keeping its rows
through the in-place upgrade. Two for the wrapping stores, which is what the
container actually builds when embeddings are configured: a delegation that
silently returned nothing would make `produced_by` answer "no learnings" on
the deployments that have the most. The last three were added because the
diff-coverage gate named their lines, which is the gate doing its job: two
delegating methods and one `ALTER TABLE` branch had no test at all.

**`packages/maistro-design/tests/test_output_provenance.py` (+7, new).** Four
drive `PgDesignProjectStore.create` against a session double and read the
parameters it binds, including the per-output case: outputs of one project can
come from different Attempts, so a refinement pass must not inherit the first
Attempt's id. Three cover `_coerce_design_output`, including a row from a
database migrated before 025, which has no such keys at all.

**Round two (+5), answering the Codex review — both findings verified against
the code first, both fixes mutation-checked:**

- `TestTheVolatileBackendFillsItToo` (+3). `InMemoryOutcomeStore.record`
  assigned an id and appended, and resolved no ambient provenance — while both
  SQL twins did. `memory://` is the default backend in dev and test, so the gap
  was in the one implementation every behavioural test runs against.
- `TestDedupMovesTheProducerWithTheContent` (+2). The learning store's dedup
  branch replaced `learning` and `trigger_keys` on the surviving row and left
  the earlier Run's ids on it, so `produced_by` attributed the new text to the
  Run that no longer wrote it and returned nothing for the Run that did.
