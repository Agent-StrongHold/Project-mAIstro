---
id: SPEC-082926-730d
title: Container Pool Ownership
repo: maistro-engine
kind: spec
status: AC Defined
created: 2026-08-29
accepted: 2026-08-29
history:
  - status: Proposed
    date: 2026-08-29
  - status: Accepted
    date: 2026-08-29
  - status: AC Defined
    date: 2026-08-29
substrate:
  - maistro-engine#ADR-082926-730d
implements:
  - maistro-engine#ADR-082926-730d
related:
  - maistro-engine#ADR-082226-5104
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/test_container_pool_ownership.py
source:
  - packages/maistro-core/src/maistro/container.py
ac-modules:
  AC-1: maistro.container
  AC-2: maistro.container
  AC-3: maistro.container
  AC-4: maistro.container
  AC-5: maistro.persistence
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-082926-730d: Container Pool Ownership

- **Status:** Active
- **Decision:** ADR-082926-730d
- **Closes:** #335

## Scope

`create_container`'s PostgreSQL branch, the `pg_pool` parameter, the pool
registry in `maistro.persistence`, and the container's shutdown.

Out of scope: which store each backend selects — that split is #122's contract
and does not change — and the SQLite branch, which holds a connection rather
than a pool.

## Precedence

| given | pool used | taken from the registry | released by `aclose()` |
|---|---|---|---|
| `pg_pool` only | the supplied pool | no | no |
| `postgresql://` URL only | the pool for that DSN | yes | yes |
| both | the supplied pool | **no** | no |
| neither | none | no | no |

*Released*, not closed: the registry owns the pool and may have handed the same
object to another container built from the same DSN. It closes when the last
holder lets go.

A supplied pool wins because a caller naming a concrete pool is more specific
than a string naming a server. It wins *before* the URL branch runs, so the
second pool is never opened rather than opened and discarded.

## The registry

`get_pool(dsn)` returns the pool for that DSN, creating it once, and records a
**user**. Two DSNs get two pools.

`release_pool(pool)` drops one user and closes the pool when the count reaches
zero — the ordinary path, and the one a container takes.

`close_pool(dsn)` closes one unconditionally; `close_pool()` closes all. These
are the teardown form: test teardown and a failed preflight both need the pool
gone regardless of who still holds a reference. `close_pool()` attempts every
close before raising, because it empties the registry first and an early return
would leave the remainder open *and* unreachable.

## Acceptance Criteria

```gherkin
Feature: Container pool ownership

  @AC-1
  Scenario: A supplied pool prevents a second pool for the same database
    Given a PostgreSQL database_url and a supplied pool
    When the container is built
    Then no pool is created
    And every PostgreSQL-backed store holds the supplied pool

  @AC-1
  Scenario: A URL with no supplied pool opens exactly one
    Given a PostgreSQL database_url and no supplied pool
    When the container is built
    Then exactly one pool is created

  @AC-1
  Scenario: One DSN yields one pool however many callers ask
    Given an empty registry
    When two callers ask for the same DSN
    Then they receive the same pool
    And exactly one pool was created

  @AC-2
  Scenario: The container holds only the pool it took from the registry
    Given a container built from a URL
    When what it holds is read
    Then it reports holding the pool

  @AC-2
  Scenario: A supplied pool is not held
    Given a container built with a supplied pool
    When what it holds is read
    Then it reports holding no pool

  @AC-3
  Scenario: Closing the container releases the pool it took
    Given a container that took its pool from the registry
    When it is closed
    Then that pool is closed

  @AC-3
  Scenario: The pool survives until the last holder lets go
    Given two containers built from the same DSN, holding the same pool
    When the first is closed
    Then the pool is still open
    And when the second is closed the pool is closed and forgotten

  @AC-3
  Scenario: Releasing a pool the registry never handed out is a no-op
    Given a pool that is not registered
    When it is released
    Then nothing is closed and nothing is raised

  @AC-3
  Scenario: Closing the container leaves a supplied pool open
    Given a container built with a supplied pool
    When it is closed
    Then the supplied pool is still open

  @AC-4
  Scenario: Every pool is closed even when one close fails
    Given two registered pools, the first of which refuses to close
    When every pool is closed
    Then both were closed
    And the failure is raised afterwards, carrying every failure

  @AC-3
  Scenario: Closing twice closes once
    Given a container that has been closed
    When it is closed again
    Then the pool is not closed a second time

  @AC-3
  Scenario: A close that raises does not abandon the rest of the shutdown
    Given a pool whose close raises
    When the container is closed
    Then the failure is reported and the container is still marked closed

  @AC-4
  Scenario: A failed preflight leaves no pool behind
    Given a database whose preflight check fails
    When the container is built
    Then it raises
    And no pool is left open

  @AC-4
  Scenario: A failed preflight against a supplied pool does not close it
    Given a supplied pool and a preflight that fails
    When the container is built
    Then it raises
    And the supplied pool is still open

  @AC-5
  Scenario: Two databases get two pools
    Given two different DSNs
    When a pool is asked for each
    Then they are different pools

  @AC-5
  Scenario: One database gets one pool
    Given the same DSN twice
    When a pool is asked for each
    Then they are the same pool

  @AC-5
  Scenario: Closing one database's pool leaves the other's open
    Given two open pools
    When one is closed by DSN
    Then the other is still open
    And asking for the closed one again opens a new pool
```
