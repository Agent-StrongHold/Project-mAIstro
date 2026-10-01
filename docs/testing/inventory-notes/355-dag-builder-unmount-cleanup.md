---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
  packages/hive-conductor/tests/e2e: +0
---

# 355 — DAG Builder closes its Run socket and drops its handlers on unmount

## The safe-point contract

The Run socket's one safe close point is the backend's `started` frame:
`services/graph_runner.execute_dag_streaming` is an async generator that
yields `started` **before** awaiting `execute_dag`, so the durable Run — and
its `_record_run_projection` projection via `on_result` — only comes into
existence once the consumer resumes past that frame
(`routes/ws._stream_canonical_run`). Closing a CONNECTING socket, or racing
the ack, silently cancels a Run the user explicitly requested. Unmount
therefore detaches immediately once the Run is acknowledged or settled, and
before that only arms a `detach` flag the frame handlers act on at the safe
point.

## What moved

Four Playwright specs in
`packages/hive-conductor/tests/e2e/dag-builder-unmount-cleanup.spec.ts`
mount and unmount the DAG Builder page while a Run stream is
pre-acknowledgement (connected, `started` not yet delivered),
acknowledged-and-running (past `started`, no terminal frame),
settled-failed (terminal `failed` frame delivered, backend closed), and
unsettled-then-resumed (left mid-Run, remounted, re-run):

1. Unmounting **before the ack** does **not** close — that would cancel the
   requested Run. When the backend's `started` frame later arrives on the
   still-open socket, the armed cleanup detaches: socket closed, handlers
   nulled, nothing sent, no post-unmount state update.
2. Unmounting during an **acknowledged, still-running** Run closes the socket
   from the page immediately (the pre-fix page left it open) and **sends
   nothing over the wire** — the protocol has no client-cancel message, so a
   remount resumes from canonical state (DAG Runs), not a dead socket.
3. A **settled failed** Run leaves exactly one socket, no re-subscription,
   and no console/page errors.
4. A **remount after leaving mid-Run** refetches the canonical DAG list and
   detail (counted via request events), presents an idle Run button rather
   than resurrected component state, and a fresh Run opens **exactly one**
   new socket — subscriptions never stack — which then completes end-to-end.

The production change is in `packages/hive-conductor/frontend/src/pages/
DagBuilder.tsx`: the Run socket lives in a `liveRunRef` (`LiveRun`: socket +
`started`/`settled`/`detach` flags); the unmount cleanup either detaches
immediately (ack/settled) or arms `detach` for the handlers; the
mount-scoped DAG/agent/model loads each carry a cleanup closure (the pattern
`DagRuns.tsx` already used for its SSE subscription and poll interval); and
`handleRun` retires a leftover run before opening a new one.

`test_graph_runner.py` gains one pytest test pinning the backend half of the
contract: `execute_dag_streaming` starts no Run and records no projection
until the consumer resumes past the `started` frame.

## Why the e2e count delta is zero

`check-suite-inventory.py` counts pytest node IDs. Playwright `*.spec.ts`
files are not pytest-collectable, so
`uv run pytest packages/hive-conductor/tests/e2e --collect-only -q` still
collects exactly the baseline 23 (`test_pm_workflow_api.py`); the browser
specs ride the existing `hive-conductor-e2e-ui` job unchanged and are
recorded in `packages/hive-conductor/tests/e2e/README.md` like every other
spec. The backend test is the `+1` under `packages/hive-conductor/backend/tests`.

## How the tests observe the socket

`routeWebSocket` was tried first and works for full page loads, but its
interception silently misses sockets a client-side-routed (SPA) page opens —
and the unmount assertions specifically need in-page SPA navigation, since a
`goto` reload destroys every connection regardless of cleanup. The spec
therefore replaces `window.WebSocket` with an instrumented fake via
`context.addInitScript` (the Run socket is the only WebSocket the SPA ever
opens), recording every `close()` call, the handler references present at
close time (the fix nulls them before closing), and every `send()` the page
makes, while frames are driven from the test via `serverSend`/`serverClose`.

Leak-detection was proven against the bug, not just the fix: with the base
head's frontend (socket created in a click handler with no lifecycle tie),
the close-on-unmount poll times out exactly as designed, and passes with the
fix. Both states were served through the canonical containerized harness
(`docker-compose.test.yml`'s `hive` + `e2e-tests` services).
