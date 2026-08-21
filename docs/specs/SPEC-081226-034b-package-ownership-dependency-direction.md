---
id: SPEC-081226-034b
title: Package Ownership and Dependency Direction
repo: maistro-engine
kind: spec
status: AC Defined
created: 2026-08-12
history:
  - status: Proposed
    date: 2026-08-12
  - status: Accepted
    date: 2026-08-12
  - status: AC Defined
    date: 2026-08-12
substrate:
  - maistro-engine#ADR-081226-034b
implements:
  - maistro-engine#ADR-081226-034b
related: []
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
source:
  - packages
ac-modules:
  AC-3: maistro.runs.service
  AC-4: maistro.runs.service
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-081226-034b: Package Ownership and Dependency Direction

- **Status:** Active
- **Date:** 2026-08-12
- **ADR:** `ADR-081226-034b`

## Canonical package roles

| Package | Canonical role |
|---|---|
| `maistro-core` | reusable domain semantics and generic platform mechanisms |
| `maistro-server` | generic API/application transport adapter |
| `hive-conductor` | Hive product/application |
| `maistro-canvas` | Canvas/composition + book-product domain/surfaces |
| `maistro-design` | design domain/skills/systems/rendering adapters |
| `maistro-turing` | cognition/self-model/persona-agent extensions |
| `maistro-evolve` | optimization/evaluation domain |
| `maistro-rsi` | recursive self-improvement domain/surface |
| `maistro-bootstrap` | installation/materialization/setup lifecycle |
| `maistro-arch-governance` | target identity for architecture/spec governance tooling |

## Requirements

1. `maistro-core` MUST NOT import product/application packages to implement canonical domain semantics.
2. Specialized packages MUST integrate execution through canonical Graph/Node/Run/Binding contracts rather than redefine universal lifecycle models.
3. `maistro-server` routes MUST delegate durable domain/execution work to canonical services once those services exist.
4. Hive duplicate lifecycle/orchestration paths MUST become adapters and be removed only after parity/reachability tests.
5. ExecutionRuntime MUST NOT import graph traversal/domain modules to decide readiness/predicates/policy.
6. Specialized NodeTypes/providers SHOULD register through public extension contracts rather than reverse imports from core.
7. `maistro-bootstrap` user-work execution responsibilities MUST be inventoried and migrated where they overlap canonical runtime/Builders/capability ownership.
8. The current `maistro-registry` physical rename MUST be isolated and MUST update package path, Python import, CLI, root workspace/source metadata, lockfile, tests and docs together.
9. Architecture governance tooling MUST remain outside the product Run ontology unless deliberately invoked as an ordinary user-work capability.
10. Package-specific event/lifecycle models on migrated paths MUST carry canonical IDs and cannot become competing authorities.
11. Dependency cycles across core/product/specialized packages MUST be rejected or explicitly waived with architecture rationale.

## Architecture fitness rules to implement

At minimum CI SHOULD enforce:

- core cannot import outward product packages;
- Runtime cannot import graph/domain traversal semantics;
- scheduler code cannot execute admitted workload directly instead of creating a Run;
- NodeType executors cannot own Run persistence;
- UI/server application code cannot invoke provider implementation directly on migrated paths;
- credentials/secrets cannot live in Graph/Node definitions;
- Binding cannot widen parent permissions;
- migrated package events carry canonical Workspace/Run correlation.

## Acceptance Criteria

```gherkin
Feature: Package ownership and dependency direction

  @AC-1
  Scenario: Core does not import application packages
    Given the maistro-core source
    When its imports are analysed
    Then it imports no Hive, Canvas, Design, Turing, RSI, Evolve or server application code

  @AC-2
  Scenario: A specialized package extends core without core knowing
    Given a specialized package
    When it registers a NodeType or Provider through the public contract
    Then it is usable
    And core does not import that package

  @AC-3
  Scenario: A migrated route reaches the canonical service
    Given a migrated server route
    When it handles a request
    Then it reaches the canonical Workspace and Run service
    And it constructs no private lifecycle record

  @AC-4
  Scenario: Hive and generic paths produce identical history
    Given the same workload
    When it runs through the Hive migrated path and through the generic server path
    Then both produce the same canonical Run and Event history

  @AC-5
  Scenario: Graph readiness logic cannot move into the runtime
    Given the runtime import fitness test
    When graph predicate or readiness logic is added to maistro.runtime
    Then the test fails

  @AC-6
  Scenario Outline: Every bootstrap area has an explicit disposition
    Given the bootstrap audit
    When <area> is reviewed
    Then it carries an explicit keep or migrate disposition

    Examples:
      | area           |
      | agent loop     |
      | model selector |
      | sandbox        |
      | session        |
      | delivery       |
      | credentials    |

  @AC-7
  Scenario: The registry rename lands atomically
    Given the maistro-registry to maistro-arch-governance migration
    When the migration commit is executed
    Then it regenerates the lockfile
    And package CLI and import tests pass before the old paths are removed

  @AC-8
  Scenario: CI fails on a deliberately forbidden dependency
    Given architecture fitness CI
    When a forbidden dependency or lifecycle fixture is introduced on purpose
    Then CI fails

  @AC-9
  Scenario: Migration shrinks the reachability baseline
    Given duplicated product orchestration
    When it is migrated or removed
    Then the reachability baseline decreases

  @AC-10
  Scenario: Consolidation does not cost domain behavior
    Given a specialized package with valid domain behavior
    When packages are consolidated
    Then that behavior is preserved rather than dropped to reduce package count
```

## Non-goals

This SPEC does not require immediate physical package moves, prohibit all optional dependencies in application layers, or force specialized domain assets into `maistro-core`.
