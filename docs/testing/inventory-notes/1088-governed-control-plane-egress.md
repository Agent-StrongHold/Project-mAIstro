---
inventory-delta:
  packages/hive-conductor/backend/tests: +24
  packages/maistro-bootstrap/tests: +6
  packages/maistro-core/tests: +6
---
# Governed evaluator and provider health egress

## hive-conductor (`test_governed_model_consumers.py`)

Three behavioural groups for issue #1088, all running against a real canonical
spine (`InMemoryRunStore` + `InMemoryProjectScopeStore`):

1. **Benchmark evaluation correlates to canonical records** — the judge
   Invocation's `run_id`/`node_run_id`/`attempt_id` resolve to real Run,
   NodeRun and Attempt records minted as a child operation of the evaluated
   Run; the operation terminalizes COMPLETED with an accepted outcome, usage
   metadata is preserved, and a run missing from the store is refused with
   `error_kind="authorization"` and **zero** model HTTP.
2. **Provider activation ordering and secret hygiene** — registration is
   Invocation-internal `setup` (zero gateway calls, including no
   `/model/new`, under a denied policy), a registration HTTP failure
   surfaces as `ProviderActivationError` with an UNKNOWN Invocation (not an
   authorization error), and the transient provider secret reaches the
   LiteLLM registration without ever being persisted in the Invocation.
3. **Minted identities end-to-end** — the full route-shaped flow (mint →
   governed health → settle) completes the canonical operation records.
4. **Fail-closed runtime, immutable bindings, truthful settlement** —
   `_runtime()` refuses without the core Container and wires the live
   container's authorities (effects/registry/router/scope/run stores) plus
   the env-chain endpoint when it exists; a missing gateway configuration is
   a `ProviderActivationError`, never an implicit default. Bindings are
   idempotent for identical re-registration and immutable against mutation.
   Minting without the canonical run store refuses; settling refuses unknown
   outcomes and terminalizes `failed`/`cancelled` operations truthfully
   (Run/NodeRun/Attempt each reach their distinct terminal state, keeping
   authorization refusals distinguishable from execution failures).
5. **Benchmark error kinds and DAG aggregation** — a policy-deny on the judge
   call returns `error_kind="authorization"` and settles the operation
   CANCELLED; an unreachable gateway returns `error_kind="evaluation"` and
   settles FAILED; `evaluate_dag_run` decomposes every successful node
   output positionally (first=plan, middle joined as code, last=review) and
   never forwards unsuccessful outputs to the judge.

## maistro-core (`test_model_chat_egress.py`)

Two seam-level ordering proofs for the new Invocation `setup` hook: the hook
runs after policy authorization and before any model HTTP, and a denied
policy refuses before the hook executes at all — the property that keeps
credential-bearing Provider preparation from leaking past authorization.

The gateway Provider seam is covered directly: `register_provider_models`
posts one `/model/new` per model against the admin base (stripping a
trailing `/v1`), carries the transient key only in `litellm_params` plus the
endpoint's authorization header, maps HTTP rejections and transport errors
to `ProviderRegistrationError`, and a governed request's `response_format`
passes through to the gateway body only when requested.

## maistro-bootstrap (`test_model_selector.py`)

Two structural-authorization cases: `run_benchmark` refuses every caller
whose `__main__` is not this module's own CLI file (authorization can no
longer be self-attested via an `operator_probe=True` keyword — passing it is
a `TypeError`), while a process executing the module as `__main__` probes
normally.
