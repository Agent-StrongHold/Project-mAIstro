---
id: ADR-085
title: "Cost, Quota, and Rate Limiting"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-05-30
substrate:
  - maistro-engine#ADR-054
  - maistro-engine#ADR-068
implements: []
related:
  - maistro-engine#ADR-051
  - maistro-engine#ADR-038
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
layer: Reliability
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-30
  - status: Accepted
    date: 2026-05-30
---

# ADR-085: Cost, Quota, and Rate Limiting

**Status:** Proposed
**Date:** 2026-05-30
**Governs token spend** at three nested levels so that no single task, principal, or background
process can run the bill away, and so that crossing a limit asks rather than fails.

---

## Context

ADR-054 gives a per-task budget ceiling and ADR-068 gives the authorization model with its budget
veto, but neither says how task-level budgets, longer-horizon quotas, and cheap background work
relate. Today spend control is ad hoc: a runaway loop, a chatty consolidation job, or a single
greedy user can exhaust tokens with no consistent backstop. This ADR specifies the layered spend
model and pins it to the existing approval and reliability substrate.

## Decision

Token spend is governed at **three levels**, evaluated together:

1. **Per-TASK budget** — the ADR-054 ceiling. A single task cannot exceed its allotted tokens; the
   executor stops the task when the ceiling is hit. This is the inner, fastest-moving guard.
2. **Per-SCOPE / per-period quota** — a token quota per scope (user / team) per billing period,
   enforced as an **ADR-068 budget veto**. When a call would push the scope over its period quota,
   Sentinel's BUDGET step vetoes it. Quota is a property of the scope, not of the task.
3. **Background / consolidation work uses BATCH-PRICED tokens.** Proactive producers, memory
   consolidation, reflection, and other non-interactive work route to the cheap batch API tier so
   that always-on housekeeping does not compete with interactive spend at interactive prices.

**Crossing a quota is a gate, not a failure.** When the per-scope quota would be exceeded, the
system raises the **ADR-051 approval gate** ("approve more spend?") rather than hard-failing the
request. The principal (or an authorized approver) can grant the overage; absent approval the work
is held, not dropped.

**Rate-limiting is per-principal.** Request-rate limits are keyed to the principal (user / service
key / agent), independent of token quota — a principal can be within budget yet rate-limited, or
rate-OK yet over quota. The two limits are orthogonal.

**Cost is attributed per scope** for visibility: every token charge is recorded against its scope so
spend is reportable per user / team / period. Attribution is a read concern (dashboards, alerts) and
does not itself block; enforcement is the quota veto above.

## Acceptance criteria

- [ ] A task that hits its ADR-054 per-task budget stops; no single task exceeds its ceiling.
- [ ] A call that would push a scope over its per-period token quota is vetoed at the ADR-068 BUDGET
      step; quota is resolved per scope per period.
- [ ] Background / consolidation work is billed at the batch-priced tier, not the interactive tier.
- [ ] Crossing a quota raises the ADR-051 "approve more?" gate; on approval the work proceeds, absent
      approval it is held (not silently dropped, not hard-errored).
- [ ] Rate-limiting is enforced per principal and is independent of token quota (a principal can be
      blocked by one while clear on the other).
- [ ] Every token charge is attributed to its scope and is reportable per user / team / period.

## Consequences

- ADR-054 and ADR-068 gain a single coherent spend story: task ceiling, scope quota veto, batch tier.
- Hitting a limit degrades to an approval prompt, preserving the ADR-051 human-in-the-loop posture
  instead of surfacing opaque failures.
- Per-scope attribution makes spend observable, which is the precondition for tuning quotas later.

## Out of scope

- Concrete quota values, period lengths, and rate-limit numbers (tuning; per-deployment config).
- The pricing tables / batch-tier discounts of specific providers.
- Multi-tenant quota partitioning — Stronghold (ADR-019).
