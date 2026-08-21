---
id: SPEC-019
title: "Human-as-node delegation — channel-routed prompts, identity-attested replies, per-human prompt optimization"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-04-25
substrate:
  - maistro-engine#ADR-009
  - maistro-engine#ADR-028
  - maistro-engine#ADR-024
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Agents
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-04-25
---

# SPEC-019: Human-as-Node Delegation

See `blakematthews-dev/project_maistro` specs/conductor/S-158-human-as-node.md for full spec.

## Acceptance Criteria

- [ ] A `human` node can be added via SPEC-020 Node Designer with at least 5 channel options (Teams, email, SMS, conductor, conductor-app)
- [ ] Channel selection respects priority + hours + urgency policy; verified by browser automation
- [ ] Reactor registers wait-events on channel responses; timeout falls back to next-priority channel; exhaustion produces a structured "no human response" error
- [ ] Bouncer screens human responses on return; verified with a test that injects a known prompt-injection payload into a simulated human reply
- [ ] Audit log records every human delegation as a signed VC with channel, latency, identity attestation method, response
- [ ] Per-human prompt optimization (opt-in) converges on per-human variants over time
- [ ] Opt-out: `STOP-LEARN` reply disables optimization for that human and deletes variant-performance state
- [ ] SMS / cost-bearing channels require admin signature before each delegation
- [ ] Delegation rate limits: defaults set during setup wizard (SPEC-009), stored per-node in config, enforced at delegation dispatch; `DELEGATION_RATE_LIMIT_EXCEEDED` returned to requesting node when a cap is hit (not a silent drop)
- [ ] First contact: the first delegation to a new human node includes a STOP-LEARN opt-out marker in the message
