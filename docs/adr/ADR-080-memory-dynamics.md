---
id: ADR-080
title: "Memory Dynamics — decay, reinforcement, tiers, consolidation, and cross-scope sharing"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-05-30
substrate:
  - maistro-engine#ADR-013
  - maistro-engine#ADR-016
implements: []
related:
  - maistro-engine#ADR-015
  - maistro-engine#ADR-017
  - maistro-engine#ADR-057
  - maistro-engine#ADR-068
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
layer: Memory
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-30
  - status: Implemented
---

# ADR-080: Memory Dynamics

**Status:** Proposed
**Date:** 2026-05-30
**Specifies the behavioral dynamics** of the ADR-013/016 memory tiers — how weight decays and is
reinforced, how memories consolidate, and how they cross scope boundaries — that the tier model
defines structurally but leaves dynamically unspecified.

---

## Context

ADR-013/016 define seven memory tiers and their weight bounds, ADR-068 defines the scope axes, and
ADR-057 defines memory exposure mode — but the *dynamics* are undocumented: when does a memory decay,
what does feedback do to it, when does consolidation run, and how does a memory move from one scope to
a wider one. "Memory must forget" (Key Design Decision 5) is a slogan without a mechanism. This ADR
specifies the three behavioral pieces: decay + reinforcement, consolidation, and cross-scope sharing
under consent.

## Decision

### (A) Decay + reinforcement

Most memories **weight-decay over time unless refreshed**. Every **access refreshes the decay timer**
(a read keeps a memory alive). Feedback steers both weight and decay rate:

- A **thumbs-up** massively boosts the memory's weight **and** slows its decay rate.
- A **thumbs-down** drops its score **and** speeds decay.

**Cumulative feedback moves a memory between the seven tiers** (ADR-013/016): enough positive
reinforcement **promotes it to WISDOM**, enough negative **demotes it to REGRET**. **WISDOM and REGRET
never decay to zero** — they have a permanent weight floor (per ADR-016 `WEIGHT_BOUNDS`: REGRET floor
`0.6`, WISDOM floor `0.9`) and are structurally unforgettable.

```python
def on_access(m: Memory) -> None:
    m.decay_timer = now()                                # access refreshes

def on_feedback(m: Memory, signal: Literal["up", "down"]) -> None:
    if signal == "up":
        m.weight *= BOOST; m.decay_rate *= SLOW          # boost + slow decay
    else:
        m.weight *= DROP;  m.decay_rate *= FAST           # drop + speed decay
    m.tier = reclassify(m.cumulative_feedback)            # may promote→WISDOM / demote→REGRET

WEIGHT_FLOOR = {"REGRET": 0.6, "WISDOM": 0.9}            # ADR-016 WEIGHT_BOUNDS; never decays below
```

### (B) Consolidation

Consolidation runs **overnight on spare compute using batch-priced tokens** (cost-optimised), **and
additionally fires immediately whenever a contradiction is detected** (event-driven). Writes are
**incremental** — amend in place, **never full replacement**:

- Semantically-similar memories **merge** (weighted by their current weights).
- A **contradiction lowers both sides' confidence** and **flags them for review** rather than
  silently picking a winner.

### (C) Cross-scope sharing + consent

A memory **defaults to its origin scope** (ADR-013/068 axes `global > org > team > user > agent >
session`). Promotion to a **wider** scope is gated by a **proactive consent task**: the system
surfaces *"you learned X, should we share that with the team?"* and the **owner/admin approves** before
the memory widens.

Reads are **your own scope + anything explicitly shared at-or-above you**. A **cross-agent read
requires the owner to mark the memory shareable** — nothing leaks across the agent boundary by default.

```python
def can_read(reader: Principal, m: Memory) -> bool:
    return m.scope == reader.scope or (m.shared and m.scope >= reader.scope)

def propose_widen(m: Memory, target: Scope) -> ConsentTask:
    return ConsentTask(prompt=f"You learned {m.summary}; share with {target}?", approver=m.owner)
```

### (D) Retrieval ranking

At recall, memories are ranked by a **hybrid** score, scaled by the memory's current weight:

```
score = (bm25_relevance + vector_similarity) * memory_weight
```

The lexical term (BM25 / pg_trgm) catches exact and id/keyword matches; the vector term (embeddings
per ADR-079) catches semantic/paraphrase matches; multiplying by `memory_weight` surfaces
reinforced/wisdom memories first and suppresses decayed ones. Return the top-k. This pins ADR-016's
under-specified "weight x word-overlap" retrieval.

## Acceptance criteria

- [ ] Memories weight-decay over time unless refreshed; every access refreshes the decay timer.
- [ ] A thumbs-up boosts weight and slows decay; a thumbs-down drops score and speeds decay.
- [ ] Cumulative positive feedback can promote a memory to WISDOM; cumulative negative can demote to
      REGRET (tier transitions follow ADR-013/016).
- [ ] WISDOM and REGRET never decay to zero: REGRET stays ≥ 0.6 and WISDOM ≥ 0.9 (ADR-016
      `WEIGHT_BOUNDS`).
- [ ] Consolidation runs overnight on batch-priced tokens and also fires immediately on a detected
      contradiction; writes are incremental (amend in place), never full replacement.
- [ ] Similar memories merge weighted; a contradiction lowers both sides' confidence and flags for
      review rather than discarding either.
- [ ] A memory defaults to its origin scope; widening to a broader scope requires a proactive consent
      task approved by the owner/admin.
- [ ] Reads return the reader's own scope plus memories explicitly shared at-or-above them; a
      cross-agent read requires the owner to mark the memory shareable.

## Consequences

- "Memory must forget" becomes a concrete mechanism: decay + access-refresh + feedback-driven rate.
- WISDOM/REGRET are durable by construction — hard-won lessons and scars survive disuse.
- Consolidation cost is bounded (overnight, batch-priced) while contradictions still get immediate
  attention (event-driven), and incremental writes keep history rather than clobbering it.
- No memory crosses a scope or agent boundary without an explicit, owner-approved consent step.

## Out of scope

- The concrete decay curve, boost/drop multipliers, and rate constants (tuning detail; follow-up SPEC).
- The contradiction-detection and semantic-similarity algorithms themselves.
- The on-disk schema of the memory store and the consent-task queue.
- Multi-tenant memory partitioning — Stronghold (ADR-019).

## Follow-up

maistro-engine#SPEC-062126-5d56 resolves the decay curve as a pluggable `DecayStrategy` protocol
(default: exponential half-life), and resolves contradiction review as LLM-mediated
auto-resolution gated by a confidence threshold that starts unreachable and decays toward
a tunable `median(resolution_confidence) + admin_offset` asymptote — the same cold-start
shape already used by RLPHD's theta schedule (maistro-engine#SPEC-248).
