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
deletes the oldest ones as it overflows — terminal Runs, and stalled
non-terminal ones with nothing left living in them *(amended 2026-09-26, see
below)*. Admission sweeps when a new Run arrives, and the canonical chat
execution seam invokes the same sweep after terminalizing a turn; the latter
closes the otherwise-unbounded final burst that has no subsequent admission.
This is enforced where the pressure is created, so the bound holds on any store
rather than only on the one that happens to prune.

**A stalled turn may not hold the window open** *(amended 2026-09-26, repair
round on #131's retention bound)*. The window originally skipped every
non-terminal Run, on the reasoning that work in flight keeps its identity
however old it is. The reasoning was right about work in flight and wrong
about the test it chose: a Run's status alone cannot tell a live turn from a
dead one. A turn whose executor never came — a stranded admission with no
Attempt (#338), an Attempt whose lease lapsed, a finished Attempt under a Run
nobody closed — stays non-terminal forever, so a window that shields every
non-terminal Run grows without limit exactly when the process is misbehaving,
which is when it must not. The window now reads the liveness signals the spine
already trusts instead of the status byte. A non-terminal Run past the window
is forgotten unless something could still be living in it: it is dispatch-
pending (the seam admitted it and has not settled its dispatch), still
CREATED/QUEUED (mid-admission, which the admission path compensates itself),
or holds an Attempt inside its lease — the chat executor leases every Attempt
it creates and renews it while the turn runs (#1170), and
`recover_abandoned_attempts` already reclaims on exactly that lease's expiry,
so a live turn is never evicted, and the live population is bounded by how
many turns can be in flight at once, not by the window. The dispatch-pending
mark is seam bookkeeping, not a new authority: `route_request` sets it between
its Run's QUEUED and RUNNING transitions (so no sweep ever observes the
RUNNING, Attempt-less, unshielded moment), releases it when the turn closes —
including the refused, cancelled, and dispatch-unrecorded exits — and a
process death clears it with the window that reads it. Two costs are accepted
and named. First, an admission-only caller of `_admit_chat_turn` — one that
admits without intending to dispatch — leaves its Runs unshielded, so an
abandoned admission is evictable at the next turn rather than kept; that is
the policy working, since nothing will ever terminalize such a Run. Second,
every non-terminal Run left CREATED/QUEUED by a caller that neither finishes
nor compensates its admission is shielded until it terminalizes; the shipped
seam compensates its own admission failures on the spot (#338), so the shape
is reachable only by a caller that abandons admission half-done, which is the
caller's contract to close.

**And the store's own bound is source-aware.** The admitter's window alone does
not deliver "chat volume cannot evict task Runs", because the store's bound runs
inside `create_run` — before the new Run reaches any admitter. So
`InMemoryRunStore` evicts terminal Runs from ephemeral sources
(`EPHEMERAL_ADMISSION_SOURCES`, today just `chat`) first, and touches Runs from
durable sources only when it is still over its *hard* bound afterwards, never
merely to reach the softer prune target. A task Run is the execution identity
behind a receipt a caller still holds; a chat Run's job is to be followable for
a while after its turn. Ordering the eviction by that difference is what makes
the guarantee real rather than asserted.

**A turn that cannot get its Run is refused, retryably** *(amended 2026-09-23,
owner decision on #1108; supersedes #223 AC4)*. Every answered turn has a
canonical Run, NodeRun and Attempt. If no chat admitter is wired, admission
fails, or the spine fails before the dispatch, the turn raises
`ChatTurnRefused` — HTTP doors answer `503` with `Retry-After` — and nothing
reaches the model; a Run admission already persisted is cancelled rather than
stranded. The original rule ("a turn is never refused for want of a Run",
answering with no `run_id`) traded governance for availability, and the owner
chose governance: an ungoverned answer is not a degraded mode. A spine failure
*after* the dispatch is different — the answer exists, so it is returned once
and the Run is left open for recovery (`ChatDispatchUnrecorded`), never
redispatched.

**The turn's answer is on the Run, bounded.** A completed turn records its
`finish_reason` and the first `MAX_RECORDED_ANSWER_CHARS` of the assistant's
text, flagged when truncated. That is what makes "a refused turn's answer is
recorded" true rather than aspirational. It is a bounded projection and not the
transcript: the conversation itself lives in `maistro.sessions`, and a chat
Run's small size is part of why the retention window can be as generous as it
is.

**Admission does not name an agent it has not chosen.** The agent is recorded
only when the submission named an intent the deployment knows — the one case
where admission provably resolves what the Conduit will, because
`_apply_intent_hint` overrides the classification with a valid hint. Otherwise
the node's `to_agent` is empty and provenance says `agent_selection: deferred`.
Resolving the empty hint would name the registry's fallback for work another
agent went on to do: a canonical record that contradicts what happened, which is
worse than one that admits the agent was not yet chosen.

**`run_id` is additive on the response.** The OpenAI-compatible shape a caller
parses is unchanged; `run_id` sits alongside `choices` on every answered turn.

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
- Since the 2026-09-23 amendment, a store or project outage that blocks
  admission is a chat outage (retryable 503) rather than unrecorded answers.
  That is the chosen cost: an answer outside the governed path is not offered.
- `RunStore` grew `delete_run`. A store with no way to forget a Run cannot
  implement any retention policy, so this is a gap being closed rather than a
  concession — but every implementation now owes it, including the PostgreSQL
  one landing in #132. It refuses a Run that has child Runs: those hold foreign
  keys into exactly the rows a delete would remove, so SQLite would fail partway
  through and the in-memory store would silently orphan them. Refusing is the
  one answer both can give truthfully.
- A chat Run whose turn had no intent hint records no agent. Anything reading
  the Graph for "who handled this turn" must read the *dispatched* agent
  elsewhere, and today there is nowhere: binding it needs the Conduit to report
  its selection, which is #142. Recording nothing is the honest interim state,
  not a complete one.
- 500 is a judgement, not a measurement. It is small enough that a busy process
  holds well under a megabyte of chat Runs and large enough that a `run_id`
  handed to a caller still resolves minutes later.

### Neutral
- Nothing about chat *routing* changes here. The turn still goes through
  `Conduit.route_request()` exactly as before; the Run is admitted around it.
- The task path is untouched: its Runs are not swept by this window, and its
  retention remains the store's own bound plus the receipt's.
