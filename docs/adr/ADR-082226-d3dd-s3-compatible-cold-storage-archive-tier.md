---
id: ADR-082226-d3dd
title: "An Archive tier below durable memory, on any S3-compatible or local object store"
repo: maistro-engine
kind: adr
status: Superseded
created: 2026-08-22
substrate:
  - maistro-engine#ADR-082226-5104
implements: []
related: []
supersedes: []
superseded-by:
  - maistro-engine#ADR-082226-f436
blocks: []
blocked-by: []
contracts:
  - boundary
tests: []
layer: Memory
owners:
  - '@BlakeMatthews-dev'
---

> **Superseded by ADR-082226-f436**, which decided the same thing on the same
> day and is the one the code implements.
>
> `maistro.memory.archive` implemented this record and was never imported by
> anything — `container.py` wires `maistro.archive.wiring.build_archive_store`,
> and this tier sat in the reachability baseline from the day it was written. It
> has now been deleted.
>
> The one substantive difference is decision 4 here against f436's decision 5.
> This record keys an object `{kind}/{id}` and keeps the payload's SHA-256 on
> the stub row; f436 puts the digest *in* the key, under a scope prefix. f436's
> shape wins because it makes a read self-verifying without consulting the row
> that pointed at it.
>
> Decision 3's `list_keys` was the one capability this design had that f436's
> implementation lacked. It was ported as `list_scope` before the code here was
> removed, so nothing was lost with the deletion.

# ADR-082226-d3dd: An Archive tier below durable memory

## Context

`ADR-082226-5104` decision 8 gives three timescales:

| Timescale | Store | Horizon |
|---|---|---|
| Immediate | LLM context window | seconds |
| Working | Ladybug, per active Workspace | minutes |
| Long-term | PostgreSQL + pgvector | durable |

**"Durable" is doing too much work at the bottom.** Everything ever true stays in
the row store forever, at row-store cost, competing for the same buffer cache
and the same backup window as the working set. Decayed learnings, superseded
episodic memories, and completed Runs from two years ago with their Attempt
evidence are all *retained* and almost never *read*.

Decision 11 of that ADR already sends large artifacts to object storage. This
applies the same argument to **cold** records rather than **large** ones.

This is not a backup, and not a replacement for PostgreSQL as the system of
record. An archived record is still authoritative — it has moved to storage
priced for reading it rarely.

## Decision

### 1. A fourth tier, below long-term

| Timescale | Store | Horizon |
|---|---|---|
| Immediate | LLM context window | seconds |
| Working | Ladybug, per active Workspace | minutes |
| Long-term | PostgreSQL + pgvector | durable, read often |
| **Archive** | **object store (S3-compatible or local filesystem)** | **durable, read rarely** |

### 2. The row stays; the payload leaves

An archived record keeps its PostgreSQL row as a **stub**: primary key, the
columns any ordinary query must join or filter on, an `archived_at`, and the
archive key plus content digest. Only the payload columns are cleared.

This answers the ADR-shaped question in #133 directly, and it answers it the
conservative way: *a dangling `run_id` is worse than the storage it saves.*
Leaving entirely would break foreign keys, break `count(*)`, and make an
archived Run indistinguishable from one that never existed.

The engine already has this shape and it is worth naming, because consistency
here is what makes the behaviour predictable: `observability/replay.py`'s SECRET
tier keeps hash and metadata and drops the payload. Archive is the same move for
a different reason — there, the payload must not be kept; here, it need not be
kept *nearby*.

### 3. A read never returns emptiness

A read for an archived record either returns the rehydrated record or raises
`RecordArchivedError` carrying the key. It must never return `None`, an empty
list, or a stub with null payload fields that a caller could mistake for "no
such record".

This is the decision that makes the tier safe to turn on. Silent degradation is
what `graph_runner.StubLLMNotAllowedError` exists to prevent elsewhere in this
repository, and what #122 found in the store-selection path. An archive that can
answer "nothing here" for a record that exists would reintroduce it one layer
down, in the layer least likely to be looked at.

### 4. One object per record, content-addressed

Key shape `{kind}/{id}`; the payload's SHA-256 digest is stored on the stub row.

Batching by time window is cheaper to write and worse to read back one record —
and the write path is the one that is already cheap, since it is a background
sweep with no user waiting on it. The read path is the one a person is waiting
on when they ask what happened in a Run. Optimise the read.

The digest is not decoration. It makes "archive, read back, byte-identical" a
checkable property rather than an assertion, and it makes re-archiving
idempotent: the same payload writing the same key is a no-op rather than a
second object.

### 5. Archiving is downstream of dreaming, and shares its signal

Dreaming (decision 7 of ADR-082226-5104) decides what working memory *deserves
promotion* into durable memory. Archiving decides what durable memory has gone
*cold*. These point in opposite directions, and merging them would give one
process two jobs and let an archive sweep influence what gets consolidated.

So: strictly downstream, but **driven by the existing memory-decay weights
rather than a second sweeper** — the decay path already knows what has not been
reinforced. Archiving runs as an ordinary Run for the same reason dreaming does:
schedule/trigger → Run → Graph → NodeRuns → Attempts, inheriting events,
observability, retries, provenance and checkpoints instead of adding an eighth
lifecycle.

### 6. Off by default, and no cloud SDK in the base install

No archive store configured means the engine behaves exactly as it does today —
not "archives to a default location", not "warns on every write".

The S3 implementation lives behind a `maistro-core[s3]` extra and is imported
lazily. `maistro-core` must import cleanly with the extra absent, proven by a
test rather than assumed: the homelab deployment gets `FilesystemArchiveStore`
and never installs an AWS SDK.

### 7. S3-compatible, not AWS

`endpoint_url` is configurable, so MinIO, Cloudflare R2, Backblaze B2 and
anything else speaking the protocol work. The CI exercise runs against a local
MinIO rather than mocking the client away — a mocked object store proves the
call was made with the arguments the test already knew.

Credentials come from the secret path (SPEC-011), never the application database
and never inline config.

## Consequences

### Positive

- The bottom of the hierarchy stops being a single undifferentiated "forever".
  Backup windows and buffer cache stop paying for records nobody reads.
- Retention becomes a policy with a knob rather than a property of having never
  deleted anything.
- The stub row means archiving is invisible to every query that only needs
  identity, and loud to every query that needs the payload — which is the split
  that makes it safe to enable on a live deployment.

### Negative / Trade-offs

- **A second store is a second thing that can be down.** A read for an archived
  record now depends on the object store being reachable, and the error is a
  new failure mode for callers that previously only had "found" and "not found".
  This is the real cost, and it is the reason for decision 3: at minimum the
  failure is legible.
- **One object per record costs more per byte for small records.** A 200-byte
  learning in its own S3 object is dominated by request overhead. Accepted:
  eligibility is by decay weight and age, so the population that reaches archive
  is the one where the retention horizon matters more than the per-object cost.
  If measurement later contradicts this, batching is a change to the key
  strategy, not to the protocol.
- **Rehydration latency is not the row store's.** A cold read is tens to
  hundreds of milliseconds, not sub-millisecond. Anything on a hot path must not
  be archive-eligible, which is a constraint on the policy, not on the caller.

### Neutral

- The `ArchiveStore` protocol is a boundary contract, so a third implementation
  (a tape gateway, a different cloud) is a new class rather than a change here.
- This says nothing about *deleting* archived records. Deletion is a retention
  decision with legal and provenance dimensions and belongs in its own record.
