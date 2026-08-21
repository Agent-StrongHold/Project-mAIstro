---
id: ADR-092
title: Capability-vs-control posture
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-06-02
accepted: null
implemented: null
substrate: []
implements: []
related:
  - maistro-engine#ADR-091   # durable execution (a control-reinforcing exception)
  - maistro-engine#ADR-039   # external-adoption policy / INSPIRATIONS
contracts: []
tests: []
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
  - status: Accepted
    date: 2026-06-10
    date: 2026-06-02
---

# ADR-092: Capability-vs-control posture

## Context

Surveying the agent-harness ecosystem (the harness design-space report plus a
catalog of chat-UI, coding-agent, and self-evolving projects), a pattern recurs:
nearly every concept that is *both* "better than ours" *and* "contradicts ours" is
making the **same trade** — **capability for control**, where *control* = security +
interpretability + auditability. We keep re-litigating each such case individually.
This ADR states the posture so we don't.

The axis: **capability ⟷ control.** Tools optimized for an individual / a benchmark /
a demo sit at the capability end; a regulated, multi-tenant, auditable substrate sits
at the control end. The two pull on one dial.

## Decision

maistro deliberately optimizes the **control** end — and is explicit about it:

1. **Accept a capability/smoothness cost for control.** Multi-tenant, gated,
   server-brokered, model-routed, auditable — even when a less-constrained design
   would be more capable or smoother for a single user.
2. **Pay the control tax only where a governance requirement demands it.** Structure
   is a *governance* cost, **not** a capability advantage (the mini-swe-agent lesson:
   a ~100-line agent matches elaborate scaffolds on the task). Don't add structure
   for its own sake; keep a minimal baseline as a control.
3. **Synthesize where a synthesis captures the benefit without abandoning the
   principle** (see worked examples) rather than treating every case as binary.
4. **Audit our own capability-for-control trades.** We are not automatically on the
   virtuous side — e.g., `model="auto"` routing trades *reproducibility* for cost, so
   we also snapshot the resolved model on the trace.

## The framework — worked examples (all = capability-for-control)

| Case | Better on | Contradicts | Posture |
|---|---|---|---|
| **Scaffold-less minimalism** (mini-swe-agent) | simplicity/capability | our node-kind + policy structure | Hold; keep structure only for governance; keep a minimal baseline as the honesty check |
| **Online self-evolution** (Live-SWE-agent) | SOTA capability | auditability + closed node-kind set | **Synthesize:** gated/audited evolution (propose → approve → version), never live-unsupervised |
| **Pin-the-provider determinism** (WebCode) | reproducibility/audit (the *mirror* — they beat us on our own axis) | our `model="auto"` router | **Synthesize:** auto-route by default + allow pin + always snapshot the resolved model |
| **Local full-access autonomy** (OpenCowork/odysseus) | latency/context/privacy for one user | multi-tenant, sandboxed, gated | **Synthesize:** a distinct "trusted local lane" vs. the brokered multi-tenant lane |

## The exceptions — better∧contradicts that are **not** the control trade

These are the only ones that should actually make us *reconsider*, because "but we're
regulated" does not rescue us:

- **Minimal / free-form spec** (AGENTS.md, GitAgent) — axis is *adoption/ergonomics*.
  Resolved: structured core + free-text override + AGENTS.md interop (see the Agent
  Builder spec). The structured schema's job is forcing the builder LLM to collect
  enough to avoid soulless agents — not human-authoring burden.
- **Durable execution** (LangGraph / event-sourcing) — axis is *reliability/state*, and
  it **reinforces** control (audit-by-replay). Resolved upstream: ADR-091.

## Consequences

- **Stops per-case re-litigation.** A contradiction that is a capability-for-control
  trade → hold the line, with eyes open. One that is *not* → genuinely reconsider.
- **"The constraint is the product."** For a regulated substrate,
  security/interpretability/auditability are the value proposition; capability is the
  commodity input every harness gets. Projects that trade control away build a better
  *tool*; we build a *trustable substrate*.
- **Downstream peers inherit this posture** (Fantasia, stronghold, …) — they do not
  re-decide it.

## Status

Proposed.
