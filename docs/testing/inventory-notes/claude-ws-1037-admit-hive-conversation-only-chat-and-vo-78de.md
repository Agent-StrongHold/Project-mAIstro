---
inventory-delta:
  packages/hive-conductor/backend/tests: +20
---
# claude-ws-1037-admit-hive-conversation-only-chat-and-vo-78de

Hive conversation-only chat and voice turns become canonical chat Runs
(#1037). The new `test_chat_run_admission.py` adds 20 node IDs, driven through
the shipped `/v1/chat/complete`, `/v1/chat/stream` and `/v1/voice/intent`
routes on a real embedded Container with the model faked at its HTTP
transport: repeated same-Workspace turns (distinct Runs, one Workspace Agent),
default-Workspace fallback, session id as provenance only (and only when the caller owns it), stream completion,
model failure on both routes, the retryable 503 on admission failure (three
routes parametrized) and on a missing Run store, the unrecorded-answer and
cancellation branches, a stream whose body never runs, a spine refusal
before the model, a member Workspace with no view, and zero tools offered. No existing test was removed;
the existing chat/voice route modules only gained the `chat_run_spine` fixture,
and one voice field-set assertion now includes the additive `run_id`.
