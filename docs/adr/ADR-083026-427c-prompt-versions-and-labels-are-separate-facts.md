---
id: ADR-083026-427c
title: "A prompt version and a prompt label are separate facts, written in one transaction"
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
  - maistro-engine#ADR-081226-9944
implements: []
related:
  - maistro-engine#ADR-019
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/persistence/test_prompt_store_conformance.py
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# ADR-083026-427c: A prompt version and a prompt label are separate facts, written in one transaction

## Context

`prompts` stores a prompt version and the label pointing at it in **one row**.
`label` is a nullable column, unique per name where not null, and the version
is half of the primary key. Two facts of different arity share a row: a version
has exactly one identity, a label has exactly one target, and a version may
legitimately be the target of *several* labels.

That last case is not hypothetical — it is the first write of every new prompt.
`upsert` labels version 1 `latest` and then wants it to be `production` too.
With one row per version it cannot, so the code writes a **second row at the
same version**:

```sql
INSERT INTO prompts (name, version, label, content, config)
  VALUES ($1, $2, 'production', $3, $4::jsonb)
  ON CONFLICT (name, label) DO UPDATE SET ...
```

On PostgreSQL that statement cannot run at all. Verified against 18.6:

```
ERROR:  there is no unique or exclusion constraint matching the ON CONFLICT specification
```

`ix_prompts_name_label` is a **partial** index (`WHERE label IS NOT NULL`), and
a partial index is only inferable as an arbiter when the statement repeats its
predicate. Supplying it gets one step further and then hits the real wall:

```
ERROR:  duplicate key value violates unique constraint "prompts_pkey"
DETAIL:  Key (name, version)=(greet, 1) already exists.
```

So on PostgreSQL, creating the first version of any prompt under a label other
than `production` raises. Not sometimes, and not under load — always. The SQLite
twin does the same thing and succeeds, because its table declares no key over
`(name, version)`: it stores the duplicate row happily. **The two backends
disagree about what the data even is**, and the disagreement was invisible
because the PostgreSQL manager's tests drive a fake connection that enforces no
constraints.

Behind that sits the concurrency defect this record was opened for (#328).
`upsert` reads `MAX(version) + 1`, clears labels, and inserts — three
statements, no transaction, no lock, on a pooled connection. Two writers can
allocate the same version, clear each other's labels, or leave `production`
pointing at a version that was never committed.

Fixing the races inside the current shape is not possible: no locking discipline
makes a schema admit a fact it has no room for.

## Decision

**A version is a row in `prompts`. A label is a row in `prompt_labels`.**

```
prompts        (name, version)  PK   content, config
prompt_labels  (name, label)    PK   version → FK (name, version) ON DELETE CASCADE
```

Each key states one of the two properties #328 asks the database to enforce:
`prompts`' key makes a version unique for a name; `prompt_labels`' key makes a
label point at exactly one version. Neither is a partial index, so both are
usable as `ON CONFLICT` arbiters, and a version may carry any number of labels
without a second copy of its content existing anywhere.

**One transaction, one lock, per prompt name.** `upsert` runs inside
`BEGIN`, taking `pg_advisory_xact_lock` keyed on the prompt name before reading
`MAX(version)`. Concurrent writers to the same name serialize; writers to
different names do not contend. The lock is transaction-scoped, so it is
released by commit or rollback — there is no path that holds it after a failure.

`SERIALIZABLE` was the alternative. Rejected: it pushes a retry loop into every
caller for a contention pattern the advisory lock resolves deterministically,
and #328 asks for *either* deterministic serialization or an explicit conflict.
Deterministic is the better answer where it is available.

**A label moves or it does not; it is never cleared alone.** The old code
`UPDATE ... SET label = NULL` and then inserted, so a failure between the two
left the label pointing nowhere. Promotion is now a single upsert against
`prompt_labels` — the label's target changes in one statement, inside the
transaction that wrote the version it points to.

**A retry is not a new version.** Writing content and config byte-identical to
the name's current head re-points the labels at that head and creates nothing.
A client that times out and retries therefore does not double the version
history, and the operation is idempotent as #328 requires. Different content is
a different version, which is the point of a version.

**The SQLite twin takes the same schema**, and gets the same properties from
`BEGIN IMMEDIATE` — its writer lock is the whole database, which is exactly
right for the single-instance deployment it serves.

## Consequences

### Positive
- First-version creation works on PostgreSQL, where it raised unconditionally.
- The two backends store the same shape, so the conformance suite can compare
  them rather than each agreeing with its own store.
- Both properties #328 asks for are database constraints, not code discipline:
  they hold against any writer, including one that does not go through this class.
- A version's content exists once. Under the old shape a labelled version was
  stored twice, and nothing kept the copies equal.

### Negative / Trade-offs
- A migration that must carry existing rows across, and the reading paths gain a
  join. The join is on two primary keys and returns one row.
- An advisory lock is a repository-wide namespace: the key derivation has to be
  stated so a second user of `pg_advisory_xact_lock` cannot collide by accident.
- Idempotent retry means an author who re-saves identical content gets no new
  version. That is the intent, and it is a behaviour change from "every call
  makes a version".

### Neutral
- `PromptManager` is unchanged. No caller learns that labels moved tables.
