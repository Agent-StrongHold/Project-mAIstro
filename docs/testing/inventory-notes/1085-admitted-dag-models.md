---
inventory-delta:
  packages/hive-conductor/backend/tests: +37
---
# Admitted ordinary DAG model nodes (#1085)

## Scope and operator contract

This bounded leaf routes ordinary asynchronous Hive DAG model nodes through the
existing `AdmittedModelCalls` adapter. Normal execution and durable recovery
compose it from the selected Container's RunStore, configured Binding IDs,
`litellm_url`, ProviderRegistry and router. Model callers create no Binding,
credential registration, actor, store or quota exception.

The node's `model_binding_id` selects an operator-declared `model.chat` Binding;
top-level takes precedence over `config.model_binding_id`, matching the existing
model-backed tool convention. An omitted ID is accepted only when exactly one
configured Binding covers the persisted Run Workspace/Project and NodeRun node.
An ID found in storage but absent from this Container's declarations is refused.
Scopes, actor, lease and the joined Run/NodeRun/Attempt come from persisted
execution. Ambient credentials cannot fill a missing scoped credential.

The configured Binding pin outranks the node's requested `model`; an unpinned
Binding keeps explicit alias or normal router selection. JSON response format,
temperature 0.3, node result/error shape and declared bounded node timeout are
preserved. Canonical Invocation terminalization remains the one usage recorder.
The `dag:model` effect key is stable within a NodeRun and excludes Attempt ID:
a later Attempt replays completed evidence and cannot redispatch UNKNOWN work.

## Separate caller boundaries

The ordinary path has no raw-builder fallback, including explicit stub opt-in.
The model-backed tool runtime remains separately composed through its incumbent
gateway selection; its existing tool Invocation and model sub-effect code are
unchanged. A regression assertion pins its gateway destination. Isolated sandbox
execution and its Provider transport/usage hook are untouched. Consequently
`services.legacy_dag_node` correctly remains in `quality/model-egress.json` and
the direct-effect inventory; this leaf does not claim the whole module migrated.
Evaluator/activation/control-plane paths and the held public Hive Responses
cutover are not changed or claimed complete.

## Evidence and inventory

- 37 new cases exercise a real configured SQLite Container and shipped ordinary
  caller, replacing only final HTTP transport with `httpx.MockTransport`.
- Successful execution joins actual actor, Workspace/Project, Run/NodeRun/leased
  Attempt, configured Binding, Invocation and single usage event. The HTTP
  request proves scoped credential, configured destination, pin precedence,
  JSON/sampling and transport timeout.
- Missing, disabled, revoked, foreign, undeclared and ambiguous Bindings; missing
  credentials; invalid/unleased/expired/foreign/terminal execution; policy and
  actor-scoped quota refusals assert zero HTTP and no added/replaced grants.
- Positive actor-budget charging, recovery composition, cached-call revocation,
  configured unknown/unavailable pins with an available alternative, unpinned
  alias/router selection, malformed content and later-Attempt completed/UNKNOWN
  behavior are covered.
- Existing traversal, streaming, condition, HTTP/WS parity and deadline tests use
  an explicitly installed test-only admitted-call seam. Existing quota tests
  now use a real Container and final MockTransport. No test is removed to hide
  failure; existing counts are unchanged, for a net Hive suite delta of +37.
- The missing-authority regression was executed against the dependency-base
  production sources in an isolated diagnostic process. It failed because the
  old runner returned `completed` via its raw builder; fixed sources pass.

All execution is focused and hermetic. Full local Hive execution and live gateway
calls remain prohibited; suite inventory uses collection only. Exact-head remote
CI is still required before publication/merge readiness can be claimed.

## Local checks

- 231 focused tests passed across the new ordinary-node proof, existing DAG
  traversal/transport/tool/control-plane coverage and core admitted-call tests.
- Ruff check/format and `git diff --check` passed on all changed Python files.
- Core strict mypy passed over 714 source files after installing this worktree's
  declared development and bootstrap extras.
- Model-egress/direct-effect, execution-lifecycle, credential-authority,
  principal-identity, release-consistency, doc-link, radon and exact-argument
  vulture gates passed. No quality ledger was expanded or pruned by this leaf.
- Hive collection inventory is 3,419 tests, an additive +37 over the dependency
  base's 3,382. Full local Hive execution and live-provider verification were
  not run.
