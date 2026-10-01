---
inventory-delta:
  packages/hive-conductor/backend/tests: +12
---

# 1183 — DAG streaming is live, keepalive-aware, and explicit about lost events

## Contract under test

`services/graph_runner.execute_dag_streaming` has two modes under one product
contract (#1183):

- **Live** (an `on_event` sink attached — the websocket route's mode): node
  frames stream while the canonical Run is in flight; each frame is durably
  recorded into the `dag_run_store` projection (via
  `services/dag_run_live.LiveRunProjection`) **before** it is published, and
  stamped with the projection's per-run sequence number. Idle stretches emit
  bounded `heartbeat` frames (`STREAM_HEARTBEAT_SECONDS`); a progress channel
  overflow (consumer stopped reading) is announced with a `resync` frame and
  healed by a canonical-truth replay of every node whose live frame was lost.
  Closing the stream cancels the in-flight Run (#355 semantics preserved).
- **Replay** (no sink): the historical wait-then-project behavior, kept
  deterministic for direct callers and pinned by the pre-existing tests.

Live per-node events originate in the real legacy node adapter
(`LegacyConductorNode._execute` → `_emit_progress`) carrying the executing
NodeRun's canonical identity (`run_id`/`node_run_id`/`attempt_id` from
`NodeContext`), threaded through `canonical_dag_runner.execute_dag(on_event=)`.
The SSE route (`routes/dag_runs.py`) now emits `seq` on every event and an
explicit `event: pm_resync` marker when a delivered seq jumps
(the subscriber queue overflowed or the replayed history was trimmed).

## What moved

Nine backend tests:

- `tests/test_graph_runner.py`: live mid-run frame delivery with a walk held
  at a barrier (proves frames arrive before settlement, durable-before-sent,
  no duplicated terminal replay); bounded heartbeats for idle work; resync +
  exactly-once convergence when the progress channel overflows; abandoning a
  live stream cancels the in-flight Run.
- `tests/test_dag_run_store.py`: monotonic per-run `event_seq`/`seq` (survives
  the `MAX_EVENTS_PER_RUN` trim), durable counter across a record round-trip,
  slow-subscriber overflow leaves a seq-detectable gap instead of silence.
- `tests/test_dag_run_scope.py`: SSE events carry `seq`; no resync for
  contiguous history; trimmed-history replays open with an explicit
  `pm_resync` naming `last_seq`/`resumed_at`/`missed`/`recover`.
- `tests/test_dag_execution_transport_parity.py`: the ws Run's projection is
  recorded incrementally with contiguous sequence identity (and the started
  frame announces the heartbeat cadence); `LiveRunProjection` rows are born
  scoped to the authorized Workspace, so mid-run inspection/SSE authorize
  before any terminal result.

One pinned record-shape test gained the new durable `event_seq` field
(`test_dag_run_history_durability.py`) — a deliberate store schema addition,
not a weakening.

## Not covered here

The Playwright unmount specs (`dag-builder-unmount-cleanup.spec.ts`) drive a
real browser and are not part of the unit battery; the ws frame vocabulary
they pin (`started` ack deferral, close-cancels) is unchanged and re-pinned at
the unit level by the live-mode tests above.
