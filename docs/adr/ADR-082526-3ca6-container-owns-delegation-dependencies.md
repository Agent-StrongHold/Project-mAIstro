---
id: ADR-082526-3ca6
title: "The Container owns the delegation dependencies, and Hive resolves them at call time"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-25
accepted: 2026-08-25
substrate:
  - maistro-engine#ADR-082426-6201
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests:
  - packages/maistro-core/tests/test_container_delegation_wiring.py
  - packages/hive-conductor/backend/tests/test_dag_agents.py
ac-modules:
  AC-1: maistro.container
  AC-2: maistro.container
  AC-3: maistro.container
  AC-4: '@flat/hive-conductor/services.dag_agents'
  AC-5: '@flat/hive-conductor/services.dag_agents'
history:
  - status: Proposed
    date: 2026-08-25
  - status: Accepted
    date: 2026-08-25
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082526-3ca6: The Container owns the delegation dependencies

## Context

#147 asked for two things: delegated work becomes a canonical child Run, and
`build_node_resolver` produces a delegate node with its dependencies wired.
PR #192 delivered the first and left the second, deferring it as needing "a
canonical-abstraction decision". The strict audit reopened #147 for exactly
that gap. This is that decision.

The helper takes the dependencies:

```python
def build_node_resolver(
    *, harness_adapters=None, usage_log=None,
    a2a_delegator=None, guest_peers=None, run_store=None,
) -> Callable[[str, Any], Any]:
```

and the shipped path supplies none of them. `services/dag_agents.py` builds one
resolver at import time:

```python
_node_resolver = build_node_resolver()
```

Reproduced against that module on `eddfa64`:

```
node type: AgentDelegateRemoteNode
  _a2a_delegator       = None
  _guest_peers         = None
  _run_store           = None
```

So every delegation on the registered-DAG path refuses for want of a
delegator, and no delegated work can be filed as a child Run because the node
holds no canonical `RunStore`.

### Why it was left

The module's own comment gives the reason, and it is a real one: *"this app
imports maistro-core pieces directly rather than constructing a full
Container"*. At **import** time there is no Container to ask. That is true and
it is not the whole picture — by the time a DAG actually runs, Hive has one,
reached the same way `services/engine.py` already reaches `run_store` and
`task_admitter`.

### Why this is not #225 repeating itself

ADR-082426-6201 **retired** `Container.a2a_broker` because it was constructed,
stored, and read by nothing. Adding two more delegation fields to the Container
looks like the same move in reverse, so the distinction has to be stated rather
than assumed: `a2a_broker` had no reader anywhere, while these two have a named
one — `build_node_resolver`, called from the path that executes DAGs.

That is not a promise; it is checkable. `scripts/check-wiring-reads.py` (#236)
fails on a Container field nothing reads, so if this wiring is ever bypassed
again the field becomes a gate failure rather than a quiet `None`.

## Decision

**The Container constructs and owns `a2a_delegator` and `guest_peers`.** Both
are cheap and dependency-free — `A2ADelegator()` takes no arguments, and
`GuestPeerManager(audit=None)` defaults its own audit logger — so there is no
configuration decision hiding behind this and no reason to make them optional.

**Hive resolves its node resolver at call time, not import time.** A
module-level resolver built once cannot see a Container that does not exist
yet; a resolver built per execution can. Where there is no bridge the no-arg
resolver remains the fallback, so a Conductor running without maistro-core
behaves exactly as it does today rather than failing to start.

The canonical `run_store` travels the same way, and it is the canonical one:
`build_node_resolver`'s docstring already records that passing the durable
executor's `InMemoryDurableRunStore` type-checks and then raises
`AttributeError` on the first accepted delegation. Hive holds both. The
container's `run_store` is the one that goes here.

### What this does not do

- **It does not retire `A2ATask.TaskStatus`.** #147 puts that out of scope and
  it stays there; the receipt keeps its own status, it simply stops being the
  only record.
- **It does not register any peer.** `GuestPeerManager` starts empty. A
  cross-instance delegation still requires a peer to have been registered, and
  nothing here decides who does that or when.

## Consequences

### Positive
- The delegate node reaches production with a delegator, so a delegation
  refusing for want of one becomes a real absence rather than the default.
- Delegated work on the registered-DAG path can be filed as a canonical child
  Run, which is what #147's first half built and nothing could reach.
- The wiring is guarded: an unread Container field now fails a gate.

### Negative / Trade-offs
- Resolving per call costs a container lookup per execution. It is a getattr
  chain against an object Hive already holds, not a construction.
- Two more fields on a Container that is already wide. The alternative — a
  second factory that assembles delegation dependencies separately — splits
  "what does this deployment have" across two places, which is the drift
  `wire_execution_spine` exists to prevent.

### Neutral
- Cross-instance delegation remains untested end to end here, because it needs
  a registered peer and a remote. The in-process path is the one this closes.

## Acceptance criteria

Split by which module carries the behaviour. AC-1 through AC-3 are about the
Container; AC-4 and AC-5 are about Hive's registered-DAG path, so they annotate
`services.dag_agents` and are proven by
`packages/hive-conductor/backend/tests/test_dag_agents.py`.

That split used to cost them their rung. `check-ac-state.py` scans markers only
in the trees `[tool.pytest.ini_options].testpaths` names, and
`packages/hive-conductor/backend/tests` was not one of them — so a criterion
about the product this monorepo ships could not climb past `declared` however
well tested it was, and this document carried two `<!-- ac-state: unproven -->`
comments admitting it. #267 put the tree in `testpaths` and taught the gate to
run each root as its own pytest session, which is what the collision between
`maistro-core`'s `tests/config/` package and Hive's flat-layout `config` module
requires. The evidence was always there; nothing was measuring it.

- [x] **AC-1** The Container declares `a2a_delegator` and `guest_peers`, and
  both construct without configuration.
- [x] **AC-2** `build_node_resolver` hands all three to the delegate node when
  supplied, and still produces an unwired node when they are not — the fix
  belongs at the call site, not in a new default.
- [x] **AC-3** The `run_store` parameter is the canonical `RunStore` and stays
  distinguishable from the durable executor's store.


- [x] **AC-4** Hive's registered-DAG path resolves its node resolver from the
  Container, so the delegate node receives a delegator, a guest-peer manager
  and the canonical `RunStore`.
- [x] **AC-5** Without a bridge — or with an engine that raises — the path
  still resolves nodes via the no-arg resolver rather than failing.
