# MAIstro ADR Agent Index

This directory is the progressive-disclosure entry point for architecture work.

## How to use it

1. Start here for the canonical architecture map.
2. Open only the category relevant to the work.
3. Read that category's short ADR entries: **Status**, **Next steps**, and **Current state**.
4. Open the linked canonical ADR only when its full rationale, invariants, history, or acceptance criteria are needed.
5. Before changing architecture, search for newer date/hash ADRs that amend an older sequential ADR. Newer decisions frequently record convergence discovered after the original design.

The category indexes cover every decision file in `docs/adr/`. `ADR-000-template.md` and `ADR-INDEX.md` are repository infrastructure rather than decisions.

## Canonical architecture first

For execution/ownership questions, begin with these current decisions rather than older Task/Recipe/GraphRun-era records:

- **Product ownership:** ADR-081226-9944, Canonical Product Hierarchy and Ownership.
- **Project scope:** ADR-081426-b1d3, Project Scope Tree.
- **Authorization:** ADR-081226-6e34, Scoped Grants and Deny-Wins Authorization.
- **Graph semantics:** ADR-081226-69ee, Graph and Node Execution Model.
- **Execution lifecycle:** ADR-081226-a66b, Run → NodeRun → Attempt.
- **Physical mechanics:** ADR-081426-1f7c, ExecutionRuntime Contract.
- **Fulfillment/effects:** ADR-081226-6b46, Capability → Provider → Binding → Invocation.
- **Durable history/recovery:** ADR-081226-7248, Event and Checkpoint Model.
- **Reusable definitions:** ADR-081226-bb3a, Template/Object/Provenance Semantics.
- **Persona:** ADR-081226-e626, Persona and Product Surface Model.
- **Package ownership:** ADR-081226-034b, Package Ownership and Dependency Direction.
- **Server/product boundary:** ADR-096 plus ADR-082426-2192.
- **Repository merge boundary:** ADR-095.

## Pre-1.0 rule

MAIstro is pre-1.0 and beta deployments are rebuilt from scratch. Do **not** preserve obsolete architecture merely for backward compatibility.

Default migration posture:

```text
build canonical model
→ move useful behavior
→ change real callers
→ delete obsolete system
```

Parity tests protect useful behavior. They do not justify permanent compatibility facades.

This rule is especially important when reading older ADRs about API version preservation, expand/contract database migrations, runtime hot-swap compatibility, legacy task/recipe lifecycles, or dual execution paths.

## Category indexes

- [Agent architecture](agent-architecture/README.md)
- [API and interfaces](api-interfaces/README.md)
- [Bootstrap and installation](bootstrap-installation/README.md)
- [Canvas and design abilities](canvas/README.md)
- [Connectivity and deployment](connectivity-deployment/README.md)
- [Core runtime and foundation](core-runtime/README.md)
- [Crypto and payments](crypto-payments/README.md)
- [Design](design/README.md)
- [Development and repository governance](development-repository/README.md)
- [Evolve / RSI](evolve/README.md)
- [Memory](memory/README.md)
- [Observability](observability/README.md)
- [Orchestration](orchestration/README.md)
- [Reliability](reliability/README.md)
- [Security and identity](security-identity/README.md)
- [Tools and capabilities](tools/README.md)

## Reading status correctly

Canonical lifecycle status remains the status in the ADR front matter. The category index adds current interpretation without rewriting history.

In particular, **Accepted** can mean:
- current architectural policy that remains continuously authoritative;
- a finite decision whose implementation is incomplete;
- an older accepted decision that now needs a successor before it can legally become Superseded.

Use **Next steps** to distinguish those cases.

A code path, test suite, or module existing is not enough for `Implemented`. Evidence must prove the acceptance contract and production reachability where the decision claims a runtime path.

## Collision warning

The repository contains 199 ADR decision files but substantially fewer unique legacy sequential IDs because early concurrent work produced collisions. Date/hash IDs were introduced to stop new collisions.

Therefore:
- resolve ADRs by **exact filename/link**, not numeric ID alone;
- do not assume `ADR-061` identifies one file without checking;
- when duplicate decisions describe the same architecture, converge them onto one canonical successor rather than allowing two sources of truth.

## High-priority successor/rewrite themes found by the audit

- Retire Task/TaskRunner, GraphRun, Builders-owned lifecycle, Recipe execution, and Hive-owned execution in favor of the canonical Run spine.
- Rewrite old identity/DID/VC assumptions around canonical principals, Workspace/Project grants, current session security, and the newer crypto-bound approval decision.
- Converge tools, MCP, model providers, renderers, sandboxes, foreign harnesses, credentials, and external effects onto Provider/Binding/Invocation.
- Replace pre-1.0 compatibility ADRs for HTTP API version preservation and expand/contract schema migration.
- Correct ADR-091's context-budget rule so protected memories cannot exceed a model's physical context limit.
- Finish reachability/evidence reconciliation for ADRs that were rolled back from Implemented during M0.
