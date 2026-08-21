---
id: SPEC-020
title: "Node Designer + Graph Designer UI — visual composition of the hyperagent graph"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-04-25
substrate:
  - maistro-engine#ADR-009
  - maistro-engine#ADR-028
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: UserClient
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-04-25
---

# SPEC-020: Node Designer + Graph Designer UI

See `blakematthews-dev/project_maistro` specs/infra/S-159-node-graph-designer.md for full spec.

## Acceptance Criteria

- [ ] Adding a node via Node Designer produces a node visible on the Graph Designer canvas within 1s of admin signature
- [ ] Editing a node via Node Designer updates the canvas live; existing in-flight chains use the prior version
- [ ] Channel-priority drag-reorder works on Teams/Slack/email/SMS/Conductor/Conductor-app channel types
- [ ] Form validation refuses invalid combos (admin-only tools on user-keyed nodes; shell on human nodes; CONVERSATION with non-empty whitelist; etc.)
- [ ] Adapter handshake test runs for imported-agent nodes; failure blocks save
- [ ] All Designer changes are admin-signed and recorded as VCs in the audit log
- [ ] Graph Designer renders nodes + edges + live traffic for a graph of at least 50 nodes without performance degradation
- [ ] Replay mode plays back actual traffic for an operator-selected time window using Langfuse trace data
- [ ] Trust-tier color coding is consistent: gold (featured) / green (trusted) / yellow (shadow) / red (untrusted) / blue (human) / purple (conductor-as-node)
- [ ] Users in read-only mode can view + replay traffic from their own chains; cannot edit
- [ ] Export / import: a graph YAML round-trips through export → import without loss
- [ ] Graph import security: an imported graph YAML is validated with the same per-node checks as Node Designer form submission; a YAML specifying admin-only tools (e.g. `shell`) on a user-level node is **rejected** with a validation error naming the violating field; a YAML that sets `trust_tier` to anything other than `untrusted` for a new node is **silently overridden** to `untrusted`; the import flow cannot bypass tool-whitelist invariants enforced by the form
- [ ] CLI parity: every Designer action has a `maistro graph ...` CLI command for headless / scripted use
