---
id: SPEC-015
title: "Hyperagent Graph Runtime — the conductor is a self-improving graph of AgentSpec nodes"
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
  - cross-service
tests: []
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-04-25
---

# SPEC-015: Hyperagent Graph Runtime

See `blakematthews-dev/project_maistro` specs/conductor/S-145-hyperagent-graph-runtime.md for full spec.

## Acceptance Criteria

- [ ] `AgentSpec` is named in the codebase as the canonical node type; no other type fills the role
- [ ] All node invocations pass through the Bouncer at every incoming edge — verified by audit log
- [ ] All long-term graph state mutations are owned by exactly one subsystem from the §4 list, enforced in code review
- [ ] Shape A has at least four working implementations: Claude SDK, LiteLLM-routed plain chat, a Medley-imported skill, and a human-on-channel node (SPEC-019)
- [ ] An external multi-agent system (LangGraph or CrewAI) can be imported as a Shape-B subgraph with no core code changes
- [ ] Self-improvement subsystem registry is enumerated in code (one place, not scattered)
- [ ] Initiator identity propagates correctly through chains; verified by audit-log inspection
- [ ] Recursion: a deliberately recursive A→B→A composition completes within budgets; an unbounded version fails at budget exhaustion with a structured error
- [ ] Test: a malicious imported agent (or a malicious human response) cannot escape its capability envelope
- [ ] Cross-conductor token spend: B's federation response includes `tokens_consumed`; A debits the amount against the chain budget before proceeding; missing field triggers the conservative `ceil(len(response) / 4)` estimate; per-hop spend visible in the chain audit log
