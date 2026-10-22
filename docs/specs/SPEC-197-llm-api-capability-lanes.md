---
id: SPEC-197
title: LLM API capability lanes
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-06-08
accepted: 2026-06-08
substrate:
  - maistro-engine#ADR-038
implements: []
related:
  - maistro-engine#SPEC-176
  - maistro-engine#ADR-079
contracts:
  - boundary
tests:
  - packages/hive-conductor/backend/tests/test_chat_streaming.py
  - packages/hive-conductor/backend/tests/test_hive_admitted_models.py
  - packages/maistro-core/tests/capabilities/test_model_protocol_lanes.py
layer: Orchestration
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-197: LLM API capability lanes

## Context

Hive Conductor's model port (`build_llm_port()` → `LLMPort`) talks to a single **LiteLLM gateway**, but LiteLLM is **multi-ingress**: it exposes `chat/completions`, the OpenAI **Responses API** (`/responses`), and the Anthropic **Messages API** (`/v1/messages`). `chat.completions` is the lowest-common-denominator dialect; each provider's native surface unlocks features it flattens (persisted reasoning, prompt caching, citations, realtime multimodal).

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

Adapters translate each native dialect into this vocabulary. Tool-call fragments are reassembled by `_ToolCallAccumulator`; Responses events by the governed Provider's `ResponsesStream` normalizer.

### Lane selection

Generalize the existing `llm_http_variant` setting into a **per-model capability map** (model → preferred lane + supported features), defaulting to `chat.completions`. `build_llm_port()` chooses the lane; nothing above the port changes. Fallback is per **ADR-038**: under `auto`, an explicitly unsupported Responses ingress may degrade to `chat.completions` only with sufficient non-application evidence. An arbitrary failure does not authorize another physical request. Model→lane policy is set by the per-model capability map defined here (default `chat.completions`); **ADR-079** (model registry / routing, still **Proposed**) is non-authoritative design context for a future registry-driven policy, not governing policy.

### Unsupported ingress and canonical reattempts

The owner clarified the compatibility boundary on **2026-10-05** (#1084):
Responses, Messages or Interactions can fall back to Chat Completions when they
are unsupported. This permission preserves the existing reattempt ontology; it
does not classify every failed native-protocol request as safe to repeat.

- Trusted capability information can select Chat Completions before dispatch.
  Absence of capability information is not a declaration of non-support.
- After dispatch, fallback requires typed evidence for the exact attempted
  ingress proving that no model effect was applied. The failed physical request
  and alternate have separate canonical Invocations with the same logical
  effect identity. The alternate repeats ordinary authority/admission checks
  and retains the model, Binding and credential scope.
- Completed Invocations replay without dispatch. UNKNOWN/active effects remain
  blocked until the canonical reconciliation service applies evidence. Proven
  NOT_APPLIED permits a normal reattempt; APPLIED replays the recorded result;
  INDETERMINATE does not authorize another request. Changing a protocol or an
  Attempt does not clear the effect ledger.
- Bare HTTP errors, auth/quota refusal, timeouts, partial output, empty text,
  malformed SSE or missing completion do not prove unsupported ingress.
  A connection failure can prove non-application without proving non-support.
- A deliberate tool-result continuation or correction after known completion
  remains a distinct, admitted effect. It must not be confused with redispatch
  after an uncertain failure.

The implemented configuration remains `chat_completions`, `responses` and `auto`.
Tool-bearing calls select the supported Chat Completions lane. Explicit
`responses` remains a strict selection; `auto` permits the bounded alternate.
Messages remains backlog and Interactions has no shipped adapter. Permission to
fall back from those protocols does not itself add an integration or a new SDK.
Any future lane must apply the same evidence and authorization contract.

### Explicit capability evidence

The existing provider configuration can declare `supported_ingresses` for a
registered model. This is a capability declaration, not a Binding or permission
change. The global `llm_http_variant` still expresses preference; a per-model
preferred-lane policy is not introduced by this bounded migration.

For example, in the YAML selected by `provider_config_path`:

```yaml
models:
  - name: configured-model
    provider: configured-provider
    cost_input: 0.0
    cost_output: 0.0
    latency_p50_ms: 0
    supported_ingresses: [chat_completions]
```

Omitting the field or setting it to null means unknown. An explicit nonempty list may contain only
implemented ingress names (`chat_completions`, `responses`), without duplicates.
With `auto`, a Chat-only declaration chooses Chat Completions before HTTP.
An explicit Responses choice excluded by the declaration refuses before HTTP;
tool-bearing requests cannot use a declared Responses-only model by silently
dropping tools. A declaration neither changes model selection nor grants access.

For an actual gateway rejection, the Provider recognizes a versioned extension:
HTTP **501** with a body of at most **4096 bytes**, containing exactly:

```json
{
  "error": {
    "type": "maistro.unsupported_ingress.v1",
    "ingress": "responses",
    "model": "<exact locally resolved model alias>",
    "dispatch": "not_started",
    "effect": "not_applied"
  }
}
```

The configured trusted gateway must create this envelope before model dispatch;
it must never pass through upstream/model-generated text as this assertion. The
status, ingress, locally resolved alias and all fields must match. Extra fields,
auth/quota statuses, other server failures and a successful stream's later error
frame do not satisfy this contract. Persisted refusal text is bounded and does
not copy gateway error text.

This is an explicit gateway-extension contract, **not an assertion that stock
LiteLLM or the deployed gateway emits it**. Deployment support has not been
verified. Without a declared capability or this evidence, ambiguous failures
remain subject to canonical reconciliation; a mocked envelope test proves the
consumer contract only.

### Normalized results and public containment

Both implemented lanes retain the requested sampling controls and normalize
content, reasoning and reported usage for existing consumers. The Provider stamps
`_maistro_ingress` on completed/assembled results from its locally selected lane,
overwriting any upstream marker. Completed replay preserves this evidence after
configuration changes. UNKNOWN has no completed result, and historical unmarked
results remain unmarked; this marker does not supply failed-dispatch provenance. Stream completion
requires protocol-level terminal evidence; `response.output_text.done` alone is
not completion of a Responses request. Failed/incomplete responses and broken
streams must not become successful model effects or trigger a blind second call.

The internal tool-capable streaming service and the public route are distinct.
The public `/v1/chat/complete` and `/v1/chat/stream` routes preserve M0 conversation
containment: tools and capability-bearing extra controls are stripped, and the
SSE route returns a final `done` event around the canonical completion. This
provider migration does not enable the dormant public tool-capable loop.

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
- **Lane #2 — Responses lane.** The governed Provider is `api_variant`-aware for both completion and streaming: tool-free requests under `variant` ∈ {auto, responses} stream `/responses` (typed events normalized by `ResponsesStream`); an `auto` request with proved unsupported/non-applied Responses ingress may use `chat.completions`, subject to the clarified canonical admission contract above.
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
- `packages/hive-conductor/backend/adapters/llm_governed.py` — admitted Hive request shaping
- `packages/maistro-core/src/maistro/capabilities/providers/llm_gateway.py` — approved gateway transport and explicit unsupported-ingress evidence
- `packages/maistro-core/src/maistro/capabilities/providers/responses_protocol.py` — Responses completion and stream normalization
- `packages/hive-conductor/backend/protocols/llm.py` — `LLMPort`
- maistro-engine#ADR-079 (model registry / routing; Proposed — design context, not policy), maistro-engine#ADR-038 (reliability / fallback), maistro-engine#SPEC-176 (Hive Conductor package)
