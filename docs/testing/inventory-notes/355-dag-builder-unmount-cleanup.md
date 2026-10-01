---
inventory-delta:
  packages/hive-conductor/tests/e2e: +0
---

# 355 — DAG Builder closes its Run socket and drops its handlers on unmount

## What moved

Three Playwright specs in
`packages/hive-conductor/tests/e2e/dag-builder-unmount-cleanup.spec.ts` mount
and unmount the DAG Builder page while a Run stream is active (connected, no
terminal frame), settled-failed (terminal `failed` frame delivered, backend
closed), and unsettled-then-resumed (left mid-Run, remounted, re-run):

1. Unmounting during an active Run **closes the socket from the page** — the
   pre-fix page left it open — and **sends nothing over the wire**. The
   protocol has no client-cancel message, so navigation cannot cancel the
   durable backend Run (`services/graph_runner.execute_dag_streaming` records
   the projection before any frame is sent;
   `routes/ws._stream_dag_run` treats the disconnect as end-of-stream).
2. Unmounting after a settled failed Run leaves exactly one socket, no
   re-subscription, and no console/page errors.
3. A remount after leaving mid-Run refetches the canonical DAG list and detail
   (counted via request events), presents an idle Run button rather than
   resurrected component state, and a fresh Run opens **exactly one** new
   socket — subscriptions never stack — which then completes end-to-end.

The production change is in `packages/hive-conductor/frontend/src/pages/
DagBuilder.tsx`: the Run socket moved into a ref closed and handler-stripped
by an unmount cleanup, the mount-scoped DAG/agent/model loads each carry a
cleanup closure (the pattern `DagRuns.tsx` already used for its SSE
subscription and poll interval), and `handleRun` retires a leftover socket
before opening a new one.

## Why the count delta is zero

`check-suite-inventory.py` counts pytest node IDs. Playwright `*.spec.ts`
files are not pytest-collectable, so
`uv run pytest packages/hive-conductor/tests/e2e --collect-only -q` still
collects exactly the baseline 23 (`test_pm_workflow_api.py`); the three new
browser specs ride the existing `hive-conductor-e2e-ui` job unchanged and are
recorded in `packages/hive-conductor/tests/e2e/README.md` like every other
spec.

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
the first spec fails exactly at "the page closed the run socket on unmount"
(the close-observed poll times out), and passes with the fix. Both states
were served through the canonical containerized harness
(`docker-compose.test.yml`'s `hive` + `e2e-tests` services), where the full
suite — 105 tests including these three and the pre-existing
`dag-run-button-truthfulness.spec.ts` — passes in one run.
