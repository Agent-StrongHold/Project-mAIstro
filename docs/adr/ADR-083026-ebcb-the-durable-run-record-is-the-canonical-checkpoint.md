---
id: ADR-083026-ebcb
title: "The DurableRunRecord is the canonical checkpoint; events/checkpoints.py is superseded"
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
  - maistro-engine#ADR-083026-a91e
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/events/test_checkpoint_contract_states_its_reach.py
layer: Reliability
owners:
  - '@BlakeMatthews-dev'
---

# ADR-083026-ebcb: The DurableRunRecord is the canonical checkpoint; events/checkpoints.py is superseded

## Context

Three checkpoint vocabularies exist, and the one written to look canonical is the
one nothing uses.

`maistro.events.checkpoints` is 428 lines. It defines `Checkpoint` with
`schema_version`, `executable_version`, a content hash and canonical Run ids;
`CheckpointRef`; three error types; a `CheckpointStore` Protocol;
`InMemoryCheckpointStore`; `SqliteCheckpointStore` over a `canonical_checkpoints`
table its own `_SCHEMA` creates; `checkpoint_created_event`; and
`SUPPORTED_CHECKPOINT_SCHEMA_VERSIONS`. It is precisely the shape #62's third
acceptance bullet asks for — "checkpoint records are versioned/compatible and
tied to canonical IDs".

Outside tests it is imported by exactly one file:

```
$ grep -rn "events.checkpoints" --include=*.py . | grep -v /tests/
./packages/maistro-core/src/maistro/events/__init__.py:12:from maistro.events.checkpoints import (
```

That is a re-export. `grep -ci checkpoint container.py` finds one hit and it is a
comment. No revision under `alembic/versions/` mentions a checkpoint table, so
`canonical_checkpoints` exists in no PostgreSQL deployment and has no twin.

**Meanwhile the durable graph already checkpoints, canonically and durably.**
`resume_durable_graph` exists on both the executor and the attempt executor;
`CanonicalDurableRunStore` binds records to canonical Run identity;
`GraphContinuationStore` has a SQLite implementation *and* a PostgreSQL twin in
`pg_continuation.py`. `container.py` already says which is which, in as many
words:

> `run_store` is the **canonical** `maistro.runs.store.RunStore` … there is no
> adapter here, because a `DurableRunRecord` is a checkpoint of one graph
> execution and a `Run` is the execution's canonical identity, and pretending
> either can stand in for the other is what produced the confusion.

A third vocabulary, ADR-056's `TaskCheckpoint`, is keyed by `task_id` and
versioned by `recipe_version`/`code_registry_version`. It is genuinely reached,
from `orchestrator/waves/ensemble.py`, `tasks/replay.py` and `tasks/recovery.py`.

**Two mechanisms hid the unreached one.** `maistro.events.checkpoints` is absent
from `quality/reachability-baseline.json` — not because anything reaches it, but
because a reachable package `__init__` imports it, so the walker counts it
reached and it is never classified or dispositioned. And `events/__init__.py:71`
holds `_CHECKPOINT_STORE_OPERATIONS`, a tuple of twelve method references that
exist only to be referenced. Vulture flagged all twelve as unused — correctly —
and the tuple answered by making them look used rather than by recording that
the store has no caller.

Finally, the names collide. Two `CheckpointStore` Protocols share a name and no
methods (`append`/`get`/`latest`/`list_run` versus `save`/`load`/`next_sequence`),
as do two `InMemoryCheckpointStore` classes, one exported from `maistro.events`
and one from `maistro.orchestrator.waves`. Which one an identifier denotes
depends on the import line — the same trap #717 found between the two
`SqliteInvocationStore` classes.

## Decision

**`DurableRunRecord` is the canonical checkpoint of a graph execution.** It is
what the executor writes, what `resume_durable_graph` reads, and the only one of
the three with a PostgreSQL twin and a migration. #62's first acceptance bullet
is met by that path today.

**`maistro.events.checkpoints` is superseded, not deleted.** Its module docstring
states that it is superseded, by what, and that nothing constructs it — the shape
#717 used for the unreached Invocation layer. Deleting 428 lines of a
carefully-specified contract is a larger decision than this issue should make
alone, and the schema-versioning and content-hash ideas in it are the ones a
future consolidation would want to keep. What it must stop doing is *reading as
current*.

**`_CHECKPOINT_STORE_OPERATIONS` goes.** A keep-alive tuple converts a true
signal into a false one: vulture's finding was correct and answering it by
manufacturing a reference is worse than no check at all. The identities are
recorded in the vulture ledger with an owner and a rationale instead, which is
where an intentional absence belongs.

**A re-export is not a use.** A module reachable only because a package
`__init__` imports it is not wired, and the reachability metric must not report
it as though it were. Whichever way that is resolved — teaching the walker the
difference, or classifying the module explicitly — the metric stops counting
this module as connected.

**The colliding names are disambiguated**, so that which `CheckpointStore` an
identifier denotes does not depend on the import line.

## Consequences

### Positive
- A reader meeting `events/checkpoints.py` learns its reach from the module.
- The reachability metric stops reporting an unwired module as connected, so the
  unreachable share the convergence matrix publishes gets more honest rather than
  more flattering.
- A suppressed dead-code signal becomes a recorded one.
- #62's fifth bullet — "retired duplicate lifecycle stores cannot become
  authoritative after restore" — gains a mechanism instead of a sentence.

### Negative / Trade-offs
- Keeping a superseded 428-line module costs reader attention even with the
  statement. The alternative, deleting it, discards a specified contract that the
  eventual consolidation may want; this defers that call rather than making it
  cheaply.
- Correcting the reachability walker may reclassify other modules that are today
  counted reachable only through a re-export. That is the metric getting more
  accurate, and it may move the published unreachable share.

### Neutral
- `TaskCheckpoint` and the wave path are untouched. Migrating them onto canonical
  identity is real work with its own risk, and belongs to #62's own convergence
  rather than to this decision.
- No migration: `canonical_checkpoints` never existed in PostgreSQL, so there is
  nothing to drop.
