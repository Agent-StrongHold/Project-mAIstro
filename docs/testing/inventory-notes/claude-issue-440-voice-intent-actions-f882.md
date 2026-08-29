---
inventory-delta:
  packages/hive-conductor/backend/tests: +8
---
# claude-issue-440-voice-intent-actions-f882

Eight node IDs, all in the new `tests/test_voice_intent_contract.py` (#440).
Purely additive: no test was removed, and the two existing assertions that
named the deleted field were re-pointed rather than deleted.

**Five pin what the response may claim.** `VoiceIntentResponse` advertised
`actions_taken: list[dict]` — the tools the utterance invoked — and could never
populate it, for two independent reasons: the route sends `tools=None`, so no
tool call is ever offered, and the local it returned was built empty and never
appended to. The tests assert the field set is exactly `{understood, intent,
reply}`, that `actions_taken` is *absent* rather than defaulted to `[]` (an
always-empty list cannot distinguish "no tool ran" from "a tool ran and nobody
recorded it"), that `intent` is constrained to the two states the service can
actually tell apart, and that each of those two states is reached.

**Three pin the seam.** Voice built its own `HttpOpenAIProtocolLLM` whenever
LiteLLM settings were present, diverging from `build_llm_port` in the HTTP
variant, the environment variable read for the key, and the model-default
chain. One test asserts both routes hold the *same* `conversation_only` object
rather than equivalent copies; one asserts the utterance reaches the model with
no tools offered and no smuggled extras; one is the regression test for the
second path, and it sets `LITELLM_API_BASE`/`LITELLM_API_KEY` because without
them the old code fell through to `build_llm_port` too and the test would have
passed against the defect it exists to catch. Verified: it fails against the
pre-change `routes/voice.py` — the hard-coded variant and the `LITELLM_API_KEY`
value are both visible in the refused constructor's kwargs — and passes after.

Two existing tests changed assertion rather than count —
`test_m0_tool_containment.py` and `test_voice_auth.py` each asserted
`actions_taken == []` beside a stronger witness (`tools is None`), so the
containment they exist to prove is untouched; they now assert the field is
gone. `test_voice_auth.py`'s `no_llm` fixture also lost its second stub of
`adapters.llm_http.HttpOpenAIProtocolLLM`, which existed only because voice had
a second construction path that a developer `.env` could activate.
