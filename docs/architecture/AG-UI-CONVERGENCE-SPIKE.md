# AG-UI convergence spike: canonical interaction contract

Status: implementation spike; **not** an adoption decision or production-ready transport.

## Architecture decision to evaluate

Use AG-UI as a client interaction protocol projected from canonical mAIstro
state, with A2UI for catalog-governed declarative surfaces. No AG-UI state,
thread, run or tool result may become a second lifecycle or authorization
authority. Do not replace the canonical EventStore, Goal/Graph/Run/NodeRun/
Attempt records, durable HITL settlement or effect ledger.

## Existing contracts and dispositions

| Contract | Disposition | Required work |
| --- | --- | --- |
| ADR-070426-3a1f | AMEND | Specify AG-UI as preferred interaction carrier while retaining A2UI v0.10 payload/catalog semantics; preserve other transport compatibility where required. |
| SPEC-277 | AMEND | Reconcile proposed A2uiCatalog/action ownership with shipped governed UI extension manifests (#967); explicitly define replay, authorization and durable projection ownership. |
| #967 / maistro.extensions.ui | REUSE | Reuse UiProjectionService, BINDABLE_FIELDS, governed routes, catalog inspection, provenance and sandbox checks. |
| #909 M8-J research | IMPLEMENT INCREMENTALLY | Validate live progress, HITL, and generated UI against canonical projection rule; measure supervision burden and recovery. |
| Workspace cutover P0.3 | DEPEND ON | Generated API types and single client boundary before shipping a new frontend consumer. |
| Canonical EventEnvelope / EventStore | REUSE | Map authorized persisted events into AG-UI; preserve sequence and replay cursor; never write canonical state from AG-UI client state. |
| #804 Persistent Workspace Agent | REUSE | Reconstruct client projections from durable Goals/Runs across sessions, not session-local A2UI data models. |
| Research Lab semantic memory | FUTURE CONSUMER | Emit source/claim/graph projections only after canonical semantic-memory contracts are implemented. |
| SPEC-179 Flutter gateway | REVIEW | Ensure AG-UI transport does not assume React or a single web client. |

## Current spike implementation

`maistro.events.agui_projection.project_agui_event` is a pure, read-only
projection to an AG-UI CUSTOM event. The allowlist is intentionally tiny.
Canonical payload and provenance are never forwarded. It is **not** a general
event bridge, transport, schema negotiation, or complete AG-UI session.

Important: the literal event names in the allowlist are provisional. Before
wiring a live route, verify actual emitted canonical event types and normalize
them through a reviewed mapping. Do not expand to arbitrary event types.

## Production implementation sequence

1. Inventory real canonical lifecycle event names and their event visibility
   policy; replace the provisional allowlist with a tested mapping.
2. Establish Workspace authorization before subscription and on reconnect;
   verify out-of-scope IDs are indistinguishable from missing IDs.
3. Read persisted canonical EventStore sequences; stream AG-UI RUN_STARTED,
   RUN_FINISHED, RUN_ERROR, text events and CUSTOM events as appropriate.
   Define the AG-UI run identity as a *projection* of canonical Run identity,
   never a second run store.
4. Implement reconnect with canonical cursor, ordered replay, deduplication,
   and bounded backpressure; compare behavior with existing run-scoped SSE.
5. Route inbound actions through existing authenticated, governed canonical
   endpoints. HITL settlement must re-check authority and be idempotent.
6. Add A2UI rendering over the AG-UI interaction carrier using one governed
   component registry and existing DesignSystem token authority.
7. Generate typed frontend client contracts, integrate one Workspace surface,
   and run real PostgreSQL restart/replay and two-client approval tests.

## Release gates

- No new authority for Runs, approvals, effects, component grants or audit.
- No client-provided canonical IDs used to authorize a mutation.
- No opaque canonical payload/provenance leakage.
- Replay and duplicate delivery do not duplicate an effect or HITL verdict.
- A2UI catalogs and extension manifests cannot bypass existing governance.
- Existing clients continue to function; feature flag until parity is proven.
- New frontend must comply with Workspace cutover typed-client requirement.
- No production claims until tests execute and end-to-end behavior is verified.

## Open design issues

- AG-UI event type coverage and version pin.
- Whether the canonical run stream has a durable cursor compatible with
  AG-UI client reconnect semantics without adding another store.
- Catalog unification: SPEC-277 A2uiCatalog versus #967 manifest identity.
- A2UI session lifetime versus persistent Workspace surface reconstruction.
- Exact placement of Warden inspection for generated UI actions that are
  already bound to governed server routes.
