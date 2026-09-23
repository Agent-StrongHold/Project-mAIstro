---
inventory-delta:
  packages/maistro-core/tests: +19
---
# #1158 Warden normalization and bounded context

- Warden regression coverage now exercises spaced-letter, composed spaced-leetspeak,
  and bounded leetspeak instruction overrides, cross-turn reconstruction, trusted-context exclusion,
  and the turn/byte aggregation budget.
- The harness safety seam verifies that an override reconstructed from two
  untrusted turns is refused before the inner provider receives the messages.
- ReAct and Artificer tool-result coverage verifies ordered cross-call
  aggregation, and the message-context regression verifies the tail and
  per-item serialization caps.

## Merge reconciliation with #1398 (central Agent trust pipeline)

`develop` landed the centralized Agent trust scanning (#1398) while this branch
hardened Warden normalization and multi-turn context. The merge keeps #1398's
structure — the Agent owns user-input, tool-result, final-output, and
delegation-output policy — and re-adds the bounded ordered analysis context at
each of those seams instead of scanning one string at a time:

- `Agent._prepare_user_input` runs after session-history injection and scans
  each user turn together with `prior_message_context` of the messages before
  it, so a payload split across individually-benign session turns or across
  user messages inside one `handle()` call is refused before the strategy
  (and any provider call) sees either fragment.
- `Agent._governed_tool_executor` aggregates sanitized tool results in a
  `deque(maxlen=_TOOL_CONTEXT_MAX_TURNS)`; `_sanitize_tool_result` forwards
  that bounded context to Sentinel `post_call`/Warden `scan`.
- ReAct and Artificer keep both reconciliation knobs: `security_pipeline=True`
  defers to the Agent-owned gate (already context-aware), while standalone
  callers keep the bounded-context gate themselves.

New Agent-level regressions in `tests/agents/test_base.py`
(`TestMultiTurnTrustAggregation`, +5): split override across session history;
split override across user messages in one call; benign-history false-positive
control; split tool results blocked at the governed executor before the next
model call; and the finite tool-result window (a fragment pushed out by more
than the retained number of intervening results is no longer joined, pinning
the bound against unbounded growth).
