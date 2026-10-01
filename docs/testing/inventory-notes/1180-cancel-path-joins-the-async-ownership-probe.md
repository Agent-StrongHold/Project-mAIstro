---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
---
# 1180-cancel-path-joins-the-async-ownership-probe

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

#1180: three new tests, none removed or moved. The earlier round
(`claude-ws-1180-async-ownership-probe-for-the-task-strea-6531`) moved the
websocket stream's ownership probe off the loop; this one closes the last
async-path caller of the sync probe.

- `cancel_task` — awaited by the async `DELETE /v1/missions/{id}` route —
  still called `MaistroServerTaskBackend.get`, the synchronous 30s-timeout
  httpx GET, on the event loop. It now awaits `get_async` like the stream
  does, so `services/engine.py` no longer performs blocking backend I/O on
  any async path.
- `test_task_stream_event_loop.py` (+2) drives the real stalling server
  through `cancel_task` end to end: while the ownership probe stalls, the
  loop keeps ticking (max heartbeat gap < 0.25s) and the sync client is
  never even constructed; cancelling the caller mid-stall returns promptly
  instead of waiting out the backend timeout. The shared test server gains a
  `do_DELETE` so `MaistroServerTaskBackend.cancel` completes the flow.
- `test_engine_service.py` (+1) pins the seam itself: sync `get` raises if
  the engine ever touches it from `cancel_task`, the probe still fails
  closed for a non-owner, and `cancel` is not called when the probe refuses.
