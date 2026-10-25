---
id: SPEC-194
title: Ultra Think — tiered parallel diverse generation
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-06-02
accepted: null
implemented: null
substrate:
  - maistro-engine#ADR-094
  - maistro-engine#ADR-038
  - maistro-engine#ADR-088
implements: []
related:
  - maistro-engine#SPEC-193
  - maistro-engine#SPEC-195
  - maistro-engine#ADR-091
contracts:
  - boundary
  - behavioral
tests:
  - apps/conductor-gateway/tests/test_ultra_think.py
  - packages/maistro-core/tests/agents/test_ultra_think_tiers.py
layer: Agents
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-06-02
---

# SPEC-194: Ultra Think tiered parallel diverse generation

## Context

Single-pass generation fails on hard tasks: one model call at one temperature
produces one candidate. Beam search at inference time — multiple diverse completions
in parallel, scored by a reviewer — dramatically improves first-attempt acceptance
rate at the cost of latency and token spend.

The Conductor snapshot implements this as "Ultra Think": N candidates generated
concurrently with varied sampling parameters and system-prompt suffixes, then returned
to the orchestrator for evaluation. It works. The problem is cost: tier 3 (N=5) burns
5× the tokens and slots of a single-pass call, and calling it indiscriminately on
easy tasks is wasteful.

**This spec defines the tier model, diversity profiles, cost controls, and integration
points.** The infrastructure (slot management, KV cache) is SPEC-193. Training data
capture is SPEC-195.

## Decision

### Tier taxonomy

| Tier | N candidates | Use when | Relative cost |
|------|-------------|----------|--------------|
| 1 | 1 | Simple / retrieval / well-specified | 1× |
| 2 | 3 | Standard coding / moderate complexity | 3× |
| 3 | 5 | Hard / ambiguous / high-stakes | 5× |
| 4 | — | Decompose + escalate (out of scope v1) | variable |

Tier 4 means the task exceeded tier-3 capabilities. In v1 the orchestrator receives
an explicit error signal and is responsible for decomposition; Ultra Think does not
attempt tier-4 autonomously.

### Diversity profiles

Five fixed sampling profiles, cycled across candidates:

| Index | Label | temperature | top_p | top_k | presence_penalty |
|-------|-------|-------------|-------|-------|-----------------|
| 0 | conservative | 0.7 | 0.90 | 30 | — |
| 1 | standard | 1.0 | 0.95 | 40 | — |
| 2 | exploratory | 1.2 | 0.98 | 50 | — |
| 3 | creative | 1.0 | 0.95 | 40 | 0.3 |
| 4 | focused | 0.8 | 0.85 | 20 | — |

Each candidate also receives a distinct **system prompt suffix** (one of five
directives: readability, performance, robustness, simplicity, edge-case handling)
appended to the **first** system message in the message array. If no system message
exists, one is inserted at position 0 containing only the suffix. This doubles the
diversity signal without changing the task.

For N > 5, profiles wrap around. Tier 2 always uses indices 0–2; tier 3 uses 0–4.

### Execution model

```
1. Acquire N worker slots from SlotManager pool (SPEC-193)
2. Restore template KV cache into each worker in parallel (asyncio.gather)
   — restore failures are non-fatal: log WARNING, generation proceeds
3. Fire N chat/completions requests in parallel, each pinned to its slot (id_slot)
   with its assigned diversity profile + system suffix
4. Collect results: successes → CandidateCompletion; failures → error log
5. Release ALL slots in finally block regardless of outcome
6. Return UltraThinkResult to caller (orchestrator / reviewer)
```

### Cost controls

These controls are **new additions in this spec** — the Conductor snapshot has none
of them. They must be implemented when porting, not assumed to exist in the reference code.

These are **hard limits** applied before any LLM call is made.

| Control | Mechanism | Default |
|---------|-----------|---------|
| `max_tier` per request | Optional field in `UltraThinkRequest`; gateway returns HTTP 422 if `tier > max_tier` | unset (no cap) |
| `max_tier` per project | Set in `conductor.yaml`; enforced at request time | 2 |
| Daily token budget | `maistro.quota.InMemoryQuotaTracker` checked before slot acquisition; returns HTTP 429 with `Retry-After` header when exhausted | configurable |
| Slot availability | Worker pool blocks callers up to `generation_timeout_seconds`; timeout raises HTTP 503, not a silent tier fallback | — |

**Tier 4 is not supported in v1.** A request with `tier=4` returns HTTP 422
(`"tier 4 requires decomposition; not supported in v1"`). The snapshot silently
mapped tier 4 to tier 3 defaults — this spec explicitly rejects it instead.

**There is no automatic tier escalation in v1.** The orchestrator decides the tier
explicitly based on its complexity heuristic. Auto-escalation on retry is a v2 feature.

### API shape (`/v1/ultra-think`)

Request:
```json
{
  "task_id": "...",
  "messages": [...],
  "project_id": "...",
  "tier": 2,
  "max_tokens": 4096,
  "n_candidates": null,
  "max_tier": 2
}
```

`n_candidates` overrides the tier default when set (e.g. `n_candidates=2` with `tier=3`
uses exactly 2 candidates instead of 5). Useful for budget-sensitive callers that still
want tier-3 diversity profiles but fewer slots.

Response:
```json
{
  "task_id": "...",
  "tier": 2,
  "candidates": [
    {
      "candidate_id": "task-c0-a1b2c3d4",
      "slot_id": 1,
      "content": "...",
      "sampling_params": {"temperature": 0.7, "top_p": 0.9, "top_k": 30},
      "system_prompt_variant": "Prioritize readability and maintainability.",
      "tokens_generated": 843,
      "generation_time_ms": 9200.0,
      "tokens_per_second": 91.6
    }
  ],
  "timing": {
    "slot_restore_ms": 48.1,
    "parallel_generation_ms": 11400.0,
    "total_ms": 11460.0,
    "prefix_tokens_cached": 1024,
    "suffix_tokens_per_candidate": [843, 901, 772]
  },
  "errors": []
}
```

Partial success (some candidates failed) returns HTTP 200 with non-empty `errors`
array. The orchestrator decides whether to retry or proceed with fewer candidates.
All-candidates-failed returns HTTP 500.

### Tier estimation heuristic (v1)

The orchestrator should select tier using this simple heuristic until a learned
difficulty model exists (see DECISION-BACKLOG):

| Signal | Tier |
|--------|------|
| Short retrieval / lookup / simple fix | 1 |
| Multi-step coding, spec-to-code, refactor | 2 |
| Architecture design, ambiguous requirements, novel algorithm | 3 |

Projects may override the default tier in `conductor.yaml` (`default_tier: 1`).

### Reviewer integration

Ultra Think returns candidates. **Selection is the caller's responsibility.**
The orchestrator is expected to:

1. Score each candidate with a reviewer prompt (correctness, style, robustness,
   simplicity, testability — five axes, 0–10 each).
2. Run tests if available; a candidate that fails tests cannot be accepted regardless
   of reviewer score.
3. Select the candidate with the highest passing score above `accept_threshold`
   (default 7.0, configurable per project).
4. Record the full cycle to TrainingDataCollector (SPEC-195).

If no candidate passes the threshold, the orchestrator may retry at the same tier
or escalate (v1: manual; v2: automatic).

The reviewer scoring rubric and `accept_threshold` are out of scope for this spec;
they belong to the orchestrator layer.

## Cost note

Tier 3 on a P40 at 32K context burns approximately 5× the tokens, 5× the slot-time,
and ~1.4× the wall-clock time (parallel, not serial) of tier 1. For a 4096-token
generation at 90 tok/s this is ~22s and ~20K output tokens. Budget accordingly.
The quota tracker should alert or hard-stop before daily limits are exhausted, not
silently degrade.

## Reference bundle

Reference implementation in git history at `d6603c9^`,
path `potential-dead-code/code-worth-implementing-from-Conductor/snapshot/gateway/ultra_think.py`.
Port to `apps/conductor-gateway/gateway/ultra_think.py` per SPEC-193.

The tier taxonomy, diversity profiles, and slot-restore pattern are stable and should
be ported verbatim. The cost controls and reviewer integration are new in this spec.

## Acceptance criteria

1. **Tier 1** — single candidate returned; only one worker slot acquired and released.
2. **Tier 2** — three candidates returned in parallel; wall-clock ≈ slowest single
   generation (not 3×).
3. **Tier 3** — five candidates returned; all five diversity profiles appear in
   `sampling_params` across the candidate list.
4. **max_tier enforcement** — request with `tier=3, max_tier=2` returns HTTP 422.
5. **Tier 4 rejected** — request with `tier=4` returns HTTP 422 with a message
   referencing decomposition.
6. **n_candidates override** — request with `tier=3, n_candidates=2` produces exactly
   two candidates using diversity profiles 0 and 1.
7. **Slot release on partial failure** — if two of three tier-2 generations fail,
   all three slots are released; `errors` has two entries; one candidate is returned.
8. **Restore non-fatal** — if template restore fails for one slot, generation still
   proceeds for that slot; the error is in the log, not in the `errors` array (restore
   failure ≠ generation failure).
9. **Quota gate** — when daily token budget is exhausted, the endpoint returns 429
   with a `Retry-After` header before acquiring any slots.
10. **System prompt suffix on first message** — the first candidate's first system
    message content ends with the suffix from `SYSTEM_PROMPT_SUFFIXES[0]`.
11. All tests use a mock llama-server; no real GPU required in CI.
