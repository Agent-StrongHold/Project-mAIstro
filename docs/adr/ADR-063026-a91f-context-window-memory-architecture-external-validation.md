---
id: ADR-063026-a91f
title: "Context windows are not memory — external validation of the Layer 0-4 / SessionStore architecture"
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-06-30
substrate:
  - maistro-engine#ADR-080
  - maistro-engine#ADR-091
implements: []
related:
  - maistro-engine#SPEC-189
  - maistro-engine#SPEC-193
  - maistro-engine#SPEC-244
  - maistro-engine#SPEC-186
supersedes: []
blocks: []
blocked-by: []
contracts: []
tests: []
layer: Memory
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-06-30
---

# ADR-063026-a91f: Context windows are not memory

## Context

["Context Windows Are Not Memory: What AI Agent Developers Need to Understand"](https://machinelearningmastery.com/context-windows-are-not-memory-what-ai-agent-developers-need-to-understand/)
makes a thesis that is easy to nod along with and easy to violate in practice: a model is stateless —
every call starts at "step zero" — so a large context window is a scratchpad, not persistent memory.
Treating the prompt as the memory system produces three concrete failures the article names:

1. **Recency bias** — models weight the start/end of a prompt and skim the middle.
2. **Snowballing** — naive transcript accumulation makes every turn resend an ever-growing history.
3. **Latency** — bloated prompts delay time-to-first-token.

It recommends four techniques: **RAG** (retrieve just-in-time, reconcile contradictions before
generation rather than asking the model to referee them), **compression** (algorithmic token
reduction, e.g. LLMLingua), **summarization with forked storage** (persist the raw transcript
separately, summarize only for the active prompt), and **persistent state with a query-commit
discipline** (agents as "database administrators, not databases" — read state in, write state out,
external store of record).

mAIstro already has ADR-080 (memory dynamics), ADR-091 (Layer 0-4 context assembly), and SPEC-189
(lossless rolling context assembly) on the books, all `Proposed`. This ADR is the gap check: does the
existing design actually satisfy the article's thesis, or are we still implicitly treating the prompt
as memory anywhere?

## Decision

Record the mapping from the article's recommendations to existing mAIstro decisions, and call out the
one real gap found.

| Article recommendation | mAIstro mechanism | Status |
|---|---|---|
| Models are stateless; the prompt is a scratchpad, not memory | ADR-091 Level 1/Level 2 split: storage types (`EpisodicMemory`, `Outcome`, etc.) are canonical state; the Layer 0-4 taxonomy is *only* a read-time assembly view over them | Covered |
| RAG: retrieve just-in-time | ADR-091 `ContextAssemblyPolicy.layer1/layer3` (scoped episodic + `Outcome` retrieval per turn); SPEC-189 citation + semantic re-hydration | Covered |
| RAG: reconcile contradictions before generation, not at inference time | ADR-080(B) — contradictions lower both sides' confidence and are flagged for review at consolidation time, not left for the model to silently arbitrate at generation time | Covered |
| Summarization with forked storage (raw transcript kept separately from the summarized view) | SPEC-189 — `transcript` is append-only and never truncated; `running_summary` is an explicitly recomputable *projection* with per-band citations back to the raw range | Covered |
| Persistent state, query-commit discipline ("DBA, not database") | ADR-091 Layer 1 (load) / Layer 3 (`Outcome` changelog, write) + ADR-080(A) `on_access`/`on_feedback` hooks as the commit path | Covered |
| Algorithmic compression of retained content (e.g. LLMLingua-style token reduction, distinct from LLM summarization) | None found in ADR-080/091/SPEC-189/SPEC-193/SPEC-244 | **Gap** |

The gap: every existing mechanism reduces tokens by *summarizing* (an LLM call producing an
abstraction) or by *excluding* (tier/scope/budget filtering). None of them reduce tokens by
*compressing* the verbatim tail or low-fidelity summary bands themselves — the technique the article
calls out separately from summarization (prompt compression that preserves the original token
sequence's information density without an LLM rewrite pass). SPEC-189's `fidelity: low|medium|high`
controls how much gets *kept*, not how densely the kept portion is *encoded*.

This gap is recorded here rather than closed: it needs its own SPEC (estimating real benefit
requires measuring SPEC-189's actual verbatim-tail token cost once implemented) and is added to
`DECISION-BACKLOG.md` as a follow-up candidate, not specified inline in this ADR.

## Consequences

### Positive
- Confirms ADR-080/ADR-091/SPEC-189 — all still `Proposed` — already satisfy the article's core
  thesis and all but one of its four recommended techniques, with no schema or design changes
  required as a result of this review.
- Gives a citable external cross-check for reviewers asking "why does mAIstro need a whole memory
  subsystem instead of just a bigger context window?"

### Negative / Trade-offs
- The compression gap is identified but not resolved here; until a follow-up SPEC lands, the
  verbatim tail and low-fidelity summary bands in SPEC-189 are not token-compressed beyond what
  summarization/fidelity already does.

### Neutral
- No code changes. This ADR is a documentation/validation artifact cross-referencing prior decisions
  against an external source.

## Out of scope

- Selecting or implementing a specific compression algorithm (LLMLingua or otherwise) — deferred to
  the follow-up SPEC noted in `DECISION-BACKLOG.md`.
- Re-litigating ADR-080/ADR-091/SPEC-189 design choices — this ADR validates, it does not amend them.
