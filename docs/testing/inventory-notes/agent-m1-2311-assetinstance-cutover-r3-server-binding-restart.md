---
inventory-delta:
  packages/maistro-server/tests: +2
---
# agent-m1-2311-assetinstance-cutover-r3-server-binding-restart

Server **+2**: both tests in `test_canvas_runtime.py::TestStartStopCanvasJobRunner`
pin the restart behavior of the fixed-id image Binding that
`start_canvas_job_runner` registers. The first container restart of the
compose stack crashed startup (`ValueError: Binding 'canvas-image-gateway'
is immutable and already registered`) because the registration re-`put` a
freshly constructed record every boot: the binding id is fixed while
`created_at` defaults to `now()`, so the durable store saw two different
records for one id and enforced its immutability rule. Fresh-state tests
could never see this; the live `docker compose up` bring-up did.
`test_restart_against_a_persisted_binding_reuses_the_record` asserts the
second boot reuses the first boot's persisted record (identical record, no
second `put`), and `test_a_conflicting_persisted_binding_refuses_to_start`
asserts a persisted record whose authorization shape (capability /
credential refs / scope) differs from what the composition registers fails
the start truthfully instead of running under a stale authority. The
production fix is the read-first registration in
`maistro_server/canvas_runtime.py`.
