---
id: ADR-082226-f436
title: "Object storage is an archive tier below durable memory, not a backup"
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-08-22
substrate:
  - maistro-engine#ADR-082226-5104
implements: []
related:
  - maistro-engine#ADR-019
  - maistro-engine#ADR-087
supersedes:
  - maistro-engine#ADR-082226-d3dd
blocks: []
blocked-by: []
contracts:
  - boundary
tests: []
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

> **Supersedes ADR-082226-d3dd.**
>
> Both records decided the same thing — an archive tier below durable memory,
> on any S3-compatible or local object store, not a backup — and both were
> implemented. `maistro.archive` implemented this one; `maistro.memory.archive`
> implemented d3dd.
>
> The code chose before the records did: `container.py` wires
> `maistro.archive.wiring.build_archive_store`, and nothing ever imported
> `maistro.memory.archive`. It sat in the reachability baseline from the day it
> was written.
>
> The designs differ in one substantive place, and it is decision 5. This record
> keys an object by a content hash under a scope prefix; d3dd keys it
> `{kind}/{id}` and keeps the digest on the stub row instead. Putting the digest
> *in* the key is the better of the two, because it makes a read self-verifying
> without a second lookup — which is what keeps an archived record authoritative
> rather than merely stored.
>
> `list_keys`, the one capability d3dd's implementation had and this one's did
> not, moved across as `list_scope` before that implementation was deleted.
> Scope at a time rather than a free prefix, because half of a content-addressed
> key is a hash and a prefix reaching into it selects an arbitrary bucket.

# ADR-082226-f436: Object storage is an archive tier below durable memory, not a backup

## Context

ADR-082226-5104 gives the memory hierarchy three timescales:

| Timescale | Store | Horizon |
|---|---|---|
| Immediate | LLM context window | seconds — current inference |
| Working | Ladybug, per active Workspace | minutes — the active working period |
| Long-term | PostgreSQL + pgvector | durable |

"Durable" is doing too much work at the bottom. Everything ever true stays in the row store
forever, at row-store cost: competing for the same buffer cache, the same index maintenance, the
same backup window and the same restore time as the working set. Decayed learnings, superseded
episodic memories, completed Runs from two years ago and the Attempt evidence under them are all
*retained* and almost never *read*.

That is not a hypothetical. ADR-082226-5104 decision 5 makes memory decay a first-class behaviour
and decision 7 makes consolidation an ordinary Run — both of which produce records that must be
kept and will not be looked at again for months. `maistro.memory` already has weight floors "for
wisdom/regrets", which is precisely a statement that some records must outlive their usefulness.

Decision 11 of the same ADR already sends **large artifacts** to object storage. This applies the
same argument to **cold** records rather than large ones, and the two compose: an archived record
that happens to be large is one object either way.

The alternative that must be named and rejected: doing nothing and letting the row store grow.
That is survivable for a long time and then stops being survivable suddenly, during a restore,
which is the worst moment to discover it.

## Decision

### 1. A fourth tier, and it is still authoritative

| Timescale | Store | Horizon |
|---|---|---|
| Immediate | LLM context window | seconds |
| Working | Ladybug, per active Workspace | minutes |
| Long-term | PostgreSQL + pgvector | durable, hot |
| **Archive** | **object storage (S3-compatible) or a local directory** | **durable, cold** |

An archived record is **not a backup and not a deletion**. It is the same authoritative record,
moved to storage priced for reading it rarely. A backup is a copy you hope never to read; an
archive is the original, in a slower place. Conflating the two is how an archive quietly becomes a
place records go to be lost.

### 2. The row stays; the payload moves

Archiving leaves a **tombstone row** in PostgreSQL carrying the record's identity, its scope
columns, and the archive key. Only the payload leaves.

This is the whole reason the tier is safe. Referential integrity holds — a `run_id` that something
still points at is still a row. Ordinary scope-filtered queries still see the record exists.
Nothing has to learn that a foreign key might dangle. The cost is that the row count does not
shrink; the benefit is that the bytes, the TOAST pressure and the backup size do, which is what
actually hurt.

A record whose *identity* nothing needs either is not archived — it is deleted, by whatever policy
governs deletion. Archiving is not a way to avoid deciding that.

### 3. Two implementations behind one protocol

`ArchiveStore` is a protocol with put/get/exists/delete over an opaque key. Two implementations
ship:

- **`S3ArchiveStore`** — S3-compatible, with `endpoint_url` configurable. Not an AWS assumption:
  MinIO, Cloudflare R2, Backblaze B2, Ceph and Wasabi are all first-class. Hard-coding AWS would
  make the homelab deployment buy a cloud account to use its own NAS.
- **`FilesystemArchiveStore`** — a local directory. This is the homelab default and the test
  default, and it exists so that "archiving" is not synonymous with "has cloud credentials".

The protocol is deliberately narrow — no listing by prefix, no server-side copy, no lifecycle
rules. Everything the engine needs is get-by-key, and a wider interface would be a wider surface
to reimplement for each backend.

### 4. Optional dependency, absent by default

No cloud SDK is in `maistro-core`'s base install. The S3 implementation lives behind a `[s3]`
extra and is imported lazily, inside the constructor. A deployment that does not archive to S3
does not pay for the import, and a deployment that does not archive at all is byte-for-byte the
system it is today.

This is a hard rule, not a preference: `maistro-core` is a library other products import
(ADR-019), and a transitive `boto3` is a large, opinionated dependency to inflict on a consumer
that wanted a router.

### 5. One object per record, content-addressed

Object layout is one object per archived record, keyed by a content hash under a scope prefix.

Batching by time window is cheaper to write and worse to read one record back, and the read
pattern here is by construction *rare, and one record at a time* — that is what makes a record
cold in the first place. Optimising archive writes at the cost of archive reads optimises the
operation that is already not the bottleneck.

Content addressing means re-archiving an unchanged record is a no-op and a corrupted read is
detectable.

### 6. Reading an archived record is explicit, never an empty result

A read for an archived record returns it, or says it is archived. It never returns "no such
record". A silent empty result for a record that exists is indistinguishable from deletion by
every caller, and would turn a cost optimisation into data loss at the API boundary.

Whether reads are transparent (read-through, caller unaware) or explicit (caller asks to
rehydrate) is per call site: memory retrieval reads through, because a decayed learning surfacing
in a search is exactly the point; bulk analytics does not, because rehydrating a million rows to
count them is worse than not answering.

The same rule binds the *store*, not only the caller, and it is sharper there than it first
looks. `head_object` answers a bare `404` with no error code, and answers the same 404 whether
the key is absent from a healthy bucket or the bucket does not exist — the two responses are
identical apart from the request id. So an `exists()` that trusted the 404 would report every
archived record absent whenever the bucket name is wrong, the bucket is deleted, or the
credential loses access: an outage indistinguishable from deletion, in the tier least likely to
be watched. A miss is therefore confirmed against the bucket before it is reported as one, and a
bucket that cannot be reached raises rather than answering. `get_object` needs no such check —
it distinguishes `NoSuchKey` from `NoSuchBucket` — which is why the gap was only ever visible on
the `exists` path.

### 6a. An archived record is as durable, and as private, as the row it left

Archiving moves a record out of a database that fsyncs its writes and restricts its files. The
archive is therefore the one component in the path that must not have the weaker story, or "the
record moved" becomes "the record was moved and then lost" on the first power cut.

For the filesystem backend, write-then-rename is not sufficient on its own. `os.replace` is
atomic with respect to *readers* and says nothing about a crash: the directory entry can reach
the disk before the data it names, leaving a correctly-named object full of zeroes — which then
fails its own digest check on read, so the record is not merely lost but reads as corrupted. The
payload is fsynced before the rename publishes the name, and the containing directory after it,
so the name survives the same crash the bytes now do.

Exposure travels with the record for the same reason. A record readable only by the database
process does not become world-readable because it moved into a directory created under the
ambient umask, so the tree and the objects in it are owner-only — at every level, since a nested
scope is exactly where an intermediate directory would otherwise be created with default
permissions while the object beneath it was locked down.

### 7. Archiving is downstream of dreaming, not part of it

Consolidation (ADR-082226-5104 decision 7) decides what is *worth keeping*. Archiving decides
where kept things *live*. Two different questions, and fusing them means a storage-tier change
could silently alter what the system believes.

Archiving is driven by the existing memory-decay path rather than a second sweeper, for the same
reason `purge_expired` was moved inline: a scheduled sweeper that does not exist is how the
sessions table grew without bound.

### 8. Credentials come from the secret path

Object-storage credentials resolve through the vault (SPEC-011) — OS keychain locally, a cloud
secrets manager in hosted environments. Never the application database, never inline config.
Consistent with ADR-082226-5104 decision 11, which already says exactly this about secrets.

### 9. Off by default

No archive store configured means today's behaviour, unchanged, with no warning — this is a
deliberate absence, not a degraded mode, and warning on a deliberate choice is how operators learn
to ignore warnings.

### 10. Archive-eligible and purge-eligible are disjoint populations, and `retention_expires_at` already separates them (#273)

Decision 2 says a record whose identity nothing needs is deleted rather than archived. That rules
out the seam everyone reaches for first. `PgRunStore.purge_expired_runs` sweeps terminal Runs whose
`retention_expires_at` has passed and **deletes** them, in FK order, under `FOR UPDATE SKIP LOCKED`.
Archiving from inside that sweep would make archiving a way of not deciding deletion, which is
precisely what decision 2 forbids.

The separation does not need a new column, because the existing one already carries it. `Run.
retention_expires_at` is documented as *"when this Run may be purged, or None to retain it
indefinitely"* (ADR-082326-c126). So:

- **`retention_expires_at IS NOT NULL`** — a deletion date was chosen. The Run is purge-eligible
  and is never archived. Its bytes are going away on purpose.
- **`retention_expires_at IS NULL`** — the Run is kept indefinitely. It is the archive candidate,
  once it is terminal and has been terminal for longer than the configured archive horizon.

The two sets cannot overlap: a Run either has an expiry or does not. That is why this rule is
stated in terms of the field rather than a new `archive_after` column on the Run — a second
nullable date would let a record be both, and the first bug would be a Run deleted from the hot
store and left in the archive, or the reverse.

The horizon itself is deployment configuration, not a constant here. Open question 1 asked for a
number nobody had data for; this decision supplies the *predicate* and leaves the number to the
operator, which is the part that was actually undecidable.

Runs, NodeRuns and Attempts are the first — and for now the only — records this applies to. See the
amendment to open question 2.

## Consequences

### Positive

- The hot row store stays sized to the working set: smaller backups, faster restores, less index
  and buffer-cache pressure.
- Retention stops competing with performance, so "keep it" stops being a decision with a
  continuous cost.
- The homelab deployment gets the same tier with a directory and no cloud account.
- Content addressing makes re-archiving idempotent and corruption detectable.

### Negative / Trade-offs

- A second place a record can be is a second place it can be *missing*. The tombstone row bounds
  this — a missing object is a loud inconsistency against a row that says it should exist, not a
  silent gap.
- Archive reads are slow, and a call site that reads through without expecting it will feel it.
- Row counts do not shrink, so `COUNT(*)`-shaped monitoring will not show the win; bytes will.
- Another protocol with two implementations is another pair that can drift. The conformance-suite
  discipline from #122 applies: one set of test bodies, every backend.

### Neutral

- Object storage brings its own consistency and lifecycle semantics per provider. The narrow
  protocol keeps that surface small, but it does not vanish.
- This does not change what is *kept*. Retention policy is unaffected; only placement is.

## Open questions

1. ~~**Archive-eligibility thresholds**~~ — **resolved for Runs by decision 10** (#273): the
   predicate is `retention_expires_at IS NULL` plus terminal-for-longer-than a configured horizon,
   and the horizon is operator configuration rather than a number frozen here. Still open for the
   memory tables, which is moot while question 2 is.
2. **Vector rows** — a pgvector embedding is useless in object storage, since the point of it is to
   be searched in place. Either embeddings stay hot while their payload archives, or archived
   records leave the index. Needs a decision before memory archiving ships.

   **Deferred deliberately, with arithmetic (#273).** `EMBEDDING_DIMENSIONS = 1536` stored as
   `vector(1536)` is **6,144 bytes per embedding**, against a learning payload of a sentence or
   two. Archiving the payload while the vector stays hot moves the small part and keeps the large
   one, so on the vector-bearing tables this tier barely pays. `runs/pg_store.py` has no embedding
   column at all, so Runs and Attempt evidence — the records this ADR's own context opens by
   naming — are archivable without answering this question.

   The question therefore stays open, and memory archiving waits for row statistics rather than for
   an argument. An asynchronous cold vector search was considered and not adopted: of its three
   forms only a second, cold vector index shrinks the hot one, and that complexity is unjustified
   while the tables it would serve are the ones least worth archiving.
3. **Compaction** — whether many small cold objects eventually warrant rewriting into larger ones,
   accepting the read cost decision 5 rejects, once the object count itself is the problem.
