---
id: SPEC-008
title: "Agent-to-agent networking"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-03-23
substrate: []
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests: []
layer: Connectivity
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-03-23
---

# SPEC-008: Agent-to-agent networking

## Problem
Agents can't directly delegate to or query each other. All coordination goes through the conductor orchestrator.

## Solution
Direct agent-to-agent RPC layer. Agent A can spawn Agent B and await its result without going back through the main loop.

## Open questions

- **Authority delegation (RESOLVED → SPEC-015 §6):** privilege escalation through agent chains is prevented by the capability envelope model. Each conductor in the chain enforces the initiator's original permission envelope; adding wraps can only narrow the scope, never widen it.

- **Deadlock / circular delegation (RESOLVED → SPEC-015 §6):** depth budget (default 16 hops), latency budget (default 60 s), and token-spend budget (default 1M tokens) are tracked per chain.

- **Observability (RESOLVED → SPEC-015 §6 + ADR-037 + ADR-024):** initiator identity and acting-via provenance propagate through all chains as required fields in every audit-log VC.

## Key files
- `conductor/orchestrator/agents/agent_spec.py` (networking extension)
