---
inventory-delta:
  packages/hive-conductor/backend/tests: +34
  packages/maistro-core/tests: +3
---
# Recover governed DAG model tools from #1370 (#1085, partial)

## Scope and dependency

This slice uses develop `31d891a5` plus #1362 `afb5b0d4`'s existing actor/quota
effect API. It does not replace ModelChatEgress, credential routing, Binding
stores, Invocation services, or any Run authority. It preserves #1937's
canonical identity adapter and #1875's tool-choice propagation.

The canonical async Hive DAG tool path retains its `legacy_tool` Invocation.
Its `clarify` and grounded-search model sub-effects now resolve a configured
`model.chat` Binding, then use the same Container's model Provider/Invocation
authority. The outer record carries tool policy/outcome; only the model
record carries model usage. Exact NodeContext actor, Workspace, Project,
Run, NodeRun and Attempt are forwarded; no fallback identity or credential
registration is added.

Operators supply `model_binding_id` on the legacy DAG node or its `config`.
That value is a reference to an existing `AgentConfig.model_bindings`
declaration loaded by normal Container bootstrap. Missing, disabled,
foreign-scope, revoked or uncredentialed declarations refuse physical model
dispatch. Brave/Serper/Tavily/browser paths retain their existing behavior;
their model fallback requires the model Binding only when actually reached.

Prompts, JSON response format, selected model alias and omitted max_tokens
remain intact. ModelChatRequest now accepts temperature=None to preserve the
tools' existing Provider-default sampling; the existing 0.7 default and
explicit 0.0 are unchanged. The 30-second tool transport ceiling is narrowed
by a shorter declared canonical node deadline.

Malformed, empty or incomplete clarification answers fail the tool instead
of manufacturing `Not specified`. Both numeric-key and question-key answers
remain accepted. An invalid grounded-search response similarly fails;
an explicit empty citations list remains valid.

The existing outer tool Binding had a timestamp-only repeat-registration
defect. Reusing `register_boot_binding`, and re-reading through that strict
helper once after a raced put, preserves the original definition and its
first timestamp. Redefinition and tombstoned revocation still refuse.

## Evidence

- 34 new Hive cases enter real SQLite Container bootstrap and the shipped
  canonical DAG resolver/executor, or target the resulting adapter boundary.
  Only final model transport is replaced; admission, Binding/policy,
  credential selection, Invocation, quota, persistence and usage stay real.
- The cases cover positive correlation, top-level/config Binding references,
  four scope/configuration refusals, missing scoped credential, provider
  unavailability, revoked model/outer tool Bindings, three real quota budgets,
  timeout/UNKNOWN outcome, malformed and absent text, model fallback routing,
  exact-request replay, sequential Runs and forced simultaneous first
  Binding registration. The latter barriers the selected store's real reads;
  it does not substitute an authorization decision.
- Three core cases cover omitted/default/zero sampling serialization. One
  existing tool fixture accepts the new callback; no prior assertions or
  tests are removed.
- The initial 19-case regression suite produced 16 failures against the
  dependency-only baseline and passed after the migration. That control
  forbids raw model HTTP rather than contacting a live provider.
- Independent review reproduced exact-request replay without duplicate
  dispatch or Invocation records, and cancellation with canonical
  Run/NodeRun/Attempt CANCELLED plus both external outcomes UNKNOWN.
- Direct-model and direct-effect inventories remove only the two retired
  tool-model call sites; browser/tool effects remain inventoried.

## Explicit limits

This is partial #1085 work. Ordinary legacy model fallback, sandbox model
dispatch, Agent tool composition, and #1084 admission/streaming remain open.
No parent is closed. Existing foreign-harness and #1867 background-actor work
is unchanged.

A simultaneous whole-DAG probe on this shared SQLite Container reaches a
separate `cannot start a transaction within a transaction` failure across
runtime stores after registration. This slice does not repair shared-store
transaction ownership or claim concurrent-DAG readiness. The isolated
Binding-registration race proof is deliberately narrower.

No live paid-provider, PostgreSQL, release or deployment proof is claimed.
