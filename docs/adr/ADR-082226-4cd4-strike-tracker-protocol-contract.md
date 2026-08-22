---
id: ADR-082226-4cd4
title: "StrikeTracker is a protocol, and the protocol is only what Gate calls"
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-08-22
substrate: []
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts: [boundary]
tests: []
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082226-4cd4: StrikeTracker is a protocol, and the protocol is only what Gate calls

## Context

`Gate` holds the strike ladder. It reads a record before admitting input, writes
one after a violation, and then reads `strike_count`, `scrutiny_level`,
`locked_until`, `disabled` and `is_locked` off whatever comes back.

Both `Gate.__init__` and `Container.strike_tracker` were typed against the
**concrete** `InMemoryStrikeTracker`, against this repository's own convention —
*"Protocol-driven DI: business logic depends on protocols, never concrete
implementations"* (`packages/maistro-core/CLAUDE.md`).

The cost was not theoretical. `PgStrikeTracker` described itself as a
replacement for the in-memory tracker and returned `dict` from both of its
methods. Wiring the durable tracker therefore raised `AttributeError` on the
**first security violation** — on the path whose entire job is to hold under
attack. Nothing caught it, because "same interface" was a sentence in a
docstring rather than a checked claim.

Exporting a name from `maistro.protocols` makes it a downstream-facing contract:
Stronghold and any other importer of `maistro-core` may implement against it and
expect it to hold. That deserves to be written down rather than inferred from an
`__init__` file.

## Decision

**`StrikeTracker` is a `@runtime_checkable` Protocol in
`maistro.protocols.strikes`, exported from `maistro.protocols`, and it is the
type `Gate` and `Container` are annotated with.**

Three parts to the contract:

1. **Two methods, not five.** `get` and `record_violation` — only what `Gate`
   actually calls. `submit_appeal`, `remove_strikes`, `unlock` and `enable`
   exist on the in-memory implementation and are admin surface reached through
   other paths. Putting them in the protocol would oblige every tracker to
   implement an operator console before it could serve the security path, which
   is how a narrow seam becomes an unimplementable one.

2. **`StrikeRecord` is the return type, not a mapping.** `is_locked` is a
   *computed* property — disabled, or `locked_until` still in the future — and a
   `dict` makes every caller recompute it. That is exactly how two
   implementations end up disagreeing about whether an account is locked.

3. **The full record, every time.** `record_violation` returns the escalated
   state rather than a summary of what it changed: `Gate` reports the fields
   above straight from that return value, so a partial record leaves the
   response describing a state the account is no longer in. `get` returning
   `None` means "no violation ever recorded"; it must never mean "some fields
   were unavailable", because `Gate` admits input when `is_locked` is falsy.

Scope stays per ADR-068: the tracker is keyed by `user_id` on the soft scope
axes. Hard tenant segmentation is Stronghold's, not core's.

## Consequences

### Positive
- A tracker that does not satisfy the ladder is a type error at the boundary
  instead of an `AttributeError` during an attack.
- `PgStrikeTracker` and `InMemoryStrikeTracker` are checked against one
  conformance suite, so "same interface" is now a test rather than a claim.
- Downstream products have a named, minimal contract to implement against.

### Negative / Trade-offs
- The admin operations are outside the protocol, so any caller that needs them
  must depend on a concrete tracker — the narrowness that makes the security
  seam implementable also means it does not cover operator tooling.
- `runtime_checkable` verifies method *presence*, not signatures, so it is a
  weaker guard than the static annotation; the conformance suite is what covers
  the difference.

### Neutral
- No behaviour change to the ladder itself: thresholds, scrutiny levels and
  lockout durations are unchanged.
