---
id: ADR-082326-c126
title: "Chat turn Run granularity and retention"
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-08-23
substrate:
  - maistro-engine#ADR-081226-a66b
implements: []
related:
  - maistro-engine#ADR-019
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

# ADR-082326-c126: Chat turn Run granularity and retention

## Context

ADR-081226-a66b makes `Workspace/Project → Graph → Run → NodeRun → Attempt` the
one execution identity, and #41 applies it to directly-submitted work. The task
half landed: `POST /tasks` admits a Run over a one-node Graph, returns its
`run_id`, and the Run is the authoritative lifecycle behind the task receipt.

The chat half was deliberately held back, because it raises two questions the
task path had already answered by having a queue at all.

**What is a chat turn's Run?** `route_request()` is a synchronous
request/response. A conversation has an identity (`session_id`) and so does a
single turn, and "one Run per turn" and "one Run per session, one NodeRun per
turn" are both defensible readings of the spine.

**How long does it live?** A task Run is kept as long as its receipt, and the
receipt has a retention policy (`MAX_TASK_STORE_SIZE`/`PRUNE_TARGET`) precisely
because it met the smaller version of this problem. A chat turn has no receipt,
no lifecycle of its own, and arrives orders of magnitude more often. Admitting a
Run per turn without answering this would ship a memory leak wearing the
convergence program's own vocabulary — and a durable table that grows without
bound is the same defect with a slower fuse, so "wait for PostgreSQL" is not an
answer either.

## Decision

**One Run per turn.** A Run has a terminal state; a conversation does not. A
Run-per-session would sit `RUNNING` for as long as somebody might type again,
which is exactly what recovery scans and the live-Run index read as a process
that died — the spine would be reporting a false positive on every idle
conversation. The conversation keeps the identity it already has: `session_id`
travels in the Run's provenance, so "every Run in this conversation" is a query
against existing data rather than a second kind of Run with different rules.

**A chat turn's Run is terminal when the turn is.** It is admitted `QUEUED`,
moved to `RUNNING` before dispatch, and terminalized `COMPLETED` or `FAILED`
when the turn ends, including when it ends by raising. A turn refused by the
Gate still gets a `COMPLETED` Run whose answer records the refusal: the turn
happened and was answered, and that is the audit trail worth having.

**Retention is bounded by the admitter, not by the store.** `ChatRunAdmitter`
keeps a window of the last `MAX_RETAINED_CHAT_RUNS` (500) Runs it admitted, and
deletes the oldest *terminal* ones as it overflows. This is enforced where the
pressure is created, so the bound holds on any store rather than only on the one
that happens to prune — and, critically, chat volume can no longer evict *task*
Runs through the shared `MAX_IN_MEMORY_RUNS` bound. A non-terminal Run in the
window is skipped rather than deleted: work in flight keeps its identity however
old it is, and a window full of live Runs grows rather than eating them, which
is the same failure the store's own bound already chooses and for the same
reason.

**A turn is never refused for want of a Run.** If admission fails, the turn is
answered anyway and the response simply carries no `run_id`. The chat path has
no receipt to fall back on, so refusing would convert "this process cannot
record the turn" into "this process cannot answer".

**`run_id` is additive on the response.** The OpenAI-compatible shape a caller
parses is unchanged; `run_id` sits alongside `choices` and is absent when no
chat admitter is wired.

## Consequences

### Positive
- A chat turn is followable through the same spine as a task, with no second
  vocabulary: one Graph, one Run, the same `admission_source` provenance field.
- The bound is testable directly — admit past the window and count what
  survives — rather than being a property of whichever store is configured.
- Task Runs are protected from chat volume, which the shared store bound alone
  could not do.
- Terminalizing on the raising path means an idle conversation never looks like
  a dead process to recovery.

### Negative / Trade-offs
- The retention window is per-process and starts empty after a restart, so a
  durable store can hold chat Runs that nothing will sweep. Closing that needs a
  startup sweep over the whole table, which belongs with the durable spine
  (#132) where the query exists; it is not a reason to leave the live process
  unbounded.
- A chat Run's Graph node carries the user's message text, exactly as a task's
  does. That is what makes the node executable rather than a decorative record,
  but it is user content in a durable store, and the tight retention window
  above is part of the mitigation rather than an accident.
- `RunStore` grew `delete_run`. A store with no way to forget a Run cannot
  implement any retention policy, so this is a gap being closed rather than a
  concession — but every implementation now owes it, including the PostgreSQL
  one landing in #132.
- 500 is a judgement, not a measurement. It is small enough that a busy process
  holds well under a megabyte of chat Runs and large enough that a `run_id`
  handed to a caller still resolves minutes later.

### Neutral
- Nothing about chat *routing* changes here. The turn still goes through
  `Conduit.route_request()` exactly as before; the Run is admitted around it.
- The task path is untouched: its Runs are not swept by this window, and its
  retention remains the store's own bound plus the receipt's.
