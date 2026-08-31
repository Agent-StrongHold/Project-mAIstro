---
id: SPEC-083026-56ee
title: "A session turn names its producing Run, and an outcome names its session"
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
  - maistro-engine#ADR-083026-1cb1
  - maistro-engine#ADR-083026-e602
  - maistro-engine#ADR-083026-5fab
implements:
  - maistro-engine#ADR-083026-56ee
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/persistence/test_session_turn_provenance.py
  - packages/maistro-core/tests/agents/test_outcome_names_its_session.py
ac-modules:
  AC-1: maistro.persistence.pg_sessions
  AC-2: maistro.persistence.sqlite_sessions
  AC-3: maistro.sessions.turns
  AC-4: maistro.agents.base
  AC-5: maistro.agents.base
  AC-6: maistro.persistence.pg_sessions
layer: Memory
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-083026-56ee: A session turn names its producing Run, and an outcome names its session

## Context

ADR-083026-56ee records the decision. This spec states what has to be true for
it to count as done.

The starting state, verified against `develop` at `3f5fd6a`:

- `session_turns` (`023`) holds `session_id`, `turn_id` and `timestamp`, and
  nothing else. `container.py` happens to pass `run.run_id` as the `turn_id`,
  but `turn_id` is contractually opaque — `reject_blank_turn_id` is its whole
  definition, and the SQLite twin declares it `TEXT NOT NULL` with no meaning.
- `canonical_runs` (`005`) records the session under
  `payload -> 'provenance' ->> 'session_id'`, with no index on it.
- `Outcome` has no `session_id` field. `agents/base.py`, the only production
  site that writes `request_id`, writes the session id into it, and passes the
  same value to `charge_usage(request_id=)`.

## Goals

- Migration `028` adds nullable `run_id`, `node_run_id` and `attempt_id` to
  `session_turns` with an index on `run_id`, a nullable `session_id` to
  `outcomes` with an index, and an expression index on
  `canonical_runs (payload -> 'provenance' ->> 'session_id')`.
- `PgSessionStore.append_messages` and `SqliteSessionStore.append_messages`
  resolve the producer through `observed_provenance` and write it with the turn
  marker.
- `Outcome` carries `session_id`; `PgOutcomeStore` and `SqliteOutcomeStore`
  persist and read it back.
- `agents/base.py` writes the session to `session_id`, leaves `request_id` to
  the ambient request id, and keys the ledger charge per turn.

## Non-goals

- Re-reading `turn_id` as a Run reference. It stays an opaque idempotency key;
  promoting it would promote every existing caller's string to a Run id.
- Backfilling `outcomes.session_id` from `outcomes.request_id`. That assumes
  every historical row came from the one call site that wrote a session there,
  which is the assumption ADR-083026-56ee exists to stop making.
- Backup/restore preserving correlated records — #64's fifth bullet, its own
  sub-issue.
- Changing the retry semantics of ADR-083026-5fab in any way.

## Acceptance Criteria

```gherkin
Feature: A session turn names its producing Run, and an outcome names its session

  @AC-1
  Scenario: A turn appended inside an execution records it
    Given an execution context naming a Run, a NodeRun and an Attempt
    When a message batch is appended under a turn identity
    Then the turn marker carries that Run, NodeRun and Attempt
    And the messages themselves are unchanged

  @AC-2
  Scenario: A turn appended outside an execution records absence, not emptiness
    Given a message batch appended under a turn identity with no execution in scope
    When the turn marker is read
    Then its three producer fields are null rather than empty strings
    And both backends answer the same way

  @AC-3
  Scenario: The turn identity keeps the meaning it had
    Given a turn identity that is not a Run id
    When the same batch is appended twice under it
    Then the second append writes nothing and raises nothing
    And a blank turn identity is still refused

  @AC-4
  Scenario: An outcome names its session as a session
    Given a chat turn recorded as an outcome inside an execution
    When the stored row is read
    Then its session id is in the session field
    And its request field holds a request id or nothing, never the session

  @AC-5
  Scenario: The ledger is charged per turn, not per session
    Given two turns of one session, each charged
    When the keys the ledger was given are compared
    Then they differ
    And each names the turn's own execution

  @AC-6
  Scenario: The session store still owns no execution lifecycle
    Given the session store's public surface
    When it is read for anything that starts, closes, retries or cancels an execution
    Then there is nothing of the kind
    And the Run this session produced is found through an index, not a scan
```
