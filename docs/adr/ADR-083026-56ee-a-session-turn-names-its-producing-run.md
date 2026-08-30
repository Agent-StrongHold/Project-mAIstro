---
id: ADR-083026-56ee
title: "A session turn names its producing Run, and a correlation id keeps its own name"
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
  - maistro-engine#ADR-083026-e602
  - maistro-engine#ADR-083026-1cb1
  - maistro-engine#ADR-083026-5fab
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Memory
owners:
  - '@BlakeMatthews-dev'
---

# ADR-083026-56ee: A session turn names its producing Run, and a correlation id keeps its own name

## Context

ADR-083026-e602 gave `learnings`, `outcomes` and `design_outputs` nullable
`run_id`/`node_run_id`/`attempt_id`, resolved from the ambient
`ExecutionContext` of ADR-083026-1cb1. Two records in the same neighbourhood
were left out, and each was left out for a reason that no longer holds.

**A session turn's link to its Run is a coincidence of one call site.**
`container.py` passes the Run id as the turn identity:

```python
turn_id=run.run_id if run is not None else None,
```

but `turn_id` is, by its own contract, an opaque idempotency key. Its whole
definition is `sessions/turns.py`:

```python
def reject_blank_turn_id(turn_id: str | None) -> None:
    """A turn identity is either absent or a name; ``""`` is neither."""
```

Nothing states that it names a Run. ADR-083026-5fab introduced the
`session_turns` table purely as a retry marker, which is what #327 needed and
all it claimed. The SQLite twin declares `turn_id TEXT NOT NULL` with no
semantics. Any caller of `append_messages` may pass any non-empty string. So a
reader of `session_turns` cannot answer "which Run produced this turn": the
value is a Run id today by accident, and depending on that is depending on an
invariant nothing holds.

**The Run-to-session direction exists, but only as unindexed JSON.**
`ChatTurnAdmitter.admit` does record the session on the Run's provenance, which
lands in `canonical_runs.payload -> 'provenance'`. Answering "the Runs of this
session" is therefore a sequential scan of a table that a retention sweeper and
an archive sweeper both walk.

**And `Outcome.request_id` carries a session id.** At the one production site
that writes the field:

```python
outcome = Outcome(
    request_id=session_id or "",
```

`ExecutionContext` gives `request_id` and `session_id` distinct canonical
meanings and carries both. `Outcome` has no `session_id` field at all, so the
session is recorded only under a name that means something else — beside three
columns from ADR-083026-e602 that do mean what they say. Nothing filters on
`outcomes.request_id`, which is why this has been invisible rather than
harmful; it is still a table whose schema is untrue, and outcomes are what the
router's scoring and the optimizer's fitness read.

The same value is also passed to the coin ledger as `charge_usage(request_id=)`.
That ledger is duck-typed against an external service with no protocol in this
repository, so its contract cannot be read here.

## Decision

**A session turn names its producing execution in fields that mean it.**
`session_turns` gains nullable `run_id`, `node_run_id` and `attempt_id`,
resolved from the ambient `ExecutionContext` exactly as ADR-083026-e602
resolves them, on the PostgreSQL store and the SQLite twin alike.

**`turn_id` keeps the meaning it has.** It stays an opaque idempotency key and
its docstring says so. The fix is a new field that names a Run, not a
re-reading of an old field that does not — a re-reading would silently promote
every existing caller's string to a Run id.

**Nullable, not `NOT NULL DEFAULT ''`.** A turn appended with no execution in
scope records no Run. An empty string would make every such row claim a Run
whose id is empty, which is the over-claim ADR-083026-a91e removed elsewhere.

**The Run-to-session direction gets an index.** An expression index on
`canonical_runs (payload -> 'provenance' ->> 'session_id')`, following the
precedent migration `015` set in this same table for `schedule_id`.

**`Outcome` gains `session_id`, and `request_id` stops carrying one.** The
session goes in the field named for it. `request_id` carries a request id or
nothing. Rows written before this migration may hold a session id under
`request_id`; the migration says so rather than rewriting them, because a
backfill would have to guess which of two meanings each historical row had.

**The ledger charge is keyed per turn.** A parameter named `request_id` given a
*session* id is wrong under both readings available to us: if the ledger dedupes
on the key, every turn after the first in a session is dropped; if it merely
groups, the grouping is by session while the charge is per turn. The Run id is
correct under both, and is what this passes. This is a correction made without
the external contract in hand, and it is deliberately the narrowest one that is
right under every reading rather than the one a particular guess would favour.

**Sessions still own no execution lifecycle.** No session store starts, closes,
retries or cancels anything. It records the execution it was told about, and a
test holds that surface still.

## Consequences

### Positive

- Given a session, a reader can name every canonical Run that produced its
  turns; given a Run, its session — both from indexed columns, neither by
  inferring meaning from a field documented to carry something else.
- The last two records in this neighbourhood join the ones ADR-083026-e602
  already made honest, so #64's third acceptance bullet has a mechanism rather
  than a coincidence.
- A per-turn billing key removes a plausible dropped-charge path, and removes it
  in the direction that is safe if the ledger turns out not to dedupe at all.

### Negative / Trade-offs

- Three more nullable columns and one more index on the session write path. The
  index is on `run_id` only, for the same reason ADR-083026-e602 gave: "what did
  this execution produce" is the question, and a `run_id` lookup already narrows
  enough that indexing the NodeRun and Attempt would buy little for three extra
  writes per row.
- `outcomes.request_id` becomes ambiguous across the migration boundary: rows
  before it may hold a session id, rows after hold a request id or nothing. The
  alternative — backfilling `session_id` from `request_id` — assumes every
  historical row came from the one call site that wrote a session there, which
  is exactly the kind of assumption this ADR exists to stop making. The
  ambiguity is recorded instead of erased.
- The ledger key change is a behaviour change to an external integration made
  from the parameter's name and the two readings of it, not from its contract.
  If the ledger keyed reporting on the session deliberately, this splits its
  reports per turn. That is a recoverable, visible change; a silently dropped
  charge is neither.

### Neutral

- The `session_turns` retry semantics of ADR-083026-5fab are untouched:
  `turn_id` remains the primary key with `session_id`, and the new columns are
  descriptive.
- Nothing reads `outcomes.request_id` as a filter today, so no consumer changes
  behaviour when its meaning narrows.
