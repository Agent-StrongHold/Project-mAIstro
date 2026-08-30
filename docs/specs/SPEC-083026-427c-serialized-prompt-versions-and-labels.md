---
id: SPEC-083026-427c
title: Prompt version creation and label promotion are one serialized, idempotent write
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
  - maistro-engine#ADR-083026-427c
implements:
  - maistro-engine#ADR-083026-427c
related: []
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/persistence/test_prompt_store_conformance.py
source:
  - packages/maistro-core/src/maistro/persistence/pg_prompts.py
  - packages/maistro-core/src/maistro/persistence/sqlite_prompts.py
ac-modules:
  AC-1: maistro.persistence.pg_prompts
  AC-2: maistro.persistence.pg_prompts
  AC-3: maistro.persistence.pg_prompts
  AC-4: maistro.persistence.pg_prompts
  AC-5: maistro.persistence.pg_prompts
  AC-6: maistro.persistence.pg_prompts
  AC-7: maistro.persistence.pg_prompts
  AC-8: maistro.persistence.sqlite_prompts
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-083026-427c: Prompt version creation and label promotion are one serialized, idempotent write

## Context

ADR-083026-427c splits a prompt version from the labels that point at it, and
puts the whole of `upsert` inside one transaction holding a per-name advisory
lock. This spec states what that has to be observed doing.

Two of the criteria below are regressions of defects measured on `develop`
against PostgreSQL 18.6, not hypotheses. AC-1 is the `ON CONFLICT` arbiter that
cannot be inferred; AC-2 is the primary-key collision waiting behind it. Both
fire on the *first* write of a new prompt, so the path they break is the one
every prompt takes exactly once.

## Acceptance Criteria

```gherkin
Feature: Prompt versions and labels are written once, together, and only forward

  @AC-1
  Scenario: The first version of a prompt is created on PostgreSQL
    Given a PostgreSQL prompt store holding no version of a name
    When a caller upserts content under the label latest
    Then the write succeeds
    And both latest and production resolve to that version

  @AC-2
  Scenario: One version carries several labels without being stored twice
    Given a version that both latest and production point at
    When the stored versions for that name are counted
    Then exactly one version row holds the content

  @AC-3
  Scenario: Concurrent writers to one name do not share a version number
    Given two connections upserting different content under the same name
    When both have committed
    Then the name has two versions with consecutive numbers
    And each version holds the content its writer supplied

  @AC-4
  Scenario: A label is never left pointing at nothing
    Given a label pointing at an existing version
    When an upsert that would move it fails before committing
    Then the label still resolves to the version it pointed at before

  @AC-5
  Scenario: A repeated write of identical content creates no new version
    Given a name whose head version holds some content and config
    When the identical content and config are upserted again
    Then the version count is unchanged
    And the requested label points at that same head version

  @AC-6
  Scenario: Writers to different names do not contend
    Given two connections upserting under two different names
    When one holds its transaction open
    Then the other completes without waiting for it

  @AC-7
  Scenario: The database refuses a duplicate version or a forked label
    Given a PostgreSQL prompt store
    When a second row is written for an existing name and version
    Or a label for one name is pointed at two versions at once
    Then the database rejects the write

  @AC-8
  Scenario: The SQLite twin stores the same shape
    Given the same sequence of upserts run against SQLite and PostgreSQL
    When each store is read back
    Then the versions, labels and contents agree
```

## Evidence required

- AC-1 and AC-2 must run against a **real** PostgreSQL server. The existing
  `test_pg_prompts.py` drives a fake connection that enforces no constraints,
  which is why two unconditional failures sat on `develop` under a green suite:
  a test that cannot fail on a key violation is not evidence about a key.
- AC-3 and AC-6 need two distinct connections. A single connection reusing one
  transaction cannot observe either serialization or its absence.
- AC-4 must abort the transaction rather than mock a failure, so that what is
  tested is the database's rollback rather than the code's intention.
