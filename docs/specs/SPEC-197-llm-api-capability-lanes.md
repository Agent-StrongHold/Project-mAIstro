---
id: SPEC-197
title: LLM API capability lanes
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-06-08
accepted: 2026-06-08
substrate:
  - maistro-engine#ADR-079
  - maistro-engine#ADR-038
implements: []
related:
  - maistro-engine#SPEC-176
contracts:
  - boundary
tests:
  - packages/hive-conductor/backend/tests/test_chat_streaming.py
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-197: LLM API capability lanes

## Context

Hive Conductor's chat path (`/v1/chat/stream` → `run_chat_completion_streaming` → `LLMPort`) talks to a single **LiteLLM gateway** (`build_llm_port()`), but LiteLLM is **multi-ingress**: it exposes `chat/completions`, the OpenAI **Responses API** (`/responses`), and the Anthropic **Messages API** (`/v1/messages`). `chat.completions` is the lowest-common-denominator dialect; each provider's native surface unlocks features it flattens (persisted reasoning, prompt caching, citations, realtime multimodal).

The `LLMPort` is the convergence seam — the place to hide *which* dialect we speak from everything above it (the streaming generator, the chat UI, downstream enterprise teams). This spec defines that seam as a set of **lanes**.

## Decision

**One normalized streaming contract above the port; ingress "lanes" below it, selected per-model.** Every lane routes through LiteLLM, so routing, key management, and observability are preserved (no direct-to-provider egress).

### Internal streaming contract (lane-agnostic)

Events yielded by `run_chat_completion_streaming` and consumed by the frontend:

| event | meaning |
|-------|---------|
| `status` | coarse progress ("Processing tool results…") |
| `delta` | a content token (append on the client) |
| `thinking` | a reasoning/thinking token |
| `tool_call` / `tool_result` | a tool executing / its summary |
| `citation` *(future)* | a grounded source span |
| `done` | terminal; carries full content as a fallback |

Adapters translate each native dialect into this vocabulary. Tool-call fragments are reassembled by `_ToolCallAccumulator`; Responses events by `_responses_event_to_chunk`.

### Lane selection

Generalize the existing `llm_http_variant` setting into a **per-model capability map** (model → preferred lane + supported features), defaulting to `chat.completions`. `build_llm_port()` chooses the lane; nothing above the port changes. Fallback is per **ADR-038** (a failed Responses call under `auto` degrades to `chat.completions`); model→lane policy is per **ADR-079**.

## Lanes

| Lane | Maps via | Unlocks | Status |
|------|----------|---------|--------|
| **chat.completions** *(default, universal)* | `delta.content`→`delta` · `delta.reasoning_content`→`thinking` · `delta.tool_calls`→`tool_call` | works across the whole routed fleet (Qwen/Llama/Claude/GPT via LiteLLM), incl. reasoning + caching passthrough | **Implemented** |
| **Responses** (GPT-5.x) | `output_text.delta`→`delta` · `reasoning_summary_text.delta`→`thinking` · `response.completed`→done | persisted reasoning across tool turns, hosted tools, server-side state | **Implemented** (content + reasoning; tool-free path) |
| **Messages** (Claude) | `content_block_delta{text/thinking/input_json}` → `delta`/`thinking`/`tool_call` · citations → `citation` | streamed extended thinking, `cache_control` prompt caching, citations | **Backlog** |
| **Live** (Gemini realtime) | own WebSocket session; adds an `audio` event beyond the SSE contract | realtime bidirectional voice/video | **Backlog** (own track) |

## Status & phasing

### Implemented (2026-06-08) — short-term increment

- **Lane #1 — reasoning/thinking streaming.** Both streaming loops in `run_chat_completion_streaming` emit `thinking` events from `delta.reasoning_content` (LiteLLM normalizes reasoning across providers). Frontend (`Chat.tsx`) renders a collapsible "💭 Reasoning" block. Universal — works for any reasoning-capable routed model without changing ingress.
- **Lane #2 — Responses lane.** `HttpOpenAIProtocolLLM.stream()` is `variant`-aware, mirroring `complete()`: tool-free requests under `variant` ∈ {auto, responses} stream `/responses` (typed events normalized via `_responses_event_to_chunk`); an `auto` request whose Responses call fails degrades to `chat.completions`.
- Tests: `tests/test_chat_streaming.py` (assembler, content-only, tool-call→answer, thinking emission, Responses normalization).

### Backlog

- **[Lane #3] Anthropic Messages lane** — a `LLMPort` adapter that POSTs LiteLLM's `/v1/messages` for **pinned-Claude** models. Acceptance:
  - map `content_block_delta` → `delta` (`text_delta`), `thinking` (`thinking_delta`), `tool_call` (`input_json_delta`); `message_stop` → `done`;
  - emit `citation` events from Anthropic citation blocks;
  - express `cache_control` breakpoints on system/tools/long context (the cost lever);
  - gated by the per-model capability map (Messages only when the routed model is Claude);
  - field-coverage verified against the deployed LiteLLM version first.
- **[Lane #4] Gemini Live realtime lane** — a **separate WebSocket adapter** (not the SSE `stream()` path) for realtime bidirectional voice/video. Acceptance:
  - new transport + a new `audio` event in the contract;
  - thinking/grounding mapped where available;
  - **security/audit:** bidirectional audio is a new logging/consent surface — requires its own review and likely graduates to a dedicated SPEC when scheduled.

## Non-goals / posture

- **No direct-to-provider egress.** All lanes go through the LiteLLM gateway; speaking a native dialect *to LiteLLM* keeps control/observability (it is a dialect choice, not a control trade).
- Native dialects only pay off when the routed model supports the feature (e.g., Messages → Claude thinking/`cache_control`); for the heterogeneous default fleet, `chat.completions` + `reasoning_content` is the pragmatic universal lane.
- Exact field names (`reasoning_content`, `cache_control`, `thinkingConfig`, Responses event types) are subject to LiteLLM version coverage and should be confirmed against the deployed gateway before each lane lands.

## References

- `packages/hive-conductor/backend/services/chat_completion.py` — `run_chat_completion_streaming`, `_ToolCallAccumulator`
- `packages/hive-conductor/backend/adapters/llm_http.py` — `HttpOpenAIProtocolLLM.stream`, `_responses_event_to_chunk`
- `packages/hive-conductor/backend/protocols/llm.py` — `LLMPort`
- maistro-engine#ADR-079 (model registry / routing), maistro-engine#ADR-038 (reliability / fallback), maistro-engine#SPEC-176 (Hive Conductor package)
