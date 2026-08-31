---
id: ADR-083026-4b70
title: "memory_entries.embedding is repaired to vector(1536); a column's declared type is asserted, not assumed"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-30
accepted: 2026-08-30
history:
  - status: Proposed
    date: 2026-08-30
  - status: Accepted
    date: 2026-08-30
substrate:
  - maistro-engine#ADR-082226-5104
  - maistro-engine#ADR-082326-8194
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests:
  - tests/migrations/test_memory_entries_embedding_type.py
layer: Memory
owners:
  - '@BlakeMatthews-dev'
---

# ADR-083026-4b70: memory_entries.embedding is repaired to vector(1536); a column's declared type is asserted, not assumed

## Context

`memory_entries.embedding` has been `text` in every deployment since migration
`001`, while every artefact that describes it says `vector(1536)`.

`001` creates the column twice, and the first spelling wins:

```python
sa.Column("embedding", sa.Text, nullable=True),  # vector(1536) — managed by pgvector
...
op.execute("ALTER TABLE memory_entries ADD COLUMN IF NOT EXISTS embedding vector(1536)")
```

`create_table` makes `embedding text`. The `ALTER` that would have made it a
vector is guarded by `IF NOT EXISTS`, and a column of that name now exists, so
PostgreSQL skips it without error or notice. The inline comment claiming the
column is "managed by pgvector" describes an intent that the next line failed to
carry out.

Verified against a migrated PostgreSQL 18 + pgvector database at `develop`
`fdb6bcb`:

```
learnings.embedding       => vector(1536)
memory_entries.embedding  => text
```

`learnings` is right because migration `011` does it in the correct order —
`CREATE EXTENSION`, then `ADD COLUMN IF NOT EXISTS ... vector(N)` on a table
that has no such column, then the HNSW index. `001` is the only place the
mistake is made, and it is the oldest.

**Three things assert the type that is not there.** The ORM model in
`memory/store.py` declares `embedding: Mapped[list[float] | None] =
mapped_column(Vector(1536))` whenever the `pgvector` package imports, so
SQLAlchemy and the database disagree about the column it is reading and
writing. `memory/vectors.py` documents `EMBEDDING_DIMENSIONS` as the width
created "by `alembic/versions/007_memory_embedding_columns.py` and, for
`memory_entries`, by 001 before it" — a file name that does not exist (it is
`011`) and a claim about `001` that is false. And `011`'s own downgrade note
reasons about leaving the extension in place because "`memory_entries.embedding`
from 001 still" needs it.

The defect survived because every check that could have caught it asked whether
a column named `embedding` exists. It does. Nothing asked what type it is.

## Decision

**`memory_entries.embedding` becomes `vector(1536)`, by a forward migration.**
`001` is applied history and its DDL is not rewritten; the repair is `029`,
which is where a schema fix belongs once the broken revision has run anywhere.

**Existing text values are converted, and anything unconvertible is preserved,
not discarded.** The migration casts the values that parse at the declared
width and moves the rest to `embedding_unconvertible text` rather than failing
the upgrade or dropping them. A vector that cannot be read is still evidence of
what a deployment was doing; an upgrade that aborts on one malformed row leaves
the operator with a half-migrated database and no way forward that does not
involve hand-editing rows.

**The width is 1536, and this ADR does not reopen it.** ADR-082326-8194 decided
that number and is `Accepted`. Repairing a column to the width every other
artefact already claims is not the moment to relitigate it — and a repair that
changed the width at the same time would make it impossible to tell, later,
which of the two changes broke something.

**The HNSW cosine index follows, matching `011` exactly.** Same operator class
(`vector_cosine_ops`), same naming (`ix_memory_entries_embedding_hnsw`). A
second index strategy for the same access pattern in the same database is the
per-table lookup ADR-082326-8194 argued against.

**Type is asserted, not presence.** The tests read the column's actual type from
`information_schema`/`pg_catalog` and fail on `text`. This is the rule the
defect is an argument for: a schema test that checks a column exists proves the
migration ran, not that it did what it said.

**The false statements are corrected where they stand.** `001`'s comment now
records what that revision actually produced and points at this repair;
`vectors.py` names the right file and stops claiming `001` created a vector.
Editing a comment in applied history changes no behaviour, and leaving a comment
that contradicts the database is how this lasted as long as it did.

## Consequences

### Positive

- The ORM's `Vector(1536)` mapping and the database agree, so a write through
  `MemoryEntry` reaches a column that can hold it.
- Scoped similarity over `memory_entries` becomes possible in one query, which
  is what ADR-082226-5104 chose pgvector for.
- A whole class of migration bug — `create_table` with a placeholder type
  followed by a guarded `ALTER` that silently no-ops — now has a test shape that
  catches it, rather than a comment asserting it did not happen.

### Negative / Trade-offs

- `ALTER COLUMN ... TYPE` rewrites the table and takes an `ACCESS EXCLUSIVE`
  lock. On a large `memory_entries` this is downtime. Accepted because the
  column is empty in every deployment we can observe (nothing writes it: the
  ORM mapping is the only reference, and it has no caller that sets the field),
  and because the alternative — a new column plus a dual-write window — is a
  large amount of machinery for a table whose contents are, as far as the
  repository shows, nothing.
- `embedding_unconvertible` is a column that will be empty and stay empty in
  every deployment that never wrote a vector. That is the cost of not throwing
  away data on the deployments we cannot observe, and it is cheap: a nullable
  text column with no index.
- The repair is `029` and therefore lands after `028`. If the two are in flight
  at once, the ladder must be renumbered before merge, not on queue position —
  two revisions sharing an id is two alembic heads, and GitHub reports that as
  `mergeable_state: clean`.

### Neutral

- No change to `learnings`, `outcomes` or `episodic_memories`. `011` got
  `learnings` right, and the other two are still waiting on the producers that
  #188 says must land with them.
- No change to `EMBEDDING_DIMENSIONS` or to `require_matching_dimension`.
