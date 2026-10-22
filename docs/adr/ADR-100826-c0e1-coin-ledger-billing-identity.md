---
id: ADR-100826-c0e1
title: "A coin charge names its Run, and a client request id never suppresses one"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-10-08
accepted: 2026-10-08
history:
  - status: Proposed
    date: 2026-10-08
  - status: Accepted
    date: 2026-10-08
substrate:
  - maistro-engine#ADR-083026-56ee
implements: []
related:
  - maistro-engine#SPEC-081226-a66b
  - maistro-engine#ADR-083026-1cb1
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/agents/test_coin_ledger_conformance.py
  - packages/maistro-core/tests/agents/test_outcome_names_its_session.py
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# ADR-100826-c0e1: A coin charge names its Run, and a client request id never suppresses one

Implements #827. Issue #718 — the provider-quota ledger — is a different
surface and is pointed at, not absorbed.

## Context

The engine's coin-ledger integration was duck-typed: `Agent._record_outcome`
handed whatever it had to a `charge_usage` attribute on an object the
container injected, with no protocol in this repository to read. Two questions
had no answer anywhere on the engine side, and each has an opposite failure
mode:

**Is `request_id` audit correlation or an idempotency key?** ADR-083026-56ee
made the per-turn correction — pass the Run id, not the session — explicitly
"without the ledger's contract in hand", choosing the narrowest value that is
right under both readings. But its expression, `request_id=context.run_id or
context.request_id`, put two meanings in one parameter: when no canonical Run
is in scope, the key *is* the request correlation id, and the request id may
be a client-supplied `X-Request-ID`. Under the dedupe reading, a client that
resends one header suppresses every charge behind it. Under the store-only
reading, a retried report bills twice. The engine could not even say which
behavior it was committing an adapter to.

**What is the billable unit?** Run, Attempt, or a future Invocation identity
were all live options, and adding ad hoc deduplication before choosing one
would freeze a guess into a billing surface.

The urgency is bounded and worth stating plainly, because the fix must not
overclaim: Stronghold's concrete `PgCoinLedger` inserts unconditionally and
its migration `009` indexes `request_id` non-uniquely, so **there is no
reproducible charge-suppression defect today**. The defect this ADR removes is
the contract gap that made every adapter's dedup behavior unobservable and
every future adapter's guess unjudgeable.

## Decision

**The integration becomes a typed protocol.** `maistro.protocols.coins`
defines `CoinLedger`, and the agent and factory take it by that name. The
protocol carries the two-field identity contract below; persistence policy
stays with the adapter.

**Audit and idempotency are separate fields with separate rules.**

- `charge_key` — idempotency. The billable unit's server-controlled identity.
  Uniqueness scope: ledger-wide, one charge per key. A repeated key is a
  retried report of one charge: record nothing new and return the original
  receipt.
- `request_id` — audit correlation. The `ExecutionContext` request id, which
  may be a client-supplied `X-Request-ID`. Stored, indexed non-uniquely,
  never deduped on, never accepted as a charge identity.

**The billable unit is the canonical Run.** Every governed admission creates
one — chat admission admits one Run per turn, direct and graph work enter
through the same canonical Run service — so the Run is the identity that is
always present at charge time, always server-generated, and stable across
retries: retrying a NodeRun creates a new Attempt while preserving `run_id`
(SPEC-081226-a66b). **The Attempt is the retry boundary, not the billable
unit**: a retry adds an Attempt and no charge. No finer identity is minted
here; per-Invocation sub-billing is the provider-quota ledger's concern
(#718), which already records canonical Invocations, and minting a second
ungoverned identifier for coins would duplicate it.

**An absent key never suppresses a charge.** Work can execute outside any
canonical Run. There the engine passes `charge_key=None` and a conforming
ledger records the charge unconditionally — the same safe direction
ADR-083026-56ee chose for the per-turn key. A doubled charge in a rare
transport retry is visible and refundable; a silently dropped charge is
neither. Corollary, and the point of the whole contract: **a client-chosen
`X-Request-ID` can never suppress a charge**, because no conforming path
leads from it to a dedup decision.

**The contract is conformed, not just declared.** Three named rules —
`canonical-retry-charges-once`, `client-request-id-cannot-collide`,
`unkeyed-charge-never-suppressed` — run against a reference adapter and
against deliberately broken adapters in
`packages/maistro-core/tests/agents/test_coin_ledger_conformance.py`; a
dedupe-on-`request_id` or suppress-unkeyed adapter fails by name.
SPEC-100826-c0e1 states the rules and the downstream adapter/schema
requirements (partial unique index on `charge_key`, non-unique audit index on
`request_id`) so a concrete adapter's migration is linkable.

**Reconciliation with ADR-083026-56ee.** That ADR chose the Run as the charge
key and is confirmed by this one; its fallback expression is not. Under this
contract the no-Run turn charges under *no* key, and the request id travels
only in the audit field. The session-naming and provenance decisions of 56ee
are untouched.

## Consequences

### Positive

- An adapter's dedup behavior is judgeable: the conformance rules name what a
  ledger must do with a repeated key, a reused client id, and a missing one.
- Canonical retries charge exactly once by construction, because the retry
  machinery already preserves the Run id the key names.
- The engine stops handing a client-influenced value to the one parameter a
  ledger might key on.

### Negative / Trade-offs

- The no-Run path gives up dedup entirely: two transport retries of the same
  unkeyed turn bill twice. That is the chosen direction (visible over
  silent), but it is real over-billing exposure, and the cure is giving that
  work a canonical Run, which chat admission already does.
- Behavior change to the external integration: the no-Run fallback no longer
  sends `request_id=<correlation id>` as the ledger's only argument. An
  adapter that keyed reporting on that parameter by design would now see
  keyed and unkeyed charges — visible, and the recoverable side of the same
  trade 56ee already accepted.
- Stronghold (and any concrete adapter) needs a migration: `charge_key` as a
  nullable column with a partial unique index, `request_id` demoted to audit.
  Until it lands, the engine-side protocol is stricter than the deployed
  ledger; the gap is the downstream work item, not a silent one.

### Neutral

- The provider-quota ledger (#718), the Invocation record, and
  `Outcome.charged_microchips` reporting all keep their existing identities;
  this contract only names what the coin charge itself is keyed by.
- `Outcome.request_id` continues to carry audit correlation, per
  ADR-083026-56ee; the charge contract and the outcome record now agree on
  what that field means.
