---
inventory-delta:
  packages/maistro-canvas/tests: 0
  packages/maistro-server/tests: +16
---
# #2406 evidence-driven coverage repair

The prior verification measured PgCanvasStore.get_blob at 20% changed-line
coverage and canvas_runtime at 83%. Existing registry tests replaced the fetch
function, lifecycle tests exercised only cooperative shutdown, and the migration
roundtrip wrote blobs without reading through the production store.

Server +16 (test_canvas_runtime.py): four gateway URL variants exercise the
real shared HTTP client and parser through MockTransport, checking Authorization,
model filtering and configured-default whitespace handling; six malformed/error
responses and two transport failures pin fail-closed admission. Four event-driven
shutdown cases cover a cancelled stuck tick, a cancellation-resistant tick with
late error logging, and already-finished success/failure outcomes. No wall-clock
speed bounds or invented asyncio.wait results. The existing idempotence test now
calls the actual shutdown function twice rather than just runner.stop().

Canvas 0: extend the existing real-PostgreSQL migration/store roundtrip with
committed blob readback through a new PgCanvasStore and unknown-reference
absence. Uses the root migration's canvas_blobs, not a substitute schema.

Validation: runtime file 33 passed; full server suite 697 passed/10 skipped;
full Canvas suite with required PostgreSQL legs 628 passed/3 skipped. Combined
branch coverage plus the core production-registration suite passes the exact
diff checker against 228dec753f (90% lines/80% arcs per changed file).
In-process mutation probes (separate pytest processes, no source edits) prove
that bypassing the fetch fails the request assertion, removing task.cancel()
fails the interruption assertion, and returning None from get_blob fails the
migration roundtrip readback. Each probe exited 1 at its intended assertion.
