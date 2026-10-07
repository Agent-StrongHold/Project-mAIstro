---
inventory-delta:
  packages/maistro-core/tests: +15
---

# Governed model tool-choice transport (#1829)

Adds five explicit-value cases through GovernedLLMClient, real ModelChatEgress,
Binding/credential resolution and Invocation execution, replacing only gateway
HTTP. The tests observe both the request handed to egress and the final JSON.
They include none, auto, required, an opaque provider value and whitespace.

Three conversation-only cases pin omitted, None and empty-string behavior:
no tool definitions or tool_choice are added to the gateway payload.

Seven direct-request cases preserve the selected Provider model, messages,
tools, JSON response_format, temperature and max_tokens while varying only
tool_choice. Caller inputs and validated requests remain unchanged.

Tests bind explicit execution context and do not modify the identity behavior
owned by #1827. Parent #1084 still owns the wider model-egress cutover.

## Verification sequence

The first draft intentionally retains the existing adapter's
`del tool_choice, stream, metadata` statement and omits adapter forwarding.
This isolates the regression: the gateway can carry the field, but the adapter
still drops it. The explicit-value tests must fail before the adapter fix.
Exact CI revisions and outcomes are recorded in the PR discussion.
