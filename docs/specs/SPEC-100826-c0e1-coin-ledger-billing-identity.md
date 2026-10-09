---
id: SPEC-100826-c0e1
title: "Coin-ledger billing and idempotency identity contract"
repo: maistro-engine
kind: spec
status: AC Defined
created: 2026-10-08
accepted: 2026-10-08
history:
  - status: Proposed
    date: 2026-10-08
  - status: Accepted
    date: 2026-10-08
  - status: AC Defined
    date: 2026-10-08
substrate:
  - maistro-engine#ADR-100826-c0e1
  - maistro-engine#ADR-083026-56ee
implements:
  - maistro-engine#ADR-100826-c0e1
related:
  - maistro-engine#SPEC-081226-a66b
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/agents/test_coin_ledger_conformance.py
  - packages/maistro-core/tests/agents/test_outcome_names_its_session.py
ac-modules:
  AC-1: maistro.protocols.coins
  AC-2: maistro.agents.base
  AC-3: maistro.agents.base
  AC-4: maistro.agents.base
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-100826-c0e1: Coin-ledger billing and idempotency identity contract

## Context

ADR-100826-c0e1 records the decision (#827). This spec states what has to be
true for it to count as done, and what a concrete adapter must build.

The starting state, verified against `develop` at `66f3cea9`:

- No engine-side type names the coin-ledger integration;
  `Agent._record_outcome` calls a duck-typed `charge_usage` and passes
  `request_id=context.run_id or context.request_id` — one parameter carrying
  audit correlation and idempotency, with a client-influenced value in the
  fallback position.
- Stronghold's `PgCoinLedger` inserts unconditionally and migration `009`
  indexes `request_id` non-uniquely: no charge-suppression defect is live
  today, and none is claimed. The gap is the missing contract any adapter
  could silently violate.

## Goals

- `maistro.protocols.coins` defines the typed `CoinLedger` protocol whose
  docstring names both identity fields and their semantics; `Agent` and the
  agent factory take it by that type.
- The charge separates `charge_key` (idempotency: the canonical Run id, or
  `None` outside any Run) from `request_id` (audit correlation, possibly a
  client `X-Request-ID`).
- The billable lifecycle is the canonical Run; the retry boundary is the
  Attempt, which preserves `run_id` and adds no charge (SPEC-081226-a66b).
- Conformance rules — `canonical-retry-charges-once`,
  `client-request-id-cannot-collide`, `unkeyed-charge-never-suppressed` —
  pass against a conforming reference adapter and fail by name against
  adapters that dedupe on the client's audit id or suppress unkeyed charges.

## Non-goals

- Claiming any live ledger drops charges today. None is known to.
- Minting a billable identity finer than the Run (per-Invocation sub-billing
  is the provider-quota ledger's surface, #718).
- Placing Stronghold-specific persistence policy in `maistro-core`; this spec
  states requirements, the adapter owns schema and migrations.

## Acceptance Criteria

```gherkin
Feature: A coin charge names its Run, and a client request id never suppresses one

  @AC-1
  Scenario: The typed contract names its two identity fields
    Given the engine-side CoinLedger protocol
    When an adapter satisfying it receives a charge from the agent
    Then idempotency travels in charge_key and audit correlation in request_id
    And an object without charge_usage is not a CoinLedger

  @AC-2
  Scenario: A canonical retry charges exactly once
    Given one canonical Run that has already been charged
    When the same charge_key is reported again
    Then the ledger records no second charge
    And the retry receives the original receipt

  @AC-3
  Scenario: A reused client request id cannot collide or suppress
    Given two different canonical Runs whose audit request ids are one client-chosen value
    When both are charged
    Then both charges are recorded

  @AC-4
  Scenario: A turn outside any Run is still charged
    Given work charged with no canonical Run in scope
    When the ledger receives charge_key None
    Then the charge is recorded unconditionally
    And repeating the client-chosen request id suppresses nothing
```

## Downstream adapter and schema requirements

Requirements for a conforming concrete adapter (Stronghold's PostgreSQL
ledger is the reference deployment). Each is checkable against the
conformance rules above; the engine never inspects the schema.

1. **`charge_key` is the idempotency column.** Nullable (an unkeyed charge
   has no identity), with a uniqueness scope of the whole ledger — not per
   org, team, user, or session. On PostgreSQL:

   ```sql
   ALTER TABLE coin_charges ADD COLUMN charge_key TEXT;
   CREATE UNIQUE INDEX coin_charges_charge_key_unique
       ON coin_charges (charge_key)
       WHERE charge_key IS NOT NULL;
   ```

   A partial unique index, because `NULL` means "no canonical identity —
   record unconditionally"; a bare `UNIQUE` column would make the second
   unkeyed charge an error, which is the suppression this contract forbids.
   Historical rows keep `charge_key IS NULL` and are never deduped.

2. **`request_id` is an audit column.** A plain (non-unique) index is
   welcome for correlation lookups; `request_id` must not appear in any
   unique constraint and must not reach a dedup decision. Migration `009`'s
   non-unique request-id index is already conformant for this column.

3. **Duplicate-key handling returns the original receipt.** On a repeated
   `charge_key`, the adapter records nothing and returns the original row's
   `charged_microchips` and `pricing_version` — so an Outcome written after a
   retry reports what the one charge cost.

4. **The receipt contract.** `charge_usage` returns a mapping with at least
   `charged_microchips: int` and `pricing_version: str`.

5. **The engine's obligation**, testable without any schema: `charge_key` is
   always a server-generated canonical Run id or `None` — never a
   client-supplied value.
