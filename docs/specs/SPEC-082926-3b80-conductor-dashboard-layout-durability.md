---
id: SPEC-082926-3b80
title: Conductor Dashboard Layout Durability
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
  - maistro-engine#ADR-082926-3b80
implements:
  - maistro-engine#ADR-082926-3b80
related:
  - maistro-engine#ADR-078
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/hive-conductor/backend/tests/test_dashboard_layout.py
source:
  - packages/hive-conductor/backend/services/dashboard_layouts.py
ac-modules:
  AC-1: dashboard_layouts
  AC-2: dashboard_layouts
  AC-3: dashboard_layouts
  AC-4: dashboard_layouts
  AC-5: dashboard_layouts
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-082926-3b80: Conductor Dashboard Layout Durability

- **Status:** Active
- **Decision:** ADR-082926-3b80
- **Closes:** #340

## Scope

`GET`/`PUT /v1/dashboard/layout`, the record they read and write, and where it
is stored.

Out of scope: what a widget may contain — `services/dashboard_safety.py` owns
that and is unchanged — and the read-only `/v1/dashboard/demos`,
`/widget-examples` and `/deck-templates` routes, which serve files shipped in
the image and are not user state.

## The record

One entry per principal in the `dashboard_layouts` store:

```json
{
  "schema_version": 1,
  "revision": 4,
  "updated_at": "2026-08-29T10:00:00Z",
  "layout": { "widgets": [], "tabs": [], "activeTab": 0 }
}
```

`revision` counts saves that landed. `layout` is what
`sanitize_dashboard_layout` returned, never what the request sent.

## Where it lives

`stores.dashboard_layouts`, a `JsonStore` like `sessions` and `dags`, so it is
written through whatever `PersistedStore` the deployment configured — SQLite
under `CONDUCTOR_STATE_DB`, or PostgreSQL. One key per principal, one upsert per
save.

## Acceptance Criteria

```gherkin
Feature: Conductor dashboard layout durability

  @AC-1
  Scenario: A saved layout survives a restart
    Given a layout saved through the API against a real store on disk
    When the store is closed and reopened
    Then the layout is still there

  @AC-1
  Scenario: The layout is not written beside the code
    Given the shipped route module
    When it is inspected
    Then it names no path inside the backend package to write layouts to

  @AC-2
  Scenario: A write that does not land is not reported as success
    Given a store whose writes are refused
    When a layout is saved
    Then the request fails with 503
    And the response says the layout was not persisted

  @AC-2
  Scenario: A write that does not read back is not reported as success
    Given a store that accepts a write and returns something else
    When a layout is saved
    Then the save raises rather than returning

  @AC-2
  Scenario: The route does not catch its own persistence failure
    Given the save call in the route module
    When the module's syntax tree is walked
    Then no broad exception handler encloses it

  @AC-3
  Scenario: One principal cannot read another's layout
    Given two principals that have each saved a different layout
    When each reads its own
    Then each gets its own

  @AC-3
  Scenario: A request with no principal is refused rather than pooled
    Given a request that reached the route with no authenticated user
    When the layout is read
    Then the request fails with 401
    And no shared fallback identity is used

  @AC-4
  Scenario: A stale expected revision is refused
    Given a layout saved twice
    When a save carries the first revision as its expectation
    Then it fails with 409 and reports the current revision

  @AC-4
  Scenario: A matching expected revision is accepted
    Given a layout at a known revision
    When a save carries that revision
    Then it succeeds and the revision advances

  @AC-4
  Scenario: A save without an expectation is last-write-wins
    Given two saves with no expected revision
    When both are applied
    Then the second is what is stored

  @AC-5
  Scenario: A read does not depend on a write succeeding
    Given a principal with a preset and a store whose writes are refused
    When the layout is read
    Then the preset is returned rather than an error

  @AC-5
  Scenario: The revision is reported to the client that saved
    Given a successful save
    When the response is read
    Then it carries the revision the save produced
```
