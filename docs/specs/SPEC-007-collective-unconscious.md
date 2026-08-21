---
id: SPEC-007
title: "Collective Unconscious — federated wisdom sharing"
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
layer: Memory
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-03-23
---

# SPEC-007: Collective Unconscious

## Problem
Learnings are siloed per conductor instance. Two conductors on different machines can't share discovered patterns.

## Solution
Cross-tenant T7 wisdom tier. High-confidence learnings (score > 0.9) optionally shared to a federated pool. Pulled during dream loop consolidation.

## Open questions

- **Privacy (OPEN):** which memory tiers and content classes are safe to share? Working assumption: only T7 LORE entries (high-abstraction, non-user-identifying) with explicit per-entry opt-in. Needs a dedicated policy spec before implementation.

- **Trust (PARTIALLY RESOLVED → SPEC-018, ADR-024):** cross-instance learnings would arrive as Verifiable Credentials signed by the peer conductor's DID. The existing federation trust VC model already handles peer identity validation.

- **Transport (PARTIALLY RESOLVED → SPEC-018):** SPEC-018 Lightning federation provides p2p transport between conductors without a central broker.

## Key files
- `conductor/orchestrator/agents/experimental/` (new)
