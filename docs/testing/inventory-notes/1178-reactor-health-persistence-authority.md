---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
  packages/maistro-core/tests: +1
---
# #1178 — /health names the Reactor's persistence authority

The Reactor's state writes already ride the canonical `State` writer (the
#1178 fix that landed in `95945b000`, PR #1578): `maistro.reactor.state_submit`
queues onto the owning `State`, and the Foundation hands the Reactor that same
`State` it configured on the state database. What was still missing is the
*report*: `/health` named the durability/ack mode of every other Conductor
store family under `persistence.families` and said nothing about the
Reactor's, so an operator had to read the code to learn which store the
Reactor's events land in — and `docs/architecture/CONDACTOR-PERSISTENCE-MAP.md`
already named the mode (`fire-and-forget`) without any surface showing it.

This change closes that gap without introducing a second authority:

- `maistro.reactor.Reactor.persistence_backend` (new read-only property)
  reports the store the Reactor's state writes land in — the canonical
  `State` it was handed, or `None` when it has none. Nothing else about the
  Reactor's persistence changes: it still writes only through that `State`.
- `routes/health.py` reports the family beside the others: `fire-and-forget`
  when the Reactor writes through the canonical `State` (one writer on the
  configured state database, no durable-success claim returned to a caller —
  the mode the persistence map gives it), and `unavailable` when there is no
  Reactor or it has no `State` bound. An unreadable Reactor never wears a
  durable label, and the whole persistence map still degrades to
  `{"ack": "unknown", "families": {}}` when a probe raises.
- The persistence map records the family in its `/health` example and states
  that the Reactor's write authority is the canonical `State`, not a store of
  its own.

Collected evidence added here: 1 node ID in `packages/maistro-core/tests`
(`test_the_reactor_names_its_persistence_authority`) and 3 node IDs in
`packages/hive-conductor/backend/tests`
(`test_health_reports_the_reactor_persistence_authority`,
`test_health_reports_no_reactor_authority_when_there_is_none`,
`test_health_reports_no_reactor_authority_without_a_state`).
