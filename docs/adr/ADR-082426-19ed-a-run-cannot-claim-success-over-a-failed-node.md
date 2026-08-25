---
id: ADR-082426-19ed
title: "A Run cannot claim success over a node that failed"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-24
accepted: 2026-08-24
history:
  - status: Proposed
    date: 2026-08-24
  - status: Accepted
    date: 2026-08-24
substrate:
  - maistro-engine#ADR-081226-a66b
implements: []
related:
  - maistro-engine#ADR-082426-a47f
  - maistro-engine#ADR-082426-f170
  - maistro-engine#ADR-082426-e3ff
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/runs/test_spine_conformance.py
ac-modules:
  AC-1: maistro.runs.lifecycle
  AC-2: maistro.runs.lifecycle
  AC-3: maistro.runs.lifecycle
layer: Reliability
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082426-19ed: A Run cannot claim success over a node that failed

## Context

#43's second acceptance criterion is *Run terminal state derives correctly from NodeRun
outcomes*. #233 closed the cancellation half and left this open.

No derivation existed. `runs/lifecycle.py` exported `transition_run`, `transition_node_run`,
`transition_attempt` and ADR-082426-a47f's cascade — nothing that read NodeRun outcomes to
decide a Run's status. Every domain computed the Run's terminal status from **its own
receipt** and asserted it:

| Domain | Site | Where the status came from |
|---|---|---|
| Chat | `container.py::_terminalize` | `FAILED if error is not None else COMPLETED` |
| Tasks | `tasks/admission.py` | `RUN_STATUS_BY_TASK_STATUS[status]` |
| Durable graph | `graph/durable_runs/executor.py` | the executor's own control flow |

So the spine recorded logical node outcomes and nothing read them back. Reproduced with no
race required — two nodes, one fails, the domain asserts success anyway:

```
Run terminal   = completed  result={'ok': True} error=None
NodeRun states = {'a': 'failed', 'b': 'completed'}
```

That is also #43's *fourth* criterion — *recovery cannot produce impossible terminal
combinations* — failing from the ordinary path rather than from recovery.

## Decision

**A Run may not transition to COMPLETED while the latest NodeRun for any of its nodes is
terminal and not COMPLETED.** `UnearnedRunCompletion` names the node, the NodeRun and the
status it actually holds. Enforced in all three stores, inside the same lock or transaction
that writes the Run.

Three narrowings, each load-bearing.

**1. The rule is a guard, not a derivation.** The domains keep asserting the status and keep
supplying `result`/`error`. A derivation — the spine computing the Run's status from the fold
— would have to overrule them, and it would be wrong to: ADR-082426-f170 established that a
*requested cancellation* is CANCELLED rather than a parked failure, and that fact lives in the
domain's receipt, not in any NodeRun. A Run cancelled while every node it ran succeeded is
correct and common. So the spine's job here is to refuse a contradiction, not to author the
answer.

**2. Only COMPLETED is checked. Success is the only claim that has to be earned.** FAILED,
CANCELLED and TIMED_OUT may all stand over nodes that each completed, because those outcomes
come from outside any node — a caller cancelled, a deadline expired, the fold between nodes
raised. Refusing them would leave a domain unable to report what actually happened, which is
a worse failure than the one this fixes.

**3. Only *terminal* latest NodeRuns are consulted.** A latest NodeRun still open is
ADR-082426-a47f's case: that ADR decided such a node is cascaded to CANCELLED by the very
transition being validated here. This ADR does not reopen it. A graph may abandon a node whose
result it no longer needs, and a first-wins race is a real pattern rather than a bug.

### The newest NodeRun per node, not every NodeRun

A node can hold more than one NodeRun. A **retry** is a new Attempt under the same NodeRun,
but a **re-execution** — a cycle, a resumed frontier — calls `execute_node` again and gets a
new NodeRun with a higher ordinal for the same `node_id`. Verified:

```
NodeRuns for node 'a': [(1, 'failed'), (2, 'completed')]
```

That is a node that failed and then succeeded, and its Run is legitimately COMPLETED. Folding
every NodeRun would make "this node failed once" permanently fatal to its Run and break every
retry-after-failure path in the repository.

This is the same rule ADR-082426-e3ff needed one level down, where the newest **Attempt** per
NodeRun is the one that may commit. Two levels of the spine, one rule: the newest record for
an identity is the one that counts.

A node with no NodeRun at all is not consulted — a Graph node that never ran is the ordinary
outcome of a conditional branch, not a missing result.

## Acceptance Criteria

Each rule is asserted twice from one helper: a `spine`-parameterized test carrying the
all-three-stores claim in CI's postgres legs, and a `memory_spine` test carrying the
criterion where no database is configured. `scripts/ac_outcome_plugin.py` counts a skip as no
evidence, and the Quality gate job configures no database, so a criterion marked on `spine`
alone would sit at `covered` however green CI was.

- [x] **AC-1**: A Run whose latest NodeRun for some node is FAILED cannot transition to
  COMPLETED. The error names the node and its status, and the refused transition leaves the
  Run and its result untouched.
- [x] **AC-2**: The asymmetry holds. The same Run may terminalize as FAILED, and a Run whose
  nodes all completed may still be CANCELLED — the outcome that came from outside the nodes
  survives.
- [x] **AC-3**: A node that failed and was then re-executed successfully does not condemn its
  Run: only the highest-ordinal NodeRun for a node is consulted.

## Consequences

### Positive

- The combination #43's fourth criterion calls impossible is now refused at the store, in all
  three implementations, rather than described in prose.
- The three domains keep their receipts. Nothing had to change in `container.py`,
  `tasks/admission.py` or the graph executor — 7,374 core tests pass unmodified, which is the
  evidence that the rule matches what the system already believed rather than imposing a new
  belief on it.

### Negative / Trade-offs

- **The residual is real and stated rather than hidden:** a Run can still complete over a node
  it cancelled in the same breath, because ADR-082426-a47f's cascade fires on the same
  transition. Whether *that* should be refused is a separate decision about speculative and
  abandoned nodes, and refusing it here would have overturned an accepted ADR as a side effect
  of fixing a different defect.
- `graph/durable_runs/executor.py` calls the **pure** `transition_run` on its own record and
  is not guarded by this. That is the same shape ADR-082426-e3ff found at the acceptance
  boundary: the durable fold holds its own record with its own concurrency control. Converging
  it is #44's.
- The check costs one read of a Run's NodeRuns per terminal transition. In PostgreSQL it runs
  inside the Run's own transaction with the row already locked, so it adds no round trip
  against a snapshot another writer could have moved.

### Neutral

- `latest_node_runs` is exported. It is the fold #43's criterion asks for, and a future
  derivation — if one is ever wanted — would build on it rather than re-deriving the
  ordinal rule a third time.
