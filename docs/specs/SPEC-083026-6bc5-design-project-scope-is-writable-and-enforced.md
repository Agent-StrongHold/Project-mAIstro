---
id: SPEC-083026-6bc5
title: A design project's scope is writable on a clean database and enforced on every read
repo: maistro-engine
kind: spec
status: AC Defined
created: 2026-08-30
accepted: 2026-08-30
history:
  - status: Proposed
    date: 2026-08-30
  - status: Accepted
    date: 2026-08-30
  - status: AC Defined
    date: 2026-08-30
substrate:
  - maistro-engine#ADR-083026-cdcb
implements:
  - maistro-engine#ADR-083026-cdcb
related: []
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests:
  - packages/maistro-design/tests/test_project_scope.py
  - tests/migrations/test_migration_chain.py
source:
  - alembic/versions/024_design_project_scope.py
  - packages/maistro-design/src/maistro_design/stores.py
  - packages/hive-conductor/backend/routes/design.py
ac-modules:
  AC-2: 'maistro_design.stores'
  AC-3: 'maistro_design.stores'
  AC-4: 'maistro_design.stores'
  AC-5: 'maistro_design.stores'
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-083026-6bc5: A design project's scope is writable on a clean database and enforced on every read

## Context

`design_projects.org_id` and `team_id` were foreign keys to `orgs` and `teams`.
Migration 003 creates both tables — added by #177's repair so the chain would
stop rolling back — and nothing else in the repository ever writes a row to
either. Measured against `develop` at `31c6102`, on a database migrated to head:
`SELECT count(*) FROM orgs` is `0`, and the only `org_id` the Design Studio
supplies is rejected by `design_projects_org_id_fkey`.

Meanwhile the store's `get`, `update` and `delete` matched on project id alone,
so any authenticated caller could read, edit or delete another scope's project.
The constraint that could not be satisfied blocked every legitimate write; the
one that was missing let every illegitimate read through.

ADR-083026-cdcb records the decisions.

## Decision

`org` and `team` are **soft scope identifiers**, as ADR-068 and every other
table in this schema already have them. Migration 024 drops both foreign keys
and drops `orgs` and `teams` with them, and replaces the org key with
`CHECK (org_id <> '')` — a constraint asking a question the caller can answer.

Scope is enforced at the store, because the store is where scope is known.
`get`, `update` and `delete` take the caller's `org_id`; `create` and the two
list methods refuse a blank one.

Three rules are load-bearing:

**Out of scope reads as absent, not forbidden.** `get` returns `None` and the
route answers 404. A 403 would confirm that a project with that id exists
somewhere, which is the scoped fact the check exists to withhold.

**`update` refuses a statement that matched nothing.** Reporting success for a
row in another scope — or for one that is gone — is what let a scoped surface
behave as an unscoped one without any caller noticing.

**The downgrade backfills before it re-adds the keys.** Every row in a database
that reached 024 has an `org_id` naming nothing, and re-adding a foreign key
over such rows aborts. That is why the pre-024 shape could not be round-tripped,
and so was never tested.

## Consequences

### Positive
- A Design Studio project creation succeeds on a freshly migrated database.
- One caller's project is not readable, editable or deletable by another scope.

### Negative / Trade-offs
- The database no longer refuses an `org_id` that names nothing. It never
  usefully did: the referenced table was empty, so it refused every value.

### Neutral
- `get` and `delete` take a keyword-only `org_id` with no default. Every caller
  is in this repository and already knows the scope.

## Acceptance Criteria

AC-1 is the migration and AC-6 the HTTP surface; both are proven by tests named
in `tests:` above. Neither carries an `ac-modules` anchor: the reachability
graph is over importable modules, and an alembic revision file is loaded by
alembic's own script directory rather than imported, while the route's proof
runs through the Conductor's flat backend. Declared rather than anchored at a
module that would not be the one under test:

<!-- ac-state: unproven AC-1 - proven by tests/migrations/test_migration_chain.py
     against a real server; an alembic revision is not an importable module the
     reachability graph can name -->
<!-- ac-state: unproven AC-6 - proven by packages/maistro-design/tests/test_project_scope.py
     reading the Conductor route's own signatures; the anchor would have to name
     maistro_design, which is not where the route lives -->

```gherkin
Feature: A design project's scope is writable on a clean database and enforced on every read

  @AC-1
  Scenario: A clean database accepts an ordinary design project
    Given a database migrated from empty to head
    When a design project is inserted with the scope the product supplies
    Then the insert succeeds
    And a project naming no scope is refused
    And no table exists whose only purpose is to be referenced

  @AC-2
  Scenario: A project must name the scope it belongs to
    Given a project carrying an empty org
    When it is created, updated, or listed
    Then the store refuses it rather than writing a scope-less row

  @AC-3
  Scenario: A read outside the caller's scope finds nothing
    Given a project stored in one scope
    When a caller in another scope reads it by id
    Then the answer is absence, not refusal
    And the caller's own scope still reads it

  @AC-4
  Scenario: A write outside the caller's scope is refused
    Given a project stored in one scope
    When a caller in another scope updates or deletes it by id
    Then the update reports that it matched nothing
    And the stored project is unchanged

  @AC-5
  Scenario: Every single-project operation takes a scope
    Given the design project store protocol
    When its methods are inspected
    Then get, update and delete each require the caller's scope
    And none of them accepts a default for it

  @AC-6
  Scenario: The HTTP surface passes the caller's scope down
    Given the Conductor's design routes
    When a project is fetched or rendered
    Then the store call carries the scope the request resolved
    And that scope comes from the request when the deployment sets one
```
