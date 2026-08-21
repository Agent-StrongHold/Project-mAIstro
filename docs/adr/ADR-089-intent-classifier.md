---
id: ADR-089
title: "Intent Classifier — thresholded escalation and multi-intent routing"
repo: maistro-engine
kind: adr
status: Accepted
accepted: 2026-06-10
created: 2026-05-30
substrate: []
implements: []
related:
  - maistro-engine#ADR-007
  - maistro-engine#ADR-010
  - maistro-engine#ADR-071
  - maistro-engine#ADR-078
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
  - status: Accepted
    date: 2026-06-10
    date: 2026-05-30
---

# ADR-089: Intent Classifier

**Status:** Proposed
**Date:** 2026-05-30

---

## Context

`maistro.classifier` exists in code (keyword, LLM-fallback, complexity phases) but has no ADR
pinning how the phases compose, how confidence escalation works, or how a compound request with
multiple intents is handled. The router (ADR-007) and planner (ADR-071) consume the classifier's
output, so its contract matters.

## Decision

Three-phase classification with thresholded escalation:

1. **Keyword phase** — a fast deterministic keyword/pattern pass produces a candidate intent + a
   confidence.
2. **LLM-fallback phase** — invoked **only when** the keyword confidence is below a threshold `τ`;
   it resolves the intent with a model call. Cheap common case, smart on the margin.
3. **Complexity phase** — sets the routing tier (which lane / model / budget) from estimated
   complexity (feeds ADR-010 lanes + ADR-079 routing).

**Multi-intent.** A request carrying more than one intent is **split into sub-tasks**, each routed
independently (and recombined by the planner/orchestrator, ADR-071), rather than forced to a single
best intent.

**Thresholds are interpretable config.** `τ` and the complexity-tier cutoffs are explicit,
hand-editable parameters held in the DB config (ADR-078) — the same glass-box principle as RLPHD
(ADR-068) and the planner's plan-scoring (ADR-071): no black-box classifier decision that can't be
read, overridden, and audited.

## Acceptance criteria

- [ ] A high-confidence keyword match resolves without an LLM call (property test: confidence `>= τ`
      never invokes the LLM phase).
- [ ] A low-confidence request escalates to the LLM phase.
- [ ] A multi-intent request is split into independently-routed sub-tasks.
- [ ] `τ` and complexity cutoffs are read from DB config (ADR-078), runtime-editable, auditable.
- [ ] Classifier output (intent, confidence, tier, phase-used) is emitted as an observability event
      (ADR-037).

## Consequences

- The router (ADR-007) and planner (ADR-071) get a stable, tier-annotated intent contract.
- Tuning routing behaviour is a config edit (ADR-078), not a code change.

## Out of scope

- The keyword lexicon / LLM prompt themselves (tuning detail).
- Cross-language intent detection (i18n) — deferred.
