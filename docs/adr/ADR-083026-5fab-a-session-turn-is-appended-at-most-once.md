---
id: ADR-083026-5fab
title: "A session turn carries an identity, and is appended at most once under it"
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
  - maistro-engine#ADR-083026-427c
implements: []
related:
  - maistro-engine#ADR-082326-c126
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

# ADR-083026-5fab: A session turn carries an identity, and is appended at most once under it

## Context

`PgSessionStore.append_messages` is atomic and serialized. A transaction-scoped
advisory lock on the session identity spans the `MAX(seq) + 1` read, every
insert and the inline retention purge, so two *different* writers cannot
collide on a sequence number and no batch can commit a prefix.

That is the whole of what a lock can do. It says nothing about the **same**
writer arriving twice, and #327's last open criterion is exactly that:

> Retry behavior is idempotent and cannot duplicate a client turn.

This is not a hypothetical. `ChatAttemptExecutor.execute` is explicit that a
re-run of one turn is a second Attempt under the same logical NodeRun rather
than a second NodeRun — the Graph has one node, and it was tried twice. Each
Attempt re-enters `conduit.route_request`, reaches `agent.handle`, and reaches
`BaseAgent._persist_run`, which appends `[user, assistant]` to the session. The
second Attempt therefore writes the user's message a second time, at fresh
sequence numbers, indistinguishable from the user having said it twice. The
retry preserved the Run's history and corrupted the conversation it was
retrying.

Nothing in the signature, the table, or any caller carries a key that could
tell the two apart. The store cannot infer one: content is not identity, and
deduplicating on `(role, content)` would silently drop a user who says "yes"
twice — trading a duplication bug for a data-loss bug that no test would ever
catch, because the second "yes" looks exactly like the mistake.

## Decision

**A turn identity is supplied, never inferred.** `append_messages` takes an
opaque `turn_id`. The store treats it as a name, not as data: it never parses
it, and it never derives one when none is given. With no `turn_id` the append
behaves exactly as it does today, so no existing caller changes meaning.

**The identity is the NodeRun, because that is already what "the same turn"
means.** `ChatAttemptExecutor` decides which Attempts belong to one logical
turn, and it answers with the NodeRun. Choosing anything else would let two
components disagree about turn identity while both being right about their own.
A fresh identity per Attempt would be no identity at all; the Run's id would be
wrong in the other direction, since a client that re-requests after a timeout
is admitted a *new* Run and is a new turn as far as the spine is concerned.

**At most once, not exactly once.** The guarantee is that a `turn_id` already
recorded for a session appends nothing and raises nothing. It is deliberately
not "the retry returns what the first append wrote": `append_messages` returns
nothing, the caller already has the answer it is persisting, and promising to
reproduce a prior write would require storing a response the store has no
business holding.

**The database enforces it, not the lock.** A `session_turns` row per
`(session_id, turn_id)`, primary-keyed on the pair, is inserted in the same
transaction as the messages. The advisory lock already makes the check-then-
insert race-free, so the key is redundant *for this code path* — which is the
point. It is what makes the property survive a second write path that forgets
the lock, and a check that only holds while everyone remembers to hold a lock
is a convention, not a constraint.

The marker is a row rather than a column on `sessions` because the fact has a
different arity from a message: one turn writes several messages, so a unique
index over `(session_id, turn_id)` on the message table would reject the second
message of the very batch it is meant to admit. Storing the identity on the
head message only would make the constraint expressible and the column
unreadable — `turn_id` would mean "this message opened turn X" on one row and
nothing on the next.

**The marker expires with the messages it admits.** Both are written under one
TTL and purged by the same sweep. A marker outliving its messages would suppress
a turn that no longer exists; messages outliving their marker would let a retry
duplicate. `delete_session` drops both, under the same lock, for the same
reason: a session recreated under a reused id must not have its first turn
silently swallowed by the deleted one's marker.

## Consequences

### Positive
- A retried chat turn no longer duplicates the user's message, on the one retry
  path the runtime actually takes today.
- The guarantee is a database key, so it holds for a future writer that has not
  read this decision.
- Callers that pass no identity are unaffected, so the change is additive at
  every seam it crosses.

### Negative / Trade-offs
- One more table, and one more row written per identified turn. The row is two
  short strings and a timestamp; the alternative shapes were rejected above.
- The identity has to travel from the executor that knows it to the agent that
  writes the session, crossing the Conduit. That widens `ChatDispatch` from a
  thunk to a one-argument call — the dispatch stops being a value the pipeline
  fully binds in advance, because one part of it is only known deeper in.
- A caller that supplies no `turn_id` gets no guarantee, and nothing forces one
  to. That is the honest position: the store cannot manufacture an identity for
  a turn it did not observe being retried.

### Neutral
- No change to sequence allocation, ordering, the advisory lock, or the shape
  of `get_history`.
