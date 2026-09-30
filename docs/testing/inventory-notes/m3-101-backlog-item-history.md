---
inventory-delta:
  packages/maistro-core/tests: +54
  packages/maistro-server/tests: +6
---
# m3-101-backlog-item-history

New tests only; nothing was removed or moved.

- `packages/maistro-core/tests` (+52): `workspaces/backlog_history/test_backlog_history_model.py`
  pins the event contract — journal kinds that are deliberately not work-state tokens, UTC
  normalisation, the per-kind required payloads (status moves carry both ends, closure carries
  evidence refs, discovered work is pinned to a PROPOSED initial status, reconciliation carries
  a decision pointer, reopening carries a reason), frozen events, store-assigned sequences, and
  the pydantic registration of every validator;
  `workspaces/backlog_history/test_backlog_history_store_conformance.py` runs one suite over the
  in-memory reference and the SQLite store (per-item sequences that continue across a restart,
  ordered reads replayed per item by sequence on both backends, workspace/project/item/kind
  filters, duplicate event ids refused, callers getting copies, full payload round-trip including
  Goal links and Run references, restart durability);
  `workspaces/backlog_history/test_backlog_history_recording.py` covers the recording semantics —
  before/after field diffs that refuse no-ops, claim take/release snapshots, blockers, partial
  progress that implies no status, decomposition receipts that snapshot parent acceptance
  criteria without rewriting them, discovered prerequisites pinned to PROPOSED, Goal binding by
  exact identity/revision, reconciliation pointers, Run/evaluation evidence with the replan
  reason, closure refused without evidence (a completed Run alone never suffices), reopening with
  a reason, and a full item life read back in order;
  `workspaces/backlog_history/test_backlog_history_wiring.py` pins the backend selection
  (memory reference, SQLite journal, refused split, loud PostgreSQL fallback, Container wiring on
  both backends) and the shared `backend_of` helper.
- `packages/maistro-server/tests` (+6): `api/test_backlog_history_api.py` covers member reads of
  the full ordered history, the kind filter, outsiders and unknown items not being
  distinguishable, a Container without a BacklogItem history store answering 503 instead of
  crashing, mounting on the production app, the registered route handler, and JSON
  serialisation of events for the wire.
