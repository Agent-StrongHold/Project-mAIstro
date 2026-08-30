---
id: SPEC-083026-5fab
title: A retried turn appends its session messages once, under an identity it was given
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
  - maistro-engine#ADR-083026-5fab
implements:
  - maistro-engine#ADR-083026-5fab
related:
  - maistro-engine#ADR-082326-c126
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/persistence/test_session_turn_idempotence.py
  - packages/maistro-core/tests/agents/test_base.py
  - packages/maistro-core/tests/runs/test_chat_execution.py
source:
  - packages/maistro-core/src/maistro/persistence/pg_sessions.py
  - packages/maistro-core/src/maistro/persistence/sqlite_sessions.py
  - packages/maistro-core/src/maistro/sessions/store.py
  - packages/maistro-core/src/maistro/sessions/turns.py
  - packages/maistro-core/src/maistro/container.py
ac-modules:
  AC-1: maistro.persistence.pg_sessions
  AC-2: maistro.persistence.pg_sessions
  AC-3: maistro.persistence.pg_sessions
  AC-4: maistro.persistence.pg_sessions
  AC-5: maistro.persistence.pg_sessions
  AC-6: maistro.persistence.pg_sessions
  AC-7: maistro.persistence.pg_sessions
  AC-8: maistro.persistence.sqlite_sessions
  AC-9: maistro.container
layer: Memory
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-083026-5fab: A retried turn appends its session messages once, under an identity it was given

## Context

ADR-083026-5fab adds a supplied turn identity to `append_messages` and a
`session_turns` row that makes at-most-once a database key rather than a
convention. This spec states what that has to be observed doing.

AC-9 is the defect, not a hypothesis. `ChatAttemptExecutor.execute` retries one
turn as a second Attempt under the same NodeRun; each Attempt re-enters
`BaseAgent._persist_run`, so on `develop` a retried turn appends the user's
message twice. The other criteria are the properties that fix has to hold
without introducing a worse one — in particular AC-1, which keeps an
unidentified append behaving exactly as it does today, and AC-5, which stops
the marker from outliving the messages it admits and silently swallowing a
later turn.

Every criterion below is stated against both durable stores. The PostgreSQL
legs run against a real server; the SQLite twin is held to the same conformance
suite, because a twin that is merely similar is a twin nobody can rely on.

## Acceptance Criteria

```gherkin
Feature: A retried turn appends its session messages once

  @AC-1
  Scenario: An append with no turn identity is unchanged
    Given a session store and a batch carrying no turn identity
    When the same batch is appended twice
    Then both appends are recorded
    And the sequence numbers stay contiguous from zero

  @AC-2
  Scenario: A repeated turn identity appends nothing the second time
    Given a batch appended under a turn identity
    When the identical batch is appended again under that identity
    Then the session holds the batch exactly once
    And the second append raises nothing

  @AC-3
  Scenario: A repeated identity is refused on identity alone
    Given a batch appended under a turn identity
    When a batch with different content is appended under that same identity
    Then nothing is added to the session

  @AC-4
  Scenario: An identity is scoped to its session
    Given a batch appended to one session under a turn identity
    When a batch is appended to a different session under that same identity
    Then the second session records its batch

  @AC-5
  Scenario: The marker does not outlive the messages it admitted
    Given a turn appended under an identity
    When retention removes that turn's messages
    And the same identity is appended again
    Then the messages are recorded again

  @AC-6
  Scenario: Deleting a session forgets its turn identities
    Given a turn appended to a session under an identity
    When the session is deleted
    And the same identity is appended to a session with that id
    Then the messages are recorded

  @AC-7
  Scenario: The marker and the messages commit together
    Given an append under a turn identity whose second message cannot be stored
    When the append fails
    Then the session holds none of the batch
    And the identity is free for a later append to use

  @AC-8
  Scenario: The database refuses a duplicate identity on its own
    Given a turn identity already recorded for a session
    When a writer inserts that identity again without the store's guard
    Then the database rejects the write

  @AC-9
  Scenario: A retried chat turn appends its messages once
    Given a chat turn that has run once and written its session messages
    When the turn is retried as a second Attempt under the same NodeRun
    Then the session holds the user message exactly once
```
