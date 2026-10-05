---
inventory-delta:
  packages/maistro-core/tests: +9
---

# Agent delegation effects within one canonical Attempt (#1084)

Stable configured Bindings exposed a previously masked collision: a custom
strategy can call the model and then return `delegate_to`; the next Agent
resets its local call counter and would replay the parent's `agent-llm-1`.
Three fail-first cases reproduced the wrong answer for different Agents,
finite self-delegation and `A -> B -> A`. The built-in `DelegateStrategy` chain
passed before the repair because only its leaf calls the model.

## Bounded repair

The existing `Agent._delegate` contract is one tail-delegated child per handle,
inside the same canonical NodeRun/Attempt (ADR-082426-6201). It allows cycles up
to its existing depth limit, so Agent name alone cannot identify each logical
model call. The effect key now incorporates the declared Agent name, the
existing delegation depth, and the existing per-turn call sequence. Revisiting
the same Agent at another depth gets its own effect; replaying the same chain
reuses the corresponding effects without HTTP or duplicate usage.

`GovernedLLMClient.set_agent_turn` is an opt-in hook over `set_turn`, which retains
the canonical tuple validation and counter reset. Agent uses the hook where
present and otherwise retains the original `set_turn(agent_name=...)` call so
standalone clients with that signature remain supported. `clear_turn`, every
new ordinary turn, and rejected turn setup clear the effect discriminator.
The discriminator is task-local and authorizes nothing. Empty-name explicit
lower-level calls retain their `agent-llm-N` keys.

No new canonical execution identity, store, allocator, Binding or actor is
introduced. Domain TurnID handling and paused #1870 remain unchanged. This does
not expand the existing single-child delegation contract into a sibling or
arbitrary reentrant execution API.

## Evidence and scope

- Three real `Agent.handle` model-before-delegate cases verify distinct prompts
  and answers, exact persisted actor/Binding/Attempt/usage joins, one canonical
  NodeRun/Attempt, and deterministic replay. Real ContextBuilder, prompt store,
  Warden, canonical admission stores and effects are used; only final HTTP is
  substituted with MockTransport.
- One built-in multi-hop delegation case and one original-client-hook case
  preserve existing behavior.
- Four focused effect-scope cases cover ordinary reset, explicit clear,
  failure-atomic rejected setup, and concurrent task isolation; the original
  #1827 tuple/identity and #1829 tool-choice suites remain applicable.
- Configured Hive boot/materialization assertions now name their Agent-qualified
  logical effect; no Hive production route is changed by this correction.

No full local Hive suite or live gateway is part of this bounded verification.
