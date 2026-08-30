---
id: ADR-082826-51b9
title: "Voice intent reports only the capability containment actually leaves it"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-28
accepted: 2026-08-28
history:
  - status: Proposed
    date: 2026-08-28
  - status: Accepted
    date: 2026-08-28
substrate: []
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
ac-modules:
  AC-1: '@flat/hive-conductor/routes.voice'
  AC-2: '@flat/hive-conductor/routes.voice'
  AC-3: '@flat/hive-conductor/routes.voice'
  AC-4: '@flat/hive-conductor/routes.voice'
tests:
  - packages/hive-conductor/backend/tests/test_voice_intent_contract.py
  - packages/hive-conductor/backend/tests/test_m0_tool_containment.py
  - packages/hive-conductor/backend/tests/test_voice_auth.py
layer: UserClient
owners:
  - '@BlakeMatthews-dev'
---

# ADR-082826-51b9: Voice intent reports only the capability containment actually leaves it

## Context

`POST /v1/voice/intent` returned a `VoiceIntentResponse` carrying
`actions_taken: list[dict]` — documented as the tools the spoken utterance
invoked — and `intent`, documented as naming the first tool invoked.

Neither could ever be true. The route sends `tools=None`, so the model is never
offered a tool call, and the list it returned was built empty and never
appended to. `intent` only ever distinguished "the model produced content" from
"it did not", which is exactly what the sibling `understood` field reports.

The route also reached the model by a path of its own: it constructed an
`HttpOpenAIProtocolLLM` directly whenever LiteLLM settings were present rather
than calling `build_llm_port`, and diverged from that builder in three ways —
a hard-coded HTTP variant instead of the configured one, `LITELLM_API_KEY`
instead of `LITELLM_PROXY_KEY`, and its own model-default chain. It likewise
restated the tool-stripping trust boundary instead of passing through the
helper the chat routes use.

This is not a gap to be filled at M1. Producing a real action record means
running model-driven tools, and the M0 containment decision (#483/#484) is that
no public Conductor route does so until the Warden input/tool-result/output
boundary lands in #315. The choice available here is therefore about what the
response may *claim*, not about what the route may *do*.

## Decision

The response states only what a contained turn can establish.

- `actions_taken` is **removed**, not defaulted to an empty list. A field that
  is always `[]` cannot distinguish "no tool ran" from "a tool ran and nobody
  recorded it", and the second is the state #315 exists to make impossible.
- `intent` is **narrowed** to `Literal["conversation", "unknown"]`, the two
  states the service can tell apart. It no longer advertises tool naming.
- Voice answers through `build_llm_port` and `conversation_only`, the same port
  builder and the same trust boundary `/v1/chat/complete` and `/v1/chat/stream`
  use. `conversation_only` moves from `routes/chat.py` to
  `services/chat_completion.py` so both routes hold one object rather than two
  copies that agree today.

Restoring an action record remains #315's, together with the Warden boundary
that must gate the tools before any of them may run again.

## Acceptance criteria

All four are carried by `routes.voice` and proven in
`packages/hive-conductor/backend/tests/test_voice_intent_contract.py`.

- [x] **AC-1** No field of `VoiceIntentResponse` is one the route cannot fill.
  `actions_taken` is absent rather than defaulted to `[]`, because an
  always-empty list cannot distinguish "no tool ran" from "a tool ran and
  nobody recorded it".
- [x] **AC-2** `intent` admits only the two states the contained service can
  distinguish, and each is reached: a reply is `conversation`, no reply is
  `unknown`. A value naming a tool is refused.
- [x] **AC-3** Voice reaches the model through the same objects the chat routes
  use -- `build_llm_port` for the port and `conversation_only` for the
  tool-stripping boundary -- held by identity, not by two copies that agree.
  The utterance and its room/source/speaker context arrive with no tools
  offered and no smuggled extras.
- [x] **AC-4** Stubbing `build_llm_port` alone keeps the route offline: it
  constructs no transport of its own. This is the regression that matters,
  because the previous code built an `HttpOpenAIProtocolLLM` directly whenever
  LiteLLM settings were present, and the test fails against that code.

## Consequences

### Positive

- No field of `VoiceIntentResponse` is structurally unpopulatable, which is the
  completion-claim defect #31 was filed about.
- One execution path, so a containment rule cannot come to mean something
  different on the route nobody looks at. The regression test for this fails
  against the previous code.
- Voice inherits the configured HTTP variant and key resolution instead of its
  own, and a developer `.env` can no longer make the route reach the network
  through a transport the test fixtures had to stub separately.

### Negative / Trade-offs

- Removing a field from a shipped response is a breaking change for any
  external voice satellite that reads `actions_taken`. No consumer in this
  repository reads it, and the value it read was always `[]`, so the loss is a
  key rather than information. Compatibility windows for contract changes are
  #461's subject and are deliberately not invented here.
- `intent` remains a field whose two values duplicate `understood`. It is kept
  because narrowing is what #440 asks for and removing a second field widens
  the break for no gain; it becomes meaningful again when #315 restores tools.

### Neutral

- The voice reply is still shaped by whatever the model returns, with no
  speech-specific summarisation on either the voice or the chat path. The
  removed `skip_summary` argument had no counterpart to skip. Shaping a reply
  for a speaker rather than a screen is a product decision that neither path
  currently makes, and this record does not make it.
