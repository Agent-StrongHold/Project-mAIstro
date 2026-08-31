---
inventory-delta:
  packages/maistro-core/tests: +71
---
# claude-issue-710-durable-episodic-memory-5de4

All 71 are new, and none of them replaces anything: `episodic_memories` had no
store, so there were no episodic persistence tests to remove (#710).

- **`tests/memory/test_scope_predicate.py` (+15).** The scope rule compiled to
  SQL, driven against the Python rule over one corpus of thirteen memories and
  eight callers. Twelve of the fifteen are the parametrized agreement cases and
  the two cross-org clauses; three are about the predicate being parameterised,
  including one that pins the *order* the numeric markers are drawn in, because
  a mis-stepped marker binds the org id to the team clause and SQLite — where
  every marker is `?` — cannot see it.
- **`tests/persistence/test_episodic_store_conformance.py` (+49, of which 20 are
  the two-backend parametrization).** Durability across a reopened SQLite file
  and a second asyncpg pool, the four fields migration 025 adds, the `EXPLAIN`
  that shows the scope filter is the server's work, the decay sweep counted
  against `InMemoryEpisodicStore`'s own sweep rather than against numbers
  written into the test, and the three stores agreeing on retrieve, list and
  reinforce. Three of the thirty-four are not about a store at all: they
  assert the two literal upsert statements still name every column in
  `COLUMNS`, in order, with a matching placeholder count. The statements are
  literal because Bandit's B608 flags SQL built by string formatting and this
  repo runs it at a strict zero baseline; the drift the assembled version
  made impossible is what these three buy back.
- **`tests/test_container_episodic_store.py` (+4).** Which store each URL
  selects, and one that writes through the wired SQLite store — a type
  assertion alone would pass for a store wired against a database with no table
  in it.
- **`tests/memory/test_episodic_lifetime_is_stated.py` (+3).** The two
  persistence claims: that the in-memory store says what its lifetime is, and
  that no migration asserts `maistro.memory` reads a table it does not. The
  third asserts the scan has a corpus, because a guard that reads no files
  guards nothing.

**Round two (+15), answering the Codex review — every finding verified against
the code first, and each test mutation-checked against the fix it covers:**

- Two memories stored with no id are two memories, and the store returns the id
  it filed one under. `EpisodicMemory.memory_id` defaulted to `""` and
  `TuringMemoryBridge.store_episode` supplies none, so `ON CONFLICT (memory_id)`
  made each episode overwrite the last.
- Two workers reinforcing one memory lose neither event. Reverting the
  `FOR UPDATE` reproduces the lost update exactly: `reinforcement_count` comes
  back 1 instead of 2.
- Equal weights order the same in all three stores, and a `limit` through a tie
  keeps the same memories. Every new memory defaults to 0.3, so this is the
  common case, not the corner.
- `reinforce` with no delta moves the weight by `REINFORCE_DELTA` — ADR-013
  requires stores to import the constant rather than re-spell `0.05`.
- The context round-trips with its value types intact and equal to the
  in-memory store's, on a pool *without* the JSON codecs and on one *with*
  them. Both halves are needed and neither alone is sufficient: uncast text is
  correct on a raw pool and double-encoded on a codec pool, where the column
  ends up holding a JSON string. The assertion is `jsonb_typeof`, because a
  tolerant reader parses the double-encoded value back into the right mapping
  and hides the wrong column.
