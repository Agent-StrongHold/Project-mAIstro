---
id: ADR-082226-c126
title: "Chat turns admit as one Run per turn, and Runs carry their own retention deadline"
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-08-22
substrate:
  - maistro-engine#ADR-082226-5104
  - maistro-engine#ADR-097
implements: []
related:
  - maistro-engine#ADR-062
  - maistro-engine#ADR-086
  - maistro-engine#ADR-087
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082226-c126: Chat turns admit as one Run per turn, and Runs carry their own retention deadline

## Context

The convergence program's rule is that work has exactly one execution identity
regardless of where it entered: `Workspace/Project → Graph → Run → NodeRun →
Attempt`. #41 made that true for `POST /tasks`. It deliberately left the chat
path alone, because chat raises two questions the task path had already
answered elsewhere.

**What is a chat turn's Run?** A task submission is unambiguous — one receipt,
one unit of work, one Run. A conversation is not. `session_id` already names a
conversation (`maistro.sessions`), so "one Run per session, one NodeRun per
turn" is a real candidate, and it is the one that makes a Run look most like the
multi-step graphs the spine was designed around.

**How long does a chat Run live?** `route_request()` is a synchronous
request/response through `maistro.conduit`. It has no queue, no receipt and no
retention policy of any kind. Chat turns are orders of magnitude more frequent
than task submissions, so a Run per turn is a growth rate the spine has never
been asked to carry. `InMemoryRunStore` grew a bound in #132
(`MAX_IN_MEMORY_RUNS`), but that bound is a last-resort eviction for a store
that was never meant to be the system of record; the PostgreSQL store has no
bound at all, and a Postgres table that grows without limit is the same defect
with a slower fuse.

Neither question can be answered by the code that admits the Run, because both
are policy. Writing them down is the point of this record.

## Decision

### 1. One Run per chat turn. The conversation is provenance, not a Run.

A chat turn admits as its own Run over the trivial one-node Graph
(`maistro.runs.admission.direct_work_graph`), exactly as a task does.
`session_id` is carried in `Run.provenance`, alongside the request id and the
submitting principal, so every Run of a conversation is recoverable by querying
provenance — the same correlation the task path already uses for `task_id`.

Run-per-session-with-NodeRun-per-turn is rejected on three grounds, all
structural rather than aesthetic:

- **A Run pins an immutable Graph snapshot.** `Run.graph` is a `GraphSnapshot`
  taken at creation, and every NodeRun must name a `node_id` present in it
  (`InMemoryRunStore.create_node_run` refuses otherwise). A conversation's Nth
  turn is not in a snapshot taken at turn 1, so a session-Run would require
  either mutating a frozen snapshot or pre-declaring nodes for turns that have
  not happened.
- **A Run has a terminal lifecycle; a conversation does not.** A session-Run
  would sit `RUNNING` for as long as the user might come back — days, or
  forever. Every consumer of the spine (recovery scans, the reconciler, the
  `ix_canonical_runs_live` index, retention) treats a long-lived non-terminal
  Run as a process that died mid-flight. Sessions would make that signal
  meaningless.
- **It would not fix the volume problem, only rename it.** A NodeRun and an
  Attempt per turn is the same row count with one fewer parent row.

### 2. Retention is a property of the Run, not of the store.

`Run` gains `retention_expires_at: datetime | None`. `None` means "retain
indefinitely" and is the default, so task Runs, graph Runs and every existing
Run behave exactly as they do today. The admitting entry point sets a deadline
when it knows the work is high-volume and low-value once finished — which today
means chat turns, whose default TTL is 7 days.

The alternative — a store-side rule such as "delete chat Runs older than N" —
was rejected because it puts the policy in the layer that knows least about the
work. The store would have to reach into `provenance['admission_source']` and
hard-code the classes of work it is allowed to delete, and every new entry point
would silently inherit whichever branch it happened to fall into. Making the
deadline a field means the decision is visible on the record itself: anyone
reading a Run can see how long it was promised to exist.

### 3. Purge is opportunistic, terminal-only, bounded, and orphan-safe.

`RunStore` gains `purge_expired_runs(*, now=None, limit=...) -> int`, implemented
by all three backends. Four rules:

- **Terminal only.** A Run past its deadline that is still running is not
  purged. Deleting the execution identity of live work is worse than the storage
  it reclaims, and the deadline is a floor ("retained until at least T"), not a
  ceiling.
- **Bounded batch.** A single call deletes at most `limit` Runs, so the first
  sweep after a long outage cannot become an unbounded delete.
- **Orphan-safe.** A Run that is the parent of another Run, or whose NodeRuns
  are the parent of another Run, is skipped. The spine's foreign keys are
  `ON DELETE RESTRICT` by design; retention must not be the thing that discovers
  that.
- **Cascading downward.** Purging a Run removes its NodeRuns and Attempts.
  Leaving them keeps the larger half of the storage while removing the index
  into it.

The sweep is driven inline from admission (`RunRetentionSweeper`), throttled to
at most one sweep per interval, and never blocks the admission it rides on. This
repository has no scheduled sweeper process, and two subsystems have already
learned that the hard way: `maistro.security.pg_strikes` clears its expired
windows on every check, and `SqliteSessionStore.purge_expired` was added
precisely because a read-time TTL filter hid expired content without ever
deleting it. A retention policy that depends on a cron job nobody has written
is not a retention policy.

## Consequences

### Positive
- A chat turn now has the same canonical execution identity as a task, so
  audit, correlation and (later) replay work uniformly across entry points.
- Retention is legible on the record: `retention_expires_at` says what was
  promised, rather than leaving it implicit in whichever store happened to be
  wired.
- Existing Runs are unaffected — `None` is both the default and the current
  behavior, so this cannot change the retention of work already recorded.
- The bound is enforced in the durable backend, not only in the in-memory one,
  which closes the "slower fuse" version of the leak.

### Negative / Trade-offs
- One Run, one GraphSnapshot per chat turn is real write amplification on a
  high-volume path. It is bounded by the TTL rather than eliminated.
- A conversation's Runs are only reassemblable by querying provenance; there is
  no parent row to join on. If conversation-level rollup becomes a first-class
  need, it should be a Project- or Workspace-level view, not a Run.
- Opportunistic sweeping means retention lag is proportional to traffic: a
  deployment that stops receiving chat stops purging. That is acceptable for a
  bound whose purpose is to stop unbounded growth — no traffic, no growth — but
  it is not a compliance-grade deletion guarantee.

### Neutral
- The default TTL (7 days) is configuration, not architecture. Deployments that
  want chat Runs kept forever set it to `None`; deployments with a stricter
  retention posture shorten it.
- Nothing here applies to conversation *content*, which lives in
  `maistro.sessions` and has its own TTL. This record governs the execution
  identity only.
