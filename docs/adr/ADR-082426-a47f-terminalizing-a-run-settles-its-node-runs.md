---
id: ADR-082426-a47f
title: "Terminalizing a Run settles its open NodeRuns, and closes them to further movement"
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-08-24
substrate:
  - maistro-engine#ADR-081226-a66b
implements: []
related:
  - maistro-engine#ADR-081426-1f7c
  - maistro-engine#ADR-062
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

# ADR-082426-a47f: Terminalizing a Run settles its open NodeRuns, and closes them to further movement

## Context

ADR-081226-a66b makes the Run the owner of universal logical lifecycle and says that
illegal transitions are rejected. What it does not say — and what no code enforced — is
that the Run's state and its NodeRuns' states are *related*. Each record validates only
its own transition, against `RUN_TRANSITIONS`, in isolation.

Two combinations follow, and both are reachable on the ordinary path on every backend:

- A Run reaches `completed` while its only NodeRun is still `running`. The Run says the
  work is finished; the record of the only thing that could have finished it says
  otherwise.
- That NodeRun then moves to `failed` *after* its Run is `completed`. The Run says the
  work succeeded and its only node says it failed, and both persist.

Neither needs a race. Every domain that terminalizes a Run does it from its own notion of
the outcome without consulting the nodes: `TaskRunAdmitter.record_transition` maps a
`TaskStatus`, `Container._terminalize` maps a chat turn's outcome, and the chat endpoint
cancels an abandoned stream's Run directly. The first combination is what an ordinary
failed turn *is* whenever its node was left parked; the second is what a slow executor's
reconciliation does when it lands after the domain has given up.

One subsystem already gets this right. The durable Graph executor grew
`_cancel_unfinished_node_runs`, which walks every non-terminal NodeRun and cancels it
before terminalizing the Run. It is correct, and it is local to the one subsystem that
happened to need it — the shape of a spine invariant that has not been hoisted.

The invariant is also already half-present in the stores: `create_node_run` refuses under
a terminal Run, in all three backends. You cannot *start* a node under a finished Run. You
can move one.

## Decision

**1. Terminalizing a Run settles every open NodeRun under it, atomically.**

`transition_run` to any of `completed`, `failed`, `cancelled` or `timed_out` first
transitions every NodeRun that is not already terminal, in the same transaction as the
Run's own write. A failure part-way through leaves the Run non-terminal: a half-settled
Run is a worse record than an unsettled one, because it looks deliberate.

**2. An open NodeRun settles to `cancelled`, whatever the Run settled to.**

Not to the Run's terminal status. The node did not itself succeed, fail or time out —
something outside it ended the work. Marking a node `failed` under a failed Run would
invent a physical outcome it never had, and would make one failure count twice for anyone
measuring node failures. `cancelled` says precisely what happened, and is the answer the
Graph executor reached independently; two subsystems arriving at it separately is an
argument for having one of it, not two.

Its `error` names the Run's terminalization, so a reader can tell a node cancelled *by its
Run* from one cancelled on its own. That distinction is the whole value of the field here:
without it the cascade is indistinguishable from six nodes that were each individually
cancelled.

A settled node's accepted outcome is superseded rather than carried over. That is forced
rather than chosen: `NodeRun` validates that its status *is* its accepted outcome's
`logical_status`, because an acceptance states the node's current logical disposition and
not a past one — a cancelled node still carrying an accepted `paused` outcome would be a
record claiming both at once. What a paused node was paused for survives where it was
written, on its Attempt.

**3. A NodeRun cannot transition once its Run is terminal.**

Refused with `RunIntegrityError`, in the register `create_node_run` already uses. This is
the half that makes the first two durable: without it, a reconciliation that lands late
rewrites the history of a Run that is closed, and the cascade's own work can be undone by
the very reconciliation it was racing.

**4. The Graph executor's local version is retired onto this one.**

`_cancel_unfinished_node_runs` is deleted rather than left beside the shared invariant.
Two implementations of one rule is how they drift.

## Consequences

### Positive

- The two impossible combinations become unrepresentable rather than merely unusual, on
  all three backends, enforced at the one seam every domain already goes through.
- A domain that terminalizes a Run no longer has to know what nodes exist under it. That
  is what makes the abandoned-stream path correct: it holds a `run_id` and nothing else.
- `GET /v1/runs/{run_id}/node-runs` stops showing `running` nodes under finished Runs,
  which is the reading that makes a live-inspection UI say a process died.

### Negative / Trade-offs

- **`transition_run` is no longer a single-row write.** A Run with many nodes costs a
  read and up to N writes under the parent lock. The alternative — refusing to terminalize
  a Run with open nodes — was rejected: it pushes the walk into every domain, which is this
  cascade written three times, and it leaves a Run with a genuinely stuck node
  non-terminal forever, which is exactly the "a process died here" signal terminalization
  exists to remove.
- A cascaded `cancelled` node carries no result. Work it actually did survives only on its
  Attempts, which are untouched. That is the correct place for it, but a reader looking at
  NodeRuns alone will see less than before.

### Neutral

- **Attempts are not cascaded.** An Attempt still `running` under a cancelled NodeRun is
  not a contradiction the store may resolve: the physical coroutine may genuinely still be
  executing, and writing `cancelled` onto it would be a lie in the other direction, at the
  layer whose whole purpose is to record what physically happened. Such Attempts are
  orphans, and recovering orphans is already `_reconcile_orphaned_attempts`'s.
- Terminalizing an already-terminal Run stays refused by `RUN_TRANSITIONS`, so the cascade
  cannot run twice.
