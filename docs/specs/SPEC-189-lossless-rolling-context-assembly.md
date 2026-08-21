---
id: SPEC-189
title: "Lossless rolling context assembly — own-the-loop context engine for mAIstro"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-05-30
substrate:
  - maistro-engine#ADR-031
implements: []
related:
  - maistro-engine#SPEC-186
  - maistro-engine#ADR-016
  - maistro-engine#ADR-034
  - maistro-engine#ADR-048
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-30
---

# SPEC-189: Lossless Rolling Context Assembly

## Context

mAIstro owns its own agent loop, which means context management is **prompt assembly, not deletion**.
Unlike a hosted harness (Claude Code, Cursor) where compaction is a fixed, opaque, lossy event you're
a guest of, mAIstro controls exactly what goes into each model call. So the right model is not "trim
old messages" but "**keep everything, and choose what to send.**" The full transcript stays in the
session store; older turns are simply not re-sent — they're replaced in the prompt by a structured
running summary, while remaining recoverable in full on demand.

This is the context engine for mAIstro-as-a-harness. The `recency-summary` skill (a personal
Claude-Code/Cursor tool) prototypes the *methodology*; this spec is the *native* implementation in
mAIstro's `ContextBuilder`, where it can be lossless, cache-pinned, and citation-addressable because
we own the loop.

## Goals

1. **Lossless:** never destroy conversation history; the running summary is a recomputable projection,
   not a replacement.
2. **Rolling/incremental:** fold the oldest content into the summary continuously as the conversation
   grows — no disruptive one-shot compaction, and never re-summarize the whole transcript.
3. **Cheap:** summarize each chunk roughly once; keep the summarized prefix cache-pinned so only the
   changing tail is re-paid per turn.
4. **Re-hydratable:** the summary carries citations to source ranges so full detail can be pulled back
   precisely on demand; semantic search is the fallback.

## Non-goals

- A hosted-harness integration (Claude Code hooks etc.) — out of scope; mAIstro replaces that host.
- The summarization *methodology* itself (recency bands + topic summaries + forward block + fidelity
  levels) — that's defined by the `recency-summary` skill / shared summary engine; this spec consumes
  it.
- Embedding/index infrastructure — reused from SPEC-186, not re-specified here.

## Decision

### State (in `SessionStore`)
- **`transcript`** — the complete, append-only message history. **Never truncated.** Persisted to disk
  so it survives restarts (extends `sessions/store.py`, currently in-memory with `max_messages`/TTL —
  `max_messages` becomes a *window* hint for assembly, not a deletion bound).
- **`running_summary`** — a cached structured summary (recency bands + topic summaries + forward block,
  per the shared summary engine) of the messages *outside* the verbatim window. Each band/topic
  carries a **citation** to the transcript range it compresses (message ids/offsets).
- **`fold_watermark`** — index of the newest message already folded into `running_summary`.

### Assembly (in `ContextBuilder`)
Each turn, `ContextBuilder` assembles the prompt as:

```
[ pinned system ]  +  [ running_summary ]  +  [ verbatim tail (messages newer than the window) ]
```

The old messages are present in `transcript` but simply not included. Nothing is lost; the prompt is a
*view*.

### The fold (incremental, downstream-aware)
When `tokens(assembled prompt) > trigger_tokens`, fold the oldest messages that are beyond
`verbatim_window` (up to `fold_chunk`) into `running_summary`:
- The fold is a summarizer call (cheap `summarizer_model`) given **`running_summary` + the chunk + the
  recent tail** as context — so it is *downstream-aware* (it keeps what later turned out to matter).
- It **updates** the running summary (topic summaries accrete; recency bands shift; citations
  extended), rather than regenerating from scratch.
- Advance `fold_watermark`. The chunk's raw messages stay in `transcript`.
- Because `running_summary` is derivable from `transcript`, it is a cache — recomputable any time;
  the fold is purely an optimization to avoid re-summarizing.

### Re-hydration
When the current task needs detail on something the summary covers:
1. **Citation (primary):** the band/topic cites a transcript range → pull those exact messages from
   `transcript`. Precise and cheap.
2. **Semantic search (fallback):** when the relevant range is unknown, search the retained transcript
   via SPEC-186's embeddings/store and pull the best-matching messages.
Re-hydrated content is injected at the **tail position** (after the cached summary prefix), so it only
costs a cache miss on turns where re-hydration actually happens — not continuously.

### Cache discipline
The `[pinned system + running_summary + folded-old]` prefix is **stable across turns** and should be
cache-pinned; only the verbatim tail (and any re-hydration block) varies. This is the core efficiency
win that a hosted harness cannot offer: history is folded once and then rides as a cached prefix,
versus a cold full re-read per compaction.

### Parameters (configurable; sensible defaults)
- `trigger_tokens` — assembled-prompt size that fires a fold.
- `verbatim_window` — recent tokens/turns kept raw.
- `fold_chunk` — how much oldest-beyond-window to fold per pass.
- `fidelity` — `low | medium | high` (per the shared summary engine), trading summary size vs. detail.
- `summarizer_model` — cheap model for folds.

## Integration points (verify exact signatures at implementation time)
- `packages/maistro-core/src/maistro/agents/context_builder.py` — `ContextBuilder` is the assembly seam.
- `packages/maistro-core/src/maistro/sessions/store.py` — `InMemorySessionStore` extended to retain the
  full transcript + persist it; `max_messages` reinterpreted as the verbatim window.
- `packages/maistro-core/src/maistro/protocols/embeddings.py` + SPEC-186 store — semantic re-hydration.
- Shared summary engine — the `recency-summary` methodology (recency bands + topic summaries + forward
  block + citations + fidelity levels).

## Acceptance criteria

- [ ] The transcript is never truncated: after many folds, every original message is still retrievable
      from `SessionStore` (asserted) and survives a process restart (persisted).
- [ ] `ContextBuilder` assembles `system + running_summary + verbatim_tail`; messages older than the
      window are absent from the prompt but present in the transcript.
- [ ] A fold triggers at `trigger_tokens`, summarizes only the chunk beyond `verbatim_window` (not the
      whole transcript), advances `fold_watermark`, and *updates* (not regenerates) `running_summary`.
- [ ] `running_summary` is recomputable: recomputing from the full transcript yields an equivalent
      summary to the incrementally-folded one (within fidelity tolerance) — proving it's a cache.
- [ ] Citations resolve: a band/topic citation maps to the exact transcript range it summarizes, and
      re-hydrating it returns those messages.
- [ ] Semantic re-hydration returns relevant prior messages for a query whose range isn't cited.
- [ ] Cache stability: across consecutive turns with no re-hydration, the assembled prefix
      (`system + running_summary`) is byte-stable (cache-pinnable); a re-hydration turn perturbs only
      the tail region.
- [ ] `fidelity` low/medium/high produce progressively larger running summaries; `low` still preserves
      the forward-looking/open items (never sacrificed to budget).

## Testing
- Unit: fold trigger + watermark advance; running-summary update vs full recompute equivalence;
  citation→range resolution; parameter handling.
- Contract: `ContextBuilder` assembly output shape; `SessionStore` retain/persist/retrieve.
- Integration: simulate a long session crossing several `trigger_tokens` boundaries → assert losslessness,
  prefix cache-stability, and successful citation + semantic re-hydration.
- Property (formal/): "no message is ever unrecoverable after any number of folds"; "assembled prompt
  never includes a message older than the window except via explicit re-hydration."

## Open questions
- Persistence backend for the transcript (SQLite via the existing store pattern vs. the SPEC-186
  pgvector store doubling as transcript home).
- Whether folds run synchronously on the triggering turn (latency) or async between turns (staleness
  window).
- Re-hydration eviction: when does re-hydrated detail leave the tail again (TTL? next fold?).
- Interaction with multi-tenant scopes (`memory/scopes.py`) for per-user/session transcript isolation.

## References
- [SPEC-186: Knowledge aggregator + cache](SPEC-186-knowledge-aggregator-cache.md) — shared embeddings/
  store for semantic re-hydration; same summary-engine lineage.
- [ADR-016: episodic store](../adr/ADR-016-episodic-store.md)
- [ADR-034: memory canonical ownership](../adr/ADR-034-memory-canonical-ownership.md)
- [ADR-048: session search](../adr/ADR-048-session-search.md)
- Methodology prototype: the `recency-summary` personal skill (recency bands + topic summaries +
  forward-looking block + `low/med/high` fidelity + source citations).
- Note: SPEC-188 is reserved for the `self_repair` loop referenced by SPEC-187.
