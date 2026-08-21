---
id: SPEC-018
title: "Lightning-native federation — conductor friends, paid messaging, payment-graph reputation"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-04-25
substrate:
  - maistro-engine#ADR-024
  - maistro-engine#ADR-027
  - maistro-engine#ADR-029
  - maistro-engine#ADR-028
implements:
  - maistro-engine#ADR-027
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
  - cross-service
tests: []
layer: Crypto
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-04-25
---

# SPEC-018: Lightning-Native Federation

See `blakematthews-dev/project_maistro` specs/security/S-156-lightning-federation.md for full spec.

## Acceptance Criteria

- [ ] **Federation works without Lightning installed.** A conductor with no LN plugin federates over DID/VC + substrate; no LN code path is invoked.
- [ ] Two conductors with Lightning enabled complete a friend handshake in under 60 seconds on signet
- [ ] A pay-per-query federation request succeeds end-to-end: A pays 100 sats, B returns memory entries as signed VCs, A verifies the VCs against B's DID document
- [ ] Conductor-to-conductor DM works with Sphinx routing; the message is opaque to substrate intermediaries
- [ ] **Non-LN first contact:** DID-only federation request from unknown peer lands in Dashboard Approvals queue; admin must approve before any exchange occurs
- [ ] **Non-LN rate limits:** 60/hour, 500/day, 10/10s burst enforced per approved peer; excess dropped with `FEDERATION_RATE_LIMIT` log entry
- [ ] **Non-LN repeated violations:** more than 3 cap events in 24h triggers automatic suspension and admin alert
- [ ] **LN routing failure:** failed payment queued with exponential backoff (up to 5 retries); after 5 failures, moved to Dashboard queue with `FEDERATION_PAYMENT_FAILED` alert
- [ ] **Bouncer on inbound federation messages:** every inbound federation message (LN-paid or non-LN) passes through the Bouncer (SPEC-001) before any action is taken; a message that triggers the Bouncer is dropped with `SAFETY_VIOLATION` logged, the sending peer's rate-limit counter is incremented as if a normal query was consumed, and the sender is NOT informed which pattern triggered (no oracle); repeated Bouncer hits from the same peer count toward the violation-suspension threshold
