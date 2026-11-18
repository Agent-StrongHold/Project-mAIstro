---
inventory-delta:
  packages/hive-conductor/backend/tests: +6
  packages/maistro-core/tests: +10
---
# 1084-streaming-and-vision-governance

Issue #1084 convergence work added direct tests for two shipped egress seams
that previously had none, and tightened SPEC-285's pinned criteria.

## packages/maistro-core/tests: +10 (`test_model_chat_egress.py`)

SPEC-285 acceptance work, each test named for the criterion it pins:

- `test_stream_http_refusal_records_failed_not_unknown` (AC-2) — a not-applied
  HTTP refusal on the stream records FAILED, not UNKNOWN.
- `test_stream_text_helper_yields_only_content_text` — `stream()` is the
  text-only view; reasoning deltas and the empty terminal usage frame
  (`choices: []`) are skipped, which is what the
  `GovernedModelChatClient.stream` no-choices guard fixes.
- `test_stream_with_caller_scope_dispatches_under_the_scoped_binding` — a
  caller-named scope derives the scoped Binding and records the Invocation
  under it.
- `test_stream_without_terminal_usage_records_none_not_zero` (AC-5) — a wire
  with no terminal usage records `usage=None`, never zero.
- `test_replay_falls_back_to_the_recorded_completion_body` and
  `test_replay_without_a_record_yield_nothing` — degenerate paths of
  `_replay_result_chunks`.
- `test_responses_protocol_streams_normalized_chunks` (AC-6) — `auto` streams
  the Responses endpoint's normalized chunks through the same one Invocation;
  wire noise is skipped, malformed usage stays unmeasured.
- `test_auto_protocol_reraises_a_response_auth_refusal` and
  `test_auto_protocol_falls_back_when_responses_refuses_the_request` — the
  `auto` protocol retries chat.completions only on non-auth refusals.
- `test_build_model_chat_client_supplies_default_authorities_when_omitted` —
  the compatibility constructor composes the process-default effect context
  rather than returning an ungoverned client.

## packages/hive-conductor/backend/tests: +6

- `test_llm_http_adapter.py` (+2): `test_an_unreachable_gateway_surfaces_as_a_compat_500`
  (an `EffectNotApplied` with no HTTP status keeps the fallback 500 shape) and
  `test_a_responses_body_normalizes_to_the_chat_shape` (every Responses-output
  shape the adapter documents resolves without crashing the turn).
- `test_vision_tool_governed_dispatch.py` (new file, +4): issue #1084 bounded
  work item 5 — `_tool_analyze_dashboard` dispatches its vision call through
  the one `build_llm_port` seam (request shape, answer, error result), and
  `build_llm_port`'s degraded-engine paths compose the canonical governed
  client instead of an ungoverned dispatcher (two tests).
