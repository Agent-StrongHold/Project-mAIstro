---
inventory-delta:
  packages/maistro-core/tests: +53
---
# claude-issue-710-durable-episodic-memory-5de4

All 53 are new, and none of them replaces anything: `episodic_memories` had no
store, so there were no episodic persistence tests to remove (#710).

- **`tests/memory/test_scope_predicate.py` (+15).** The scope rule compiled to
  SQL, driven against the Python rule over one corpus of thirteen memories and
  eight callers. Twelve of the fifteen are the parametrized agreement cases and
  the two cross-org clauses; three are about the predicate being parameterised,
  including one that pins the *order* the numeric markers are drawn in, because
  a mis-stepped marker binds the org id to the team clause and SQLite — where
  every marker is `?` — cannot see it.
- **`tests/persistence/test_episodic_store_conformance.py` (+31, of which 14 are
  the two-backend parametrization).** Durability across a reopened SQLite file
  and a second asyncpg pool, the four fields migration 025 adds, the `EXPLAIN`
  that shows the scope filter is the server's work, the decay sweep counted
  against `InMemoryEpisodicStore`'s own sweep rather than against numbers
  written into the test, and the three stores agreeing on retrieve, list and
  reinforce.
- **`tests/test_container_episodic_store.py` (+4).** Which store each URL
  selects, and one that writes through the wired SQLite store — a type
  assertion alone would pass for a store wired against a database with no table
  in it.
- **`tests/memory/test_episodic_lifetime_is_stated.py` (+3).** The two
  persistence claims: that the in-memory store says what its lifetime is, and
  that no migration asserts `maistro.memory` reads a table it does not. The
  third asserts the scan has a corpus, because a guard that reads no files
  guards nothing.
