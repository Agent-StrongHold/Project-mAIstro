---
id: ADR-083026-a322
title: "Episodic memory is durable, and the scope rule has one meaning in two languages"
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
  - maistro-engine#ADR-013
  - maistro-engine#ADR-016
  - maistro-engine#ADR-080
implements: []
related:
  - maistro-engine#ADR-082926-0b72
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/persistence/test_episodic_store_conformance.py
layer: Memory
owners:
  - '@BlakeMatthews-dev'
---

# ADR-083026-a322: Episodic memory is durable, and the scope rule has one meaning in two languages

## Context

`episodic_memories` has existed since migration 001. Migration 006 converted its
two timestamps to `timestamptz` and migration 008 gave eight of its columns
server defaults. It carries the index `ix_episodic_org_scope`.

Nothing writes to it. Nothing reads from it. `grep -rn "episodic_memories"
--include=*.py packages/` returns matches only under `alembic/`.

`EpisodicStore` and `DecayableEpisodicStore` are protocols with exactly one
implementation between them, `InMemoryEpisodicStore`, which holds a list. And
`create_container` constructs it unconditionally — not on the `memory://`
branch, but after the backend branch has already run, so a `postgresql://` URL
gets it too.

So the whole of ADR-080: the seven tiers, the reinforcement and contradiction
counts, the promote-to-wisdom and demote-to-regret thresholds, and the weight
floors that make wisdom and regret structurally unforgettable — all of it is
process-local. It is empty after every restart, and two replicas of the same
deployment hold different memories of the same agent. CLAUDE.md decision 5 says
"memory must forget"; what shipped forgets everything, on a schedule set by the
process manager.

Two smaller things follow from the same gap.

**The table could not hold the record even if something wrote it.**
`EpisodicMemory` carries `project_id` — which `list_by_scope` filters on —
`decay_rate`, `shared` (ADR-080 part C) and `flagged_for_review` (ADR-080 part
B). Migration 001 created none of them. "The table exists" was never the same
claim as "the record fits".

**A document asserts the opposite of all of this.** Migration 011's docstring
names `episodic_memories` among "the tables `maistro.memory` actually reads and
writes". Its own `_EMBEDDED_TABLES` comment, twenty lines below, gives the true
reason it is excluded: "the container wires `InMemoryEpisodicStore` even on
PostgreSQL, so the indexes would exist, cost write time, and index nothing."
The code was right and the prose above it was never corrected.

## Decision

Episodic memory becomes durable. The table is not dropped.

**1. The record and the row are made to match.** Migration 026 adds
`project_id`, `decay_rate`, `shared` and `flagged_for_review`, and an index on
`(org_id, scope, weight)` for the read `list_by_scope` performs. The four
columns are added nullable-with-default rather than backfilled: no row exists to
backfill.

**2. Two stores, one protocol pair.** `PgEpisodicStore` over asyncpg and
`SqliteEpisodicStore` over aiosqlite, the same twin arrangement `learnings` and
`outcomes` already use. Both satisfy `EpisodicStore` *and*
`DecayableEpisodicStore`: a durable store that could not sweep would move the
decay ladder from "process-local" to "never runs", which is not an improvement.

**3. The backend selects the store, in the place that already selects stores.**
`_wire_episodic_store(pg_pool=..., db_pool=...)`, shaped exactly like
`_wire_prompt_manager` and for the reason stated there — adding a backend must
not grow `create_container`'s branch count. A `memory://` URL still gets
`InMemoryEpisodicStore`, and now that is a choice rather than the only option.

**4. The scope rule is written once and compiled twice.** This is the load-bearing
decision. `matches_scope` is not a simple equality: a `global` memory carrying
an `org_id` is visible only to that org, and a `team` match additionally
requires the caller's org — two clauses that exist to stop cross-org leakage. A
store that filtered in SQL by re-typing those clauses would be a second spelling
of a security rule, and #622 is the record of what happens when one formula
acquires four spellings.

So `maistro.memory.scopes` gains `scope_predicate(filters)`, returning the SQL
fragment and its parameters, and sits beside `matches_scope` in the same module.
A test drives both over the same generated corpus and fails if they disagree on
any memory. The rule has one home; the two languages are compiled from it.

Filtering happens in the database, not after an unscoped fetch — the property
#188 established for similarity reads, for the same reason: a scope filter
applied in Python is a scope filter that ran after the rows crossed the
boundary.

**5. Retrieval ranks over the top-weighted candidates, and says so.**
`retrieve` selects the scope-matching live rows ordered by weight, capped at
`RETRIEVAL_CANDIDATE_CAP`, then ranks them with `maistro.memory.episodic.ranking.rank`
— the same function `InMemoryEpisodicStore` uses, not a SQL restatement of it.
The cap is a real difference from the in-memory store, which ranks over
everything, and it is deliberate: the ladder's whole premise is that weight is
how much a memory matters, so the highest-weighted rows are the right candidate
set to bound on. Below the cap the two stores return identical results, and a
conformance test asserts that.

**6. No embedding column.** `episodic_memories` does not get one here.
Migration 011 refused to add columns nothing would write, and adding one now —
when `retrieve` ranks lexically — would recreate exactly the accepted-design-
with-no-caller shape that refusal was about. It lands with its producer, in the
change that writes it.

**7. Migration 011's docstring is corrected.** The sentence that says
`maistro.memory` reads and writes `episodic_memories` is replaced with what was
true at 011 and why the table was excluded.

## Consequences

### Positive
- An agent's memories, and the tier each has been promoted or demoted to,
  survive a restart and are shared between replicas.
- The decay sweep operates on a durable ladder, so the weight floors are a
  retention property rather than a property of one process's uptime.
- The cross-org visibility rule is stated once. A future backend compiles it
  rather than re-deriving it.

### Negative / Trade-offs
- `apply_decay` reads the live rows and writes each back rather than issuing one
  UPDATE. An UPDATE would be a second spelling of `tick_decay`, which depends on
  each row's own `decay_rate` and `last_accessed_at`; the sweep cost is the
  price of one decay formula.
- `retrieve` over a corpus larger than `RETRIEVAL_CANDIDATE_CAP` can differ from
  the in-memory store's answer. Stated in the spec, and bounded by weight rather
  than by insertion order so the truncation is the ladder's own judgement.

### Neutral
- Deployments on `memory://` are unchanged, and are now the only ones whose
  episodic memory is volatile.
