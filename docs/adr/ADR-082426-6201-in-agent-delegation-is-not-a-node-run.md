---
id: ADR-082426-6201
title: "In-agent delegation is not a NodeRun, and the A2A local transport has no consumer"
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-08-24
substrate:
  - maistro-engine#ADR-081226-a66b
implements: []
related:
  - maistro-engine#ADR-019
  - maistro-engine#ADR-081226-69ee
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082426-6201: In-agent delegation is not a NodeRun, and the A2A local transport has no consumer

## Context

#42's fourth acceptance criterion is *no direct execution bypass remains on migrated core
paths*. An audit of every `await …handle(`, `await run_task(` and `await executor(` outside the
three adapters found that every migrated entry point does reach `RunExecutionService`:

| Entry point | Adapter | Landed |
|---|---|---|
| `POST /v1/tasks` | `tasks/execution.py` | #143 |
| Graph nodes | `graph/durable_runs/attempt_executor.py` | — |
| Chat turns | `runs/chat_execution.py` | #223 |

Two call sites remained, and neither is a migrated entry point escaping the spine. They are
different problems that happened to look alike.

**`agents/base.py` — in-agent delegation.** `BaseAgent.handle` checks `result.delegate_to`
and calls `_delegate`, which calls `target.handle(..., _delegation_depth=depth + 1)`. It is
live and reachable, and it already runs *inside* an Attempt, because whatever drove the outer
`handle` created one. The open question is whether the sub-delegation deserves a NodeRun of
its own.

**`container.py` — `_wire_a2a_broker`.** It builds an `A2ABroker` over a `LocalTransport`
whose `_invoke` calls `agent.handle` directly. It looks like a bypass and is not one:
**nothing in production reads `container.a2a_broker`.** It is constructed, stored on the
Container, and consumed only by tests. `A2ABroker` has no other construction site in `src/`
at all, and the one live `.delegate(` caller — `graph/nodes/agent_delegate_remote.py` — goes
through `GuestPeerManager`, not this broker, and already runs inside a NodeRun (#147).

## Decision

**1. In-agent delegation does not create a NodeRun.**

ADR-081226-a66b defines NodeRun as "one logical execution occurrence of **one Node in that
Run**". In-agent delegation happens inside one node's execution and is not a Node in the
Graph — the delegate is chosen by a reasoning strategy at runtime, from data the Graph never
saw. Giving it a NodeRun would make the spine's shape depend on a strategy's runtime choices
rather than on the Graph, which is precisely what NodeRuns project.

This does not contradict #147, which gives a *remote* A2A delegation a **child Run**. The
same ADR's "Child Runs" section allows a child Run to exist without being a node in the
parent's Graph; a NodeRun has no such licence. Two mechanisms, two scopes, one rule each.

**2. The delegation is made visible on the answer instead.**

The cost of (1) is the one #225 names: today the delegation is invisible. `_delegate` returns
the delegate's `AgentResponse` wholesale, so `agent_name` is overwritten and the delegator
disappears — including from the Attempt, which #223 taught to record the agent that handled
the turn. A record that names only the delegate is not wrong, but it cannot answer "who was
asked".

`AgentResponse` gains a `delegation_chain`: the delegators, outermost first, appended as the
response returns through each `_delegate`. It costs one tuple on a dataclass, it is bounded
by the existing depth limit, and it makes a delegated answer attributable without inventing
logical execution identity for something that has none.

**3. `Container.a2a_broker` and `_wire_a2a_broker` are retired.**

Not given a consumer. A surface that is constructed, stored and never read is worse than one
that is absent: it reads as supported, it is the shape `archive_store` was in before #133,
and the reachability ratchet cannot see it *because the container imports it* — which is how
it survived three audits.

`maistro/a2a/broker.py` itself stays. `A2ABroker` and `LocalTransport` are exported from
`maistro.a2a`, and `maistro-core` is a library other products import (ADR-019); deleting a
public class because *this* repo has no caller would be deciding for Stronghold and the
canvas app. What goes is the claim that the Container offers one — the part that was untrue.

## Consequences

### Positive

- #42's fourth criterion resolves to a stated decision plus one retirement, rather than
  remaining an open "audit the bypasses" item nobody can close.
- A delegated answer can name both the agent asked and the agent that answered.
- One fewer surface that looks like a supported execution path and is not.

### Negative / Trade-offs

- **The dead code stays invisible to the ratchet, and this makes that plainer.** I expected
  retiring the wiring to push `a2a/broker.py` into the unreachable set and cost a baseline
  row. It does not: `maistro/a2a/__init__.py` re-exports `A2ABroker`, so the module stays
  reachable through the package's own public API whatever the Container does. So the
  retirement removes a misleading surface and buys **no** new visibility — the code is now
  exported-but-uncalled instead of wired-but-unread, and `check-reachability.py` reads both
  as reachable.
- `delegation_chain` is carried in memory and on whatever record chooses to persist it. It is
  not itself durable execution identity, and a caller wanting delegation history across a
  restart still has only the Attempt's single agent name. That is the accepted cost of (1).

### Neutral

- The reachability ratchet cannot see this class of defect at all, by either route: a
  container attribute keeps a module importable, and so does a package re-export. This ADR
  removes one instance; the class of defect remains, and the audit that found it was a grep.
  A check that finds *exported but never called* is a different tool from the one that finds
  *never imported*, and the repository has only the second.
- Delegation depth stays bounded at 5 by `_MAX_DELEGATION_DEPTH`, unchanged. Bounded is still
  not declared, and declaring it is a Graph-shape question this decision deliberately leaves
  where it is.
