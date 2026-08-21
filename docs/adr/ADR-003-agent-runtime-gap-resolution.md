---
id: ADR-003
title: Agent runtime gap analysis (archived branch resolution)
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-04-26
substrate:
  - maistro-engine#ADR-001
implements: []
related: []  # roadmap doc: the gap→tranche ADR ranges in the body are planning
             # numbers, not semantic edges. The original numbering predates the
             # canvas/substrate 041-046 renumber (now ADR-062..067), so pinning them
             # as machine-readable edges would mis-link this to unrelated canvas ADRs.
supersedes: []
blocks: []
blocked-by: []
contracts: []
tests: []
layer: Agents
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-04-26
  - status: Accepted
    date: 2026-04-26
---

# ADR-003: Agent runtime gap analysis (archived branch resolution)

**Status:** Accepted  
**Date:** 2026-04-26  
**Tranche:** T0  
**Depends on:** ADR-001

---

## Context

An orphaned branch `origin/claude/compare-bot-frameworks-tFPdY` contained a single commit (`76954c1`, 2026-03-17) adding a gap analysis document comparing maistro-engine against a **full personal-agent runtime** (five primitives: identity, memory, workspace context, scheduled autonomy, skill composability). It was never merged and had no PR open.

The analysis identified five gaps in maistro-engine relative to that reference runtime:

| # | Primitive | Status at time of analysis |
|---|---|---|
| 1 | **Soul** (identity/personality) | MISSING — static system prompt only |
| 2 | **Memory** | Schema defined (`MemoryEntry`, `KnowledgeNode`), not wired |
| 3 | **Context** (workspace awareness) | MINIMAL — description + constraints only |
| 4 | **Heartbeat** (proactive autonomy) | EMPTY MODULE — `scheduler/` had no code |
| 5 | **Taskmaster** (skill composability) | HARDCODED — no runtime skill discovery |

## Decision

1. Keep a **neutral** summary of the agent-runtime gaps in this ADR. The original vendor-specific comparison text was removed per repository naming policy.
2. Delete the orphaned branch once this ADR is committed to `integration`. Its only unique content is captured here and in the gap-analysis stub.
3. Treat the five gaps as the north-star for the porting backlog: each gap is closed by a specific tranche.

**Gap-to-tranche mapping:**
- Gap 1 (Soul) → T8 (`ADR-055` through `ADR-058`)
- Gap 2 (Memory) → T2 (`ADR-011` through `ADR-018`)
- Gap 3 (Context) → T7 (`ADR-049` through `ADR-054`)
- Gap 4 (Heartbeat) → T6 (`ADR-043` through `ADR-048`)
- Gap 5 (Taskmaster/skills) → T5 (`ADR-036` through `ADR-042`)

## Acceptance criteria

- [x] `docs/analysis/agent-runtime-gap-analysis.md` present on `integration`
- [ ] Orphaned branch `origin/claude/compare-bot-frameworks-tFPdY` deleted after this commit merges (manual step — requires `git push origin --delete claude/compare-bot-frameworks-tFPdY`)

## Out of scope

The original document's Phase 3 channel integration recommendations (Slack/Discord). iMessage from approved sources only is the chosen channel; defer to T15+.

## Source references

- Historical branch `origin/claude/compare-bot-frameworks-tFPdY` (orphaned; delete after merge).
