---
id: SPEC-285
title: "Incremental streaming through the governed model Invocation (narrow observer seam)"
repo: maistro-engine
kind: spec
status: Implemented
created: 2026-10-24
accepted: 2026-10-24
implemented: 2026-10-24
history:
  - status: Proposed
    date: 2026-10-24
  - status: Implemented
    date: 2026-10-24
substrate:
  - maistro-engine#ADR-081226-6b46
  - maistro-engine#ADR-082326-5386
implements:
  - maistro-engine#ADR-081226-6b46
related:
  - maistro-engine#SPEC-081226-6b46
  - maistro-engine#ADR-079
  - maistro-engine#SPEC-284
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-core/tests/capabilities/test_model_chat_egress.py
  - packages/hive-conductor/backend/tests/test_llm_http_adapter.py
ac-modules:
  AC-1: maistro.capabilities.model_chat
  AC-2: maistro.capabilities.model_chat
  AC-3: maistro.capabilities.model_chat
  AC-4: maistro.capabilities.model_chat
  AC-5: maistro.capabilities.providers.llm_gateway
  AC-6: maistro.capabilities.providers.llm_gateway
source:
  - packages/maistro-core/src/maistro/capabilities/providers/llm_gateway.py
  - packages/maistro-core/src/maistro/capabilities/model_chat.py
  - packages/hive-conductor/backend/adapters/llm_http.py
layer: Ability
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-285: Incremental streaming through the governed model Invocation

## Context

Issue #1084 (bounded work item 3) requires: *"Preserve real incremental
streaming through governed Provider/Invocation lifecycle; specify its narrow
callback/lifecycle design before implementation."* The convergence round
initially shipped the streaming path as **buffer-then-replay**
(`GovernedModelChatClient.stream_chunks` awaited a full governed `complete`,
then replayed the buffered `_stream_chunks`), which satisfied Invocation
truthfulness but not incrementality, and shipped without this design. This
document is the design of record; the implementation in the same change makes
the shipped path match it.

Two facts bound the problem:

- The Invocation lifecycle (admit → dispatch → terminalize) terminalizes only
  after the provider call resolves. A stream resolves only when the wire is
  exhausted, fails, or is abandoned. Terminalizing any earlier would record an
  outcome nobody can prove.
- The shipped Hive `/chat/stream` route deliberately emits one final `done`
  event (M0 containment, `routes/chat.py`), so no shipped consumer lost token
  streaming when the boundary converged. The incremental contract this spec
  defines is consumed by `LLMPort.stream()` callers
  (`services.chat_completion.run_chat_completion_streaming`, and any future
  route that lifts the M0 containment).

## Decision

**One optional observer parameter — `on_chunk` — threads from the stream
consumer down to the one approved transport seam. The Invocation lifecycle is
untouched.**

1. `ModelChatEgress.complete(..., on_chunk=None)` captures the observer in its
   executor closure and hands it to `execute_model_chat(..., on_chunk=...)`.
   `InvocationExecutionService` is unchanged: the observer is transport-side
   progress, not lifecycle state.
2. The gateway's SSE pump (`_stream_body`) parses each `data:` event and hands
   the **normalized chunk** (Responses events converted to chat.completions
   shape by the existing `_responses_event_to_chunk`) to `on_chunk` as it
   arrives — before the pump returns, while the Invocation is RUNNING.
3. `GovernedModelChatClient.stream_chunks` bridges observer callbacks to its
   own async generator with a queue. The governed call runs in a pump task;
   chunks are yielded live; a sentinel enqueued in the pump's `finally`
   terminates the loop; `await pump` after the loop propagates any executor
   failure to the consumer in ordinary `async for` semantics.

### Invariants preserved (and how the design keeps them)

| Invariant | Mechanism |
| --- | --- |
| Admission before dispatch | Unchanged: `invoke()` admits, then dispatches. |
| One Invocation per logical effect; dedup replay | The terminal summary body keeps `_stream_chunks`; a call that replays a prior completed Invocation sees zero live chunks and replays the recorded ones (`_replay_result_chunks`). |
| Terminalize only after full consumption | The pump returns the `_StreamSummary` body only when the wire ends; `_run_provider` terminalizes on it exactly as on a non-streaming body. |
| Failed stream cannot become a successful result | A mid-stream error propagates through `_run_provider` (generic error → UNKNOWN, `EffectNotApplied` → FAILED) and re-raises to the consumer. |
| Consumer cancellation is truthful | A consumer that stops early (`aclose()`) cancels the pump task; the executor's `CancelledError` path terminalizes UNKNOWN ("provider invocation cancelled with unknown external outcome"). No fabricated success, no orphaned dispatch. |
| Usage accounting | `_stream_usage` normalizes the last usage measurement on the wire — chat.completions terminal usage chunks and Responses `response.completed` events — into the terminal body, so `_gateway_usage` records real input/output units for streamed calls. An unmeasured stream stays unmeasured (`usage=None`), never zero. |
| Authorization cannot leak through the observer | `on_chunk` receives parsed chunks only. It runs inside the executor after authorization; it cannot alter admission, dedup, policy, quota, or the terminal record. |

### Explicit non-goals

- **Adapter-backed streaming stays buffered/JSON.** `AdapterGatewayProvider`
  specs declare no streaming normalization in this round; a streaming request
  routed to an adapter keeps today's behavior. Extending the observer across
  adapters requires their `normalize_request`/`usage_from` hooks to declare
  stream shapes first (SPEC-284 follow-up).
- **No second execution authority.** Alternatives that added an
  `invoke_streaming()` variant or a streaming-specific lifecycle were rejected:
  two lifecycle code paths is exactly the divergence the convergence exists to
  remove. The observer is deliberately narrow enough that one path serves both.
- **The M0 `/chat/stream` single-`done` frame is unchanged.** Lifting it is a
  product decision that can now reuse this contract without further boundary
  work.

## Consequences

- `stream_chunks` consumers (shipped: `HttpOpenAIProtocolLLM.stream` →
  `run_chat_completion_streaming`) receive tokens as the provider emits them,
  inside the same governed Invocation, with cancellation/failure/usage that the
  ledger can prove.
- The bridge's queue is unbounded but bounded-in-practice by the provider
  response size — identical memory exposure to the buffering it replaces;
  slow consumers exert backpressure only up to the wire buffer, which the
  gateway timeout bounds.
- Tests pin the design structurally: the core suite proves a chunk crosses to
  the consumer while the provider wire is still producing (a buffering
  regression aborts the wire loudly), that a mid-stream failure and an
  abandoned consumer both terminalize non-COMPLETED, that a deduplicated
  stream replays without re-dispatch, and the Hive adapter test proves the
  shipped port's stream lands on the ledger with usage.

## Acceptance Criteria

Each criterion below is pinned by the suites named in the `tests:` front-matter;
the structural proofs deliberately avoid wall-clock assertions.

- [x] **AC-1** Incremental delivery under one Invocation: while the provider
  wire is still producing, an observer-bridged chunk reaches the consumer
  through `stream_chunks`
  (`test_stream_reaches_the_consumer_while_the_invocation_is_running`); a
  buffering regression aborts the wire loudly instead of passing.
- [x] **AC-2** Failure cannot fabricate success: a mid-stream provider failure
  terminalizes the Invocation non-COMPLETED and propagates to the consumer
  (`test_stream_failure_midstream_terminalizes_and_reaches_the_consumer`);
  a generic wire error records UNKNOWN
  (`..._midstream_...`), a not-applied HTTP refusal records FAILED
  (`test_stream_http_refusal_records_failed_not_unknown`).
- [x] **AC-3** Abandonment is truthful: a consumer that closes the stream
  early cancels the pump and terminalizes UNKNOWN — never COMPLETED, never an
  orphaned dispatch
  (`test_stream_abandonment_never_leaves_a_completed_invocation`).
- [x] **AC-4** Dedup replay without re-dispatch: a logical effect whose
  Invocation already terminalized COMPLETED replays the recorded chunks with
  zero live provider calls
  (`test_deduplicated_stream_replays_the_record_without_dispatch`); a record
  without stored chunks replays its completion body, and no record replays
  nothing.
- [x] **AC-5** Usage accounting for streamed calls: the terminal usage
  measurement on the wire reaches the Invocation ledger for streamed
  dispatches (the Hive adapter suite pins the ledger row);
  an unmeasured stream records `usage=None`, never zero.
- [x] **AC-6** One execution authority: the streaming path crosses the same
  one gateway seam and Invocation lifecycle as non-streaming dispatch under
  every shipped protocol selection — `auto` streams the Responses endpoint's
  normalized chunks through the identical admitted, deduplicated, terminalized
  Invocation (`test_responses_protocol_streams_normalized_chunks`), and the
  observer receives parsed chunks only, never lifecycle authority.

## Ratification note

The chunk-granularity and cancellation semantics above were authored and
implemented in the #1084 convergence lane. The lane cannot self-ratify owner
policy: the owner decision of record for this issue (2026-09-23) governs
admission, which this design preserves. Any subsequent owner adjustment to
streaming semantics amends this spec rather than forking the transport.
