---
id: ADR-083026-14c3
title: "An emptied Attempt output is repaired only where a second copy proves it was emptied"
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
  - maistro-engine#ADR-081226-a66b
implements: []
related:
  - maistro-engine#SPEC-082926-2844
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Reliability
owners:
  - '@BlakeMatthews-dev'
---

# ADR-083026-14c3: An emptied Attempt output is repaired only where a second copy proves it was emptied

## Context

Before #566, a node returning a typed model persisted its Attempt as
`output: {}`: Pydantic serialized a union member declared as bare `BaseModel`
through that class's empty schema. SPEC-082926-2844 fixed the contract and
deliberately did not repair the rows already written, recording the repair as
this decision's to make.

The first attempt at that repair shipped and had to be withdrawn (#638). It ran
over `SqliteDurableRunStore`, a document-shaped table nothing in production
writes: `container.py` wires `CanonicalDurableRunStore`, whose `get` assembles
Attempts from the canonical `RunStore`. Run against a real deployment, the
survey **created** an empty table and reported that there was nothing to repair.
A survey that answers the wrong question confidently is worse than no survey,
and this one also could not reach a PostgreSQL deployment at all, since it took
a filesystem path.

So the repair has to reach Attempts where they actually live. Two facts make
that harder than a read-modify-write.

**There is no write path for an Attempt's recorded result.**
`transition_attempt` moves an Attempt's status and records evidence *as it
finishes*; it does not rewrite the evidence of one that finished long ago.
`DurableRunStore.update` mirrors lifecycle state and never touches
`Attempt.result` either.

**The evidence is recorded twice, and the two must agree.** For the Attempt its
NodeRun accepted, `NodeRun.accepted_outcome.attempt_result` embeds a copy of
that Attempt's result, and `validate_accepted_outcome_against_attempt()` raises
if the two diverge. Repairing the Attempt alone would leave the record holding
two different physical results for one execution — trading a lost output for a
self-contradicting spine.

## Decision

**Repair only what a second copy proves was lost.** `output: {}` is
indistinguishable from a node that genuinely returned an empty mapping; the
envelope never recorded which. So emptiness alone is not damage, and the survey
never treats it as such.

An Attempt is **repairable** exactly when its NodeRun's accepted outcome names
it *and* `NodeRun.result` carries an output the Attempt's does not. That
combination is proof rather than inference: the executor has always dumped the
model explicitly onto `NodeRun.result` via `_result_output`, so a logical record
holding a value beside a physical record holding `{}` is the defect's signature
and nothing else's. The match is by `attempt_id`, so it is exact.

Everything else is reported and left alone, under the reason it cannot be
repaired — a superseded retry, a failure, or an in-flight try has no second copy
anywhere, and an accepted Attempt whose NodeRun is *also* empty is a case where
nothing distinguishes loss from a genuine `{}`. Reporting these as "unrepairable"
rather than "clean" is the point: the operator learns what the tool cannot see,
which is the half the withdrawn version got wrong.

**One store method does both writes.** `RunStore.repair_attempt_result` rewrites
one terminal Attempt's recorded result and, when its NodeRun's accepted outcome
names that Attempt, rewrites the embedded copy in the same operation. The store
derives the new outcome from the repaired Attempt rather than accepting one from
the caller, so a caller cannot leave the two disagreeing — the invariant is
enforced by the only path that can break it, not by everyone who uses it.

The method is deliberately narrow: it refuses an Attempt that is not terminal,
and it changes nothing but the result. An operator repair that could move a
status would be a second, unreviewed lifecycle path.

**The survey states its own bound.** `RunStore` offers no cursor over every Run,
so a walk is necessarily capped. The survey reports how many Runs it examined
and says explicitly when it stopped at the cap, rather than presenting a partial
sweep as a complete one. That is the same failure the withdrawn version had —
answering more confidently than the evidence supports — and it must not be
reintroduced through the back door of an unstated limit.

**Survey by default; repair only when asked.** The command reports without
writing unless told to apply, because the first thing an operator wants from a
data-repair tool is to know what it would do.

## Consequences

### Positive
- The repair reaches the store production actually writes, on both SQLite and
  PostgreSQL, because it goes through the configured `RunStore` rather than a
  path built from a filename.
- A repaired Attempt cannot leave the spine self-contradicting, since the two
  copies move together in one call that derives one from the other.
- An operator is told what the tool cannot determine, instead of being told
  everything is fine.

### Negative / Trade-offs
- Attempts genuinely lost — superseded retries, failures, in-flight tries — stay
  lost. There is no second copy to recover from, and inventing one would be a
  guess written into a durable record.
- `RunStore` grows a method that exists for an operator action rather than for
  the runtime. It is the smallest such method that can hold the invariant, and
  the alternative is a caller that can break it.
- The survey is capped, so a very large deployment needs more than one pass.
  Stating the cap is the honest version of that limitation, not a fix for it.

### Neutral
- No change to `NodeResult` serialization, to `_result_output`, or to how any
  Attempt is written during execution.
