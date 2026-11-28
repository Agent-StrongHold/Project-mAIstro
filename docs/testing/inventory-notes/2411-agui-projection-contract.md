---
inventory-delta:
  packages/maistro-core/tests: +20
---

# AG-UI canonical projection spike (#2411)

Added 20 collected contract cases in
`packages/maistro-core/tests/events/test_agui_projection.py`.

The **pure** transport projection offers:
- allowlisted canonical event -> AG-UI `CUSTOM`, with payload/provenance
  discarded and IDs/Workspace sequence preserved;
- `RUN_STARTED` with explicit AG-UI 1.0 producer version;
- `RUN_FINISHED` for canonical COMPLETED, cancelled outcome for CANCELLED,
  `RUN_ERROR` for FAILED or TIMED_OUT (no raw error leakage);
- non-terminal Run values do not fabricate a final event;
- run-scoped ordered/deduped event subset after a canonical sequence cursor,
  with foreign Workspace and Run rows omitted.

**Important limits:** no streaming HTTP endpoint, official schema validator,
A2UI catalog, frontend client, HITL action wiring, Postgres/restart test or
principal-scoped EventStore read has been integrated. The existing
`project_agui_event` event-type allowlist remains provisional and needs
real-producer verification. Passing pure-function tests would not establish
AG-UI protocol interoperability.

The status-vocabulary test pins all RunStatus enum variants; adding a new
canonical status without adjusting the projection fails tests. These tests
are not yet executed in the monorepo.
