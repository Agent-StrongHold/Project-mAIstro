---
id: SPEC-082926-0b72
title: Conductor Settings Durability
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
  - maistro-engine#ADR-082926-0b72
implements:
  - maistro-engine#ADR-082926-0b72
related:
  - maistro-engine#SPEC-010
  - maistro-engine#SPEC-011
  - maistro-engine#ADR-082226-5104
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/hive-conductor/backend/tests/test_settings_durability.py
source:
  - packages/hive-conductor/backend/services/settings_store.py
ac-modules:
  AC-1: services.settings_store
  AC-2: routes.settings
  AC-3: services.settings_store
  AC-4: routes.settings
  AC-5: services.settings_store
  AC-6: services.settings_store
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-082926-0b72: Conductor Settings Durability

- **Status:** Active
- **Decision:** ADR-082926-0b72
- **Closes:** #334

## Scope

The Conductor's operator-facing settings surface: `GET/PUT/PATCH /api/settings`,
the capability toggle in `routes/capabilities.py`, and the Setup wizard's
default-model choice in `routes/setup.py`. All three write the same record.

Out of scope: the *contents* of `SettingsModel`, which this document does not
change, and the data-directory that holds the database file, which is #331.

## The record

Settings persist as a single envelope under one key in the Conductor's
`PersistedStore`:

| field | meaning |
|---|---|
| `schema_version` | the envelope shape this build wrote |
| `revision` | monotonic, incremented once per accepted write |
| `updated_at` | when that write was confirmed |
| `values` | the `SettingsModel` payload, unchanged by this spec |

The envelope migrates; the payload does not. A reader that does not understand
`schema_version` refuses the record rather than dropping the fields it cannot
name.

## Acknowledgement

`PersistedStore.put` enqueues a closure for a writer thread and returns, and
`State._writer_loop` swallows every exception that closure raises. A route that
returns after `put` has therefore not observed anything. A write is acknowledged
only after the value has been read back through a *reader* connection and
compared to what was sent.

## Volatility

Values that are deliberately not durable live in a named overlay, are returned
under a `volatile` key marked `durable: false`, and never reach the record. The
durable record is never inferred from the overlay, and clearing the overlay
never changes the record.

## Acceptance Criteria

```gherkin
Feature: Conductor settings durability

  @AC-1
  Scenario: Settings persist as one versioned envelope
    Given a Conductor with a durable state database
    When a settings value is written
    Then the stored record carries a schema version, a revision and an update time
    And the payload is the SettingsModel the caller sent

  @AC-2
  Scenario: A settings write is acknowledged only after a read-back
    Given a Conductor with a durable state database
    When PUT /api/settings is called with a new default model
    Then the response body is the value read back from the durable store
    And a reader connection opened afterwards returns that same value

  @AC-2
  Scenario: A write the store did not take is not acknowledged
    Given a durable store whose writes do not land
    When PUT /api/settings is called
    Then the response is 503
    And no success-shaped body carries the unwritten value

  @AC-3
  Scenario: Secret material is refused rather than stored
    Given a settings payload whose value carries an API key
    When the write is attempted
    Then the write is refused with 400
    And the rejection names the field and not the value
    And the durable record is unchanged

  @AC-4
  Scenario: A stale write is refused with the current value
    Given a settings record at revision 3
    When a write arrives declaring expected revision 2
    Then the response is 409
    And the body carries the record at revision 3
    And the durable record is unchanged

  @AC-4
  Scenario: An undeclared write is last-writer-wins by choice
    Given a settings record at any revision
    When a write arrives declaring no expected revision
    Then the write is accepted
    And the stored revision advances by exactly one

  @AC-5
  Scenario: Settings survive a restart
    Given a settings value written through the durable store
    When the Conductor's state is closed and reopened against the same database
    Then the value is still the one that was written

  @AC-5
  Scenario: An older envelope migrates forward on read
    Given a stored record written at an older schema version
    When the store loads it
    Then the record is readable at the current schema version
    And its payload is unchanged

  @AC-5
  Scenario: A forward-version envelope is refused, not coerced
    Given a stored record whose schema version exceeds this build's
    When the store loads it
    Then the load fails
    And nothing overwrites the record

  @AC-5
  Scenario: An invalid value never reaches the store
    Given a settings payload that fails model validation
    When the write is attempted
    Then the write is refused
    And the durable record is unchanged

  @AC-6
  Scenario: A volatile preview value is labelled and never persisted
    Given a preview override set on the volatile overlay
    When the settings surface is read
    Then the override is returned under a volatile key marked not durable
    And the durable record does not contain it

  @AC-6
  Scenario: Clearing the overlay does not disturb the record
    Given a preview override and a durable record that disagree
    When the overlay is cleared
    Then the durable record is unchanged
```
