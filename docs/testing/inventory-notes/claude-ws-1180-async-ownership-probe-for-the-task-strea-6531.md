---
inventory-delta:
  packages/hive-conductor/backend/tests: +7
---
# claude-ws-1180-async-ownership-probe-for-the-task-strea-6531

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

#1180 (partial): seven new tests, none removed or moved.

- `test_task_stream_event_loop.py` (+3) runs a real `ThreadingHTTPServer`
  that stalls `GET /tasks/{id}` for 2s behind `MaistroServerTaskBackend`, and
  pins the three properties the websocket stream needs: the event loop keeps
  ticking (max heartbeat gap < 0.25s; ~2.2s before the fix), cancelling the
  stream mid-stall returns promptly, and the synchronous `get`/`list_tasks`
  path reuses one owned client that `EngineService.stop()` closes.
- `test_engine_service.py` (+4) covers the new `get_async` on both backends
  (404 → None, non-404 errors raise, owner scoping on the local queue), that
  `iter_task_events` awaits the async probe rather than calling sync `get`
  and still fails closed for a non-owner, and that `stop()` is idempotent
  when no sync client was ever built.
- `test_adapter_ports.py` changes an assertion only (the Protocol's method
  set now includes `get_async`), so it adds no node IDs.
