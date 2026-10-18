---
inventory-delta:
  packages/maistro-turing/backend/tests: +9
---

# Issue #27/#859 — Scope Turing cognitive state to canonical principals; bounded writes

The Turing backend's self-model was one process-global snapshot (any admin's
`PATCH /v1/admin/mood` changed what every other principal read) and the chat
session map was an unbounded module global — the exact #859 audit defect.
This change scopes cognitive state per authenticated principal and bounds the
chat-session registry, on the production backend path
(`packages/maistro-turing/backend/`):

- `state.py`: self-model state lives in per-principal scopes created lazily
  from an explicit, non-blank scope id; a blank/absent scope raises instead of
  falling back to a shared snapshot. `set_mood`/`set_facet` enforce the
  documented ranges at the authoritative write seam itself (`Mood.__post_init__`
  / explicit facet range check), not only in the HTTP layer's pydantic schema.
  New `ChatSessionRegistry`: chat sessions are keyed by
  `(principal_id, session_id)` — a client-supplied session id alone never
  selects a session — and the map is bounded by idle TTL and LRU capacity.
- `routes/admin.py`, `routes/state.py`: reads and writes are keyed by the
  calling principal's canonical `actor_id()`, so one admin's mutation is
  invisible in another principal's snapshot.
- `routes/chat.py`: the module-global `_SESSIONS` dict is replaced by the
  composed `TuringState.chat_sessions` registry (per-principal keys, bounded).

Tests (`+9` node IDs, new file `test_state_scoping.py`):

- cross-principal self-model isolation at the state seam (two scopes never
  share mutations) and refusal of blank scopes (no process-global fallback);
- seam-level bound enforcement: out-of-range mood/facet values raise and leave
  state unmutated; unknown facets raise;
- API-level proof of the audit's exact defect reversed: one admin's mood PATCH
  is visible in the admin's own views and invisible in another principal's
  `/v1/state/snapshot`;
- chat-session registry: same session id under two principals yields distinct
  sessions; LRU capacity eviction; idle-TTL expiry (fake clock, no
  wall-clock timing assertion); blank principal/session ids refused.

`test_state.py::test_snapshot_reflects_admin_mood_change` asserted the defect
itself (another user's snapshot reflecting one admin's PATCH); it is renamed to
`test_snapshot_reflects_the_calling_admins_own_mood_change` and now asserts the
scoped contract (node count unchanged). `test_chat.py`'s `StubState` carries a
registry to match the composed `TuringState` shape.
