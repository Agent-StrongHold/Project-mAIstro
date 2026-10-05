# Governed model streaming (#1084)

This slice extends the existing model Provider protocol; it does not introduce
another admission, execution, credential, or accounting authority.

- `ModelChatEgress.stream` drives the same canonical governed `invoke` method as
  non-streaming completion. Its executor consumes the Provider stream and returns
  the assembled response only after a complete protocol termination.
- Only `capabilities/providers/llm_gateway.py` owns gateway HTTP. The initial
  streaming protocol is OpenAI-compatible chat/completions, with requested usage
  reporting. Responses API is not silently substituted or emulated.
- An awaited, one-item queue forwards the original provider chunks while the
  Invocation is RUNNING. Consumer backpressure stops protocol consumption; no
  full-response buffering is required before the first chunk. The final response
  is accumulated for canonical result persistence and deduplication.
- SSE comments are ignored, data lines are joined per event, and every data event
  must decode to an object. A provider error, malformed event, missing terminal
  marker, or unfinished choice raises. A `[DONE]` marker plus finish reasons for
  all observed choices proves protocol completion; transport EOF alone does not.
  A choice cannot resume after its finish marker. Interleaved choices and tools
  are assembled by their independent indices; repeated tool IDs stay metadata,
  while function names/arguments and text/reasoning remain fragment sequences.
  Known textual fields reject non-text values. ID/role/type metadata accepts
  identical repeats and empty fragments, but rejects conflicting nonempty values.
- Only connection refusal/timeout before response arrival proves non-dispatch and
  becomes `EffectNotApplied`/FAILED. HTTP errors, protocol failures, interrupted
  reads, and cancellation after dispatch remain UNKNOWN under existing Invocation
  rules. There are no transport retries or alternate-model requests.
- Consumer cancellation or explicit iterator close requests a stop and cancels
  the Invocation task only during active Provider execution, closing its HTTP
  response. Before Provider entry, canonical admission or failure recording is
  awaited; if admission later reaches the executor, its stop check raises
  `EffectNotApplied` before any HTTP. Once the Provider has exited on
  success or failure, cleanup instead waits for canonical terminalization so a
  late consumer close cannot interrupt COMPLETED, UNKNOWN, or proven FAILED
  recording and strand a RUNNING row.
  Repeated consumer cancellation is deferred until that existing Invocation
  finishes recording; cancellation is then propagated to the consumer.
- Usage is copied from a provider report, never estimated from chunks or replaced
  with zero when absent. The existing extractor and canonical completion recorder
  settle usage once. Missing reports stay absent. Interrupted outcomes preserve
  the existing UNKNOWN/quota-hold behavior rather than charging partial guesses.
- A completed effect replay makes zero HTTP calls. It emits one explicitly marked
  `_maistro_replayed` chunk assembled from the persisted message, finish reason,
  and usage. It does not claim a second incremental provider execution occurred.
- Application adapters must supply admitted execution identity and already
  resolved operator Bindings. They must not create credentials, actors, scopes,
  stores, policy bypasses, or synthetic Run/NodeRun/Attempt identifiers.

Verification uses only an in-memory canonical effect authority and
`httpx.MockTransport` with controlled asynchronous byte streams. Required cases:
first chunk before upstream completion, bounded backpressure, content/reasoning/
tool fragments and usage preservation, replay, missing usage, malformed/truncated
streams, HTTP and connect failures, denial before dispatch, cancellation and
explicit iterator close, and completion cleanup after provider success.

The focused streaming suite contains 71 cases. Cancellation-during-cleanup,
admission/quota-failure cancellation, failure-finalization cancellation,
repeated-tool-ID, post-finish-delta, invalid
text, and conflicting-metadata regressions were observed failing before their
corresponding fixes. Together with existing model egress coverage, 95 tests pass
without a live gateway. Replay is also exercised after closing and
reopening a SQLite Invocation store, rather than only against an in-process
cache. Focused Ruff and strict mypy checks pass; changed production modules have
no new C-or-higher Radon blocks. Repository-wide gates remain the integrating
task's responsibility.
