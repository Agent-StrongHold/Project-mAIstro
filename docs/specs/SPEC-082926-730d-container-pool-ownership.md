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
  AC-1: container
  AC-2: container
  AC-3: container
  AC-4: container
  AC-5: persistence
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

| given | pool used | opened by the container | closed by `aclose()` |
|---|---|---|---|
| `pg_pool` only | the supplied pool | no | no |
| `postgresql://` URL only | the pool for that DSN | yes | yes |
| both | the supplied pool | **no** | no |
| neither | none | no | no |

A supplied pool wins because a caller naming a concrete pool is more specific
than a string naming a server. It wins *before* the URL branch runs, so the
second pool is never opened rather than opened and discarded.

## The registry

`get_pool(dsn)` returns the pool for that DSN, creating it once. Two DSNs get two
pools. `close_pool(dsn)` closes one and forgets it; `close_pool()` closes all.

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

  @AC-2
  Scenario: The container owns only the pool it opened
    Given a container built from a URL
    When its ownership is read
    Then it reports owning the pool

  @AC-2
  Scenario: A supplied pool is not owned
    Given a container built with a supplied pool
    When its ownership is read
    Then it reports owning no pool

  @AC-3
  Scenario: Closing the container closes the pool it opened
    Given a container that opened its own pool
    When it is closed
    Then that pool is closed

  @AC-3
  Scenario: Closing the container leaves a supplied pool open
    Given a container built with a supplied pool
    When it is closed
    Then the supplied pool is still open

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
