---
inventory-delta:
  packages/maistro-core/tests: +16
---

# #2500 — A2A v1 status-only Task projection

This is a pure mapping from an already principal-scoped canonical `Run`
to an A2A v1 `Task` status snapshot, not an A2A service implementation.

- `packages/maistro-core/src/maistro/a2a/wire_projection.py` maps every
  canonical `RunStatus` to a published A2A v1 `TaskState` token.
- `WAITING` and `PAUSED` remain `WORKING` until **verified canonical
  human-input evidence** justifies `INPUT_REQUIRED`. A pause is not itself
  proof that a user must answer.
- The external `contextId` must be derived from a persisted authorized A2A
  context; the mapper never serializes Workspace, principal, Run.result,
  Run.error, Graph or provenance.
- Timeouts project as failures, cancellations as canceled.
- The mapper cannot admit or mutate Run state, dispatch tasks, set approvals
  or authorize any client.

`packages/maistro-core/tests/a2a/test_wire_projection.py` adds 16
collected cases: enum coverage, status behavior, sensitive-data exclusion,
invalid context/unknown status/timezone handling. Test inventory is
recorded; **full repository tests and upstream A2A conformance were not run**.

Before issue #2500 can close: implement Agent Card discovery, proper
SendMessage wire decoding and Warden, canonical run admission, scoped
GetTask and cancellation, output/artifact governance, idempotency/retry,
version negotiation and independent official client conformance. Do not
expose this slice as a publicly interoperable A2A endpoint.
