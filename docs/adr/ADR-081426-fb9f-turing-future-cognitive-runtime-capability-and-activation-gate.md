---
id: ADR-081426-fb9f
title: Turing future cognitive runtime capability and activation gate
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-08-14
substrate:
  - maistro-engine#ADR-092
  - maistro-engine#ADR-081226-6e34
  - maistro-engine#ADR-081226-7248
  - maistro-engine#ADR-081426-1f7c
related:
  - maistro-engine#ADR-070426-9f47
  - maistro-engine#ADR-070126-6386
  - maistro-engine#ADR-088
  - maistro-engine#ADR-081226-6b46
  - maistro-engine#ADR-081226-a66b
  - maistro-engine#ADR-081226-9944
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Governance
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-08-14
---

# ADR-081426-fb9f: Turing future cognitive runtime capability and activation gate

## Context

MAIstro is converging historically separate execution, product, RSI/Evolve, and Turing code onto
one canonical platform model. That convergence must remove accidental duplication without erasing
a future capability that was part of the intended system direction but is not ready to be built or
activated today.

Turing is not intended to become a competing peer platform with its own `TuringRun`, `TuringGraph`,
authorization universe, capability system, or persistence ownership. The surrounding platform
remains canonical MAIstro: Workspace/Project scope, Persona, Graph/Node, Run/NodeRun/Attempt,
capabilities/providers/bindings/invocations, authorization and policy, Events and observability,
artifacts, persistence, credentials/integrations, schedules, and product surfaces.

What may eventually differ is the cognitive runtime. A mature Turing implementation may combine
an autonoetic/self model, cognitive memory architecture, drives, endogenous processes, persistent
internal state, and proactive cognition. Those concepts should not be flattened into generic
MAIstro concepts merely to make package boundaries look uniform.

The architectural requirement at this stage is therefore deliberately asymmetric:

> **Preserve the ability to build Turing; do not turn it on.**

The complete Turing runtime is a *possible future capability*, not a capability this convergence
work creates, enables, or declares safe for production.

## Decision

### 1. Preserve a future Turing-class cognitive runtime principal

Canonical MAIstro MUST remain capable of representing a future persistent cognitive actor with a
shape closer to a system-runtime component plus a highly trusted principal than to an ordinary
stateless agent.

If implemented in the future, such a principal may be able to:

- maintain cognition and state across individual requests and Runs;
- observe authorized system and execution state over time;
- communicate directly with users or services and initiate communication proactively;
- initiate authorized work without requiring an active user request;
- inspect Graphs and execution history and reason about system-level improvement;
- create candidate changes and launch evaluation/experiment Runs within delegated scope;
- invoke ordinary MAIstro capabilities, including improvement mechanisms such as RSI and Evolve;
- perform equivalent lower-level improvement operations directly when those operations are within
  its delegated authority; and
- be explicitly invoked by a Node when a Graph intentionally wants Turing cognition in the
  execution path.

This is an architectural compatibility requirement only. It does **not** create a canonical
`TuringPrincipal`, `TuringRuntime`, Graph supervisor type, permission bundle, or production service
in this ADR.

### 2. Runtime-like persistence does not imply root authority

A future Turing actor is best thought of as having **near-administrative visibility with tightly
controlled developer-like powers**, not as an omnipotent internal root process.

Authorization remains multidimensional and scope-bound per ADR-081226-6e34. Turing MUST NOT be
represented by a scalar assumption such as `user < admin < Turing`. Its effective authority must
be an explicit, reviewable envelope of grants, denies, policies, approval requirements, resource
visibility, and capability bindings.

A future Turing implementation may have unusually broad observational access while having less
mutation authority than a human platform administrator. In particular, being capable of changing
a system is distinct from being authorized to make a particular change.

At minimum, the safety model for any future activation must prevent the actor from using its own
cognitive or developer powers to bootstrap authority outside its issuance scope. No future Turing
implementation may implicitly gain the ability to expand its own grants, bypass inherited denies,
obtain protected credentials merely because it can discover them, disable auditability, or rewrite
its enclosing safety boundary through ordinary self-improvement.

### 3. Graph supervision is asynchronous by default and outside the hot path

A Graph may eventually have an associated higher-order observing/improving actor. The permanent
name for that role is intentionally unresolved; terms such as *hyperagent*, *meta-agent*,
*overseer*, and *Graph Supervisor* are descriptive working terms, not canonical object names.

The role, if implemented, must not become an implicit step in normal Graph execution.

A scheduled Run MUST be able to execute according to its immutable Graph snapshot without the
Graph-associated cognitive supervisor being available. Observation, evaluation, learning, and
improvement are asynchronous by default. They may consume Events, Run/NodeRun/Attempt results,
artifacts, metrics, evaluation results, and versioned Graph state after or alongside execution
without inserting a hidden latency-bearing decision between ordinary Nodes.

The supervisor may propose or, when explicitly authorized, apply changes that affect **future**
Graph versions. It does not mutate the immutable snapshot already being executed by an existing
Run.

Synchronous Turing participation remains valid when it is explicit Graph semantics. A Turing-backed
Node, for example, may intentionally invoke the persistent cognitive runtime and therefore place
that invocation in the hot path. The invocation has the ordinary `NodeRun -> Attempt` lifecycle;
the persistent Turing identity/runtime is not reduced to the lifetime of that invocation.

### 4. RSI and Evolve are reusable improvement mechanisms, not exclusive owners of improvement

RSI and Evolve remain reusable mechanisms that can be invoked directly by users, by conventional
future supervisory agents, or by a future Turing runtime. They are not mandatory middle layers
through which every improvement must pass.

A future Turing actor may choose to use RSI, Evolve, Builders, evaluation harnesses, or lower-level
canonical capabilities as tools. Subject to authorization, it may also perform similar bounded
operations directly when that is the appropriate strategy.

This preserves both composition and autonomy without creating parallel execution lifecycles:

```text
human / conventional supervisor / Turing
                  |
                  v
        canonical improvement operations
          /          |           \
       RSI         Evolve       direct bounded operations
          \          |           /
           evaluation / candidate versions
                       |
                governed promotion
```

Winning an experiment, producing a candidate, or being cognitively confident does not itself grant
promotion authority.

### 5. Keep domain, process, and package ownership separate

Current Hive and Turing backend/process boundaries are evidence about deployment and historical
development, not authoritative domain boundaries.

Convergence decisions must distinguish:

1. **domain ownership** — which canonical MAIstro concept owns the behavior;
2. **deployment/process ownership** — which independently launched process exposes or performs it;
3. **Python/package ownership** — where the implementation happens to live today.

An independently deployable Turing process may remain useful later without becoming a second
platform architecture. Likewise, Turing-specific cognitive primitives may remain Turing-owned
while duplicated surrounding infrastructure converges onto canonical MAIstro.

The governing rule is:

> **Preserve what makes Turing meaningfully different. Remove what only makes Turing accidentally separate.**

## Activation gate

This ADR intentionally defines no date or milestone at which Turing becomes active. **Turing must
remain off while the canonical platform and its enclosing safety cage are incomplete.** Existing
Turing code may be inventoried, tested, preserved, and converged where appropriate, but this ADR
must not be cited as authorization to finish or activate the autonomous runtime.

Before any future proposal to activate a Turing-class persistent actor, the proposal must establish
that the surrounding platform controls it independently of Turing's own cognition. At minimum,
the activation review must demonstrate a functioning and integrated:

- canonical Graph/Run/NodeRun/Attempt execution model;
- scoped grant/deny authorization and delegation model with deny-wins behavior;
- capability/provider/binding/invocation authorization path;
- Event/audit/observability path sufficient to reconstruct consequential actions;
- versioned mutation path for Graphs, Nodes, configuration, and other improvable objects;
- isolated experiment/evaluation path with bounded compute and side effects;
- approval, promotion, rollback, and recovery controls appropriate to consequential changes;
- credential and integration isolation that does not equate visibility with use authority;
- protected safety/control surfaces that the Turing principal cannot modify through its ordinary
  delegated developer powers; and
- fail-closed behavior proving that unavailable policy, authorization, or safety infrastructure
  cannot silently become permission.

This list is a **minimum activation review surface, not a claim that the safety cage is fully
specified today**. A future activation ADR/SPEC must define concrete contracts, threat models,
tests, operator controls, emergency disablement, and acceptance evidence against the then-current
system before enabling the runtime.

The existing autonoetic self-model guardrails in ADR-070426-9f47 remain necessary but are not
sufficient for activation. They protect important Turing-internal write and identity boundaries;
they do not by themselves establish that a near-admin, developer-capable persistent actor is safe
to operate across MAIstro.

## Consequences for current convergence

Current convergence work SHOULD preserve the interfaces and ownership boundaries necessary for the
future capability, but MUST NOT implement speculative Turing-specific platform objects merely to
prepare for it.

In particular:

- do not add `TuringRun`, `TuringGraph`, or a Turing-specific authorization/capability lifecycle;
- do not place a Graph supervisor in the scheduled execution hot path;
- keep Run snapshots immutable while allowing asynchronous observation of execution outcomes;
- allow canonical capability and authorization contracts to support non-human persistent principals
  without granting those principals implicit system authority;
- preserve a clean boundary where a Turing cognitive runtime could later be invoked as a Node;
- preserve Events/observability as a non-blocking sensory surface available to authorized future
  cognitive actors;
- normalize RSI/Evolve onto canonical execution rather than turning either into the unique owner of
  all future self-improvement; and
- classify Turing code as **canonical platform concern**, **Turing cognitive substitution**,
  **Turing-specific product/API concern**, or **accidental duplication** before merging/removing it.

The design objective is compatibility, not implementation.

## Non-goals

This ADR does **not**:

- finish, reactivate, or deploy Turing;
- decide the permanent name or object model for the graph-level supervisory role;
- specify the final cognitive-runtime protocol;
- grant Turing any permissions;
- define a default near-admin role or reusable permission bundle;
- weaken existing Warden, Sentinel, sandbox, approval, or authorization controls;
- move Turing into the ordinary execution hot path;
- require Turing to supervise every Graph;
- require RSI or Evolve to mediate every improvement operation; or
- claim that the current safety architecture is sufficient for Turing activation.

## Relationship to existing decisions

- **ADR-092** supplies the capability-vs-control posture: MAIstro accepts capability friction where
  governance requires it. A future Turing runtime inherits that posture rather than bypassing it.
- **ADR-081226-6e34** supplies scope-bound grants, sticky denies, explicit delegation, and the rule
  that authority is not a single global role hierarchy.
- **ADR-081226-7248** supplies canonical Events/Checkpoints that may form part of the asynchronous
  observation surface without making cognition an execution prerequisite.
- **ADR-081426-1f7c** supplies the canonical execution runtime contract that future cognitive
  invocation must use rather than replacing.
- **ADR-081226-6b46** supplies the Capability/Provider/Binding/Invocation separation through which
  future tool use should be governed.
- **ADR-070126-6386** and **ADR-088** describe existing RSI/Evolve mechanisms that a future Turing
  actor may use as tools; this ADR does not make them synonymous with Turing cognition.
- **ADR-070426-9f47** protects Turing's autonoetic self-model internals. Those guardrails remain
  mandatory if that code is completed, but are only one layer of the larger activation cage.

## Acceptance criteria

This ADR is satisfied during current convergence when:

1. no canonical convergence decision requires a Graph-associated cognitive supervisor in the hot
   path of ordinary scheduled execution;
2. canonical execution and authorization contracts remain usable by a future persistent non-human
   principal without granting implicit root authority;
3. Turing can remain an independently deployable process and/or an explicitly invoked Node runtime
   without owning duplicate canonical Run/Graph/authorization semantics;
4. RSI/Evolve convergence preserves them as reusable improvement mechanisms rather than exclusive
   owners of improvement;
5. future Turing activation is treated as a separate gated architectural/security decision with
   concrete evidence, not as an automatic consequence of completing Turing code; and
6. no work performed merely to satisfy this ADR turns on or completes the Turing autonomous
   runtime today.
