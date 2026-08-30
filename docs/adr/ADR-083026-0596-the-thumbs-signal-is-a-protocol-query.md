---
id: ADR-083026-0596
title: "A store's private state is not an interface: signals cross the boundary as protocol queries"
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
  - maistro-engine#ADR-082226-ff3c
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/hive-conductor/backend/tests/test_thumbs_read_through_the_protocol.py
layer: Memory
owners:
  - '@BlakeMatthews-dev'
---

# ADR-083026-0596: A store's private state is not an interface

## Context

The Conductor's optimizer reads four signals to propose DAG improvements. One
of them, user thumbs, was read like this:

```python
store = get_outcome_store()
for o in getattr(store, "_outcomes", []):
```

`_outcomes` is `InMemoryOutcomeStore`'s backing list. `PgOutcomeStore` and
`SqliteOutcomeStore` implement the same protocol and have no such attribute,
so against either of them the expression evaluates to `[]`.

That is a specific and unusually bad failure shape. It is not a crash, and it
is not a wrong answer that a test would notice — it is **an empty answer that
is indistinguishable from "no user has given a thumb yet."** The Optimization
Inbox would keep rendering. The optimizer would keep proposing. The user
satisfaction term would simply be zero, forever, and no log line anywhere would
say so.

Two readers had their own copy of it: `optimizer._collect_thumbs` and
`topology_compare._fold_in_thumbs`.

The consequence was structural, not hypothetical. `set_outcome_store` existed
precisely so the Conductor could bind the Container's durable store, and it had
**no production caller** — so every thumb a user gave went into a capped
in-process list and was lost on restart. Making that call, the obvious
one-line fix, is what would have emptied both readers. The durability bug and
the encapsulation bug were locked together: neither could be fixed alone.

## Decision

**A signal crosses a store boundary as a method on the protocol, never as an
attribute of an implementation.** `OutcomeStore` gains `list_thumbs`, and every
implementation answers it.

Three things follow, and each is a decision rather than a detail:

**The query carries the reader's semantics, not the reader's loop.** The old
reader treated a thumb with an empty `dag_id` as belonging to every DAG —
those predate the attribution wire, and excluding them would discard real
feedback to tidy a filter. That rule now lives in the protocol's contract and
in all three implementations, where it is stated once and tested once, instead
of being an inline `if` that a durable implementation had no way to infer.

**The predicate belongs in the store.** A durable implementation pushes the
scoping into SQL rather than filtering rows it has already fetched, so a row
bound limits candidates rather than survivors. A protocol method that can only
be implemented by fetching everything and filtering in Python is a private
attribute with extra steps.

**Retention becomes explicit.** The old reader had no time window and no bound:
its effective retention was whatever `MAX_OUTCOMES` happened to be and its
effective window was "since this process started". Neither was chosen. A
protocol query has to name both, which is the point.

### Enforced, not just agreed

A reader reaching for `_outcomes` again would pass every behavioural test in
the Conductor suite, because those run against the in-memory store that has the
attribute. So the rule is a gate: a test parses every production module and
fails on `x._outcomes` or `getattr(x, "_outcomes", ...)` outside the store that
defines it.

It parses rather than greps. A substring scan flags `list_outcomes` and
`pg_outcomes`; a word-boundary scan flags the docstrings that explain the
defect. Both false-positive classes invite an allowlist, and any allowlist
large enough to silence them would have had to name the two modules that held
the bug.

## Consequences

### Positive
- A thumb survives a restart, which is what the feedback endpoint always implied.
- The optimizer and the topology comparison read one aggregation, so they cannot
  disagree about what a thumb counts for.
- The failure mode this closes was silent; the gate that replaces it is loud.
- Retention and scope for user-supplied feedback are now stated and tested.

### Negative / Trade-offs
- Reading a signal now requires `await`, so `run_optimizer` and
  `compare_variants` and their routes became async. That is the honest shape —
  they read a database — but it is a wider diff than binding the store would
  have been.
- Every new signal needs a protocol method rather than a comprehension over
  whatever the store happens to hold. That is the cost being paid deliberately.

### Neutral
- The Hive-local in-memory default stays for processes with no bridge. A thumb
  still records there, deterministically; it is simply not durable, and nothing
  claims otherwise.
