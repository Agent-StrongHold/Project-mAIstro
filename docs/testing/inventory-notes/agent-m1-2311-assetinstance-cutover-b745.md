---
inventory-delta:
  packages/maistro-server/tests: +2
---
# agent-m1-2311-assetinstance-cutover-b745

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

Server **+2**: both tests in `test_main.py::TestLifespanCanvasRunnerStart`
pin the `CANVAS_SERVER_CONSUMER_ENABLED` opt-out for the in-process Canvas
job consumer started by #2311. `test_disabled_by_configuration_skips_the_start`
asserts that a deployment running the external `maistro-canvas-worker`
service can stop the server process from competing for the shared
`generation_jobs` queue — the flag gates `_start_canvas_job_runner` itself,
so a configured-off server neither claims nor burns attempts on `refine`
jobs it cannot execute — and that the skip is logged truthfully.
`test_the_opt_out_defaults_off_so_default_composition_is_unchanged` asserts
default `Settings` keep the consumer enabled, so the default composition's
"runner started in the shipped process" contract (#2311) is unchanged.

No canvas delta: the same batch renamed the legacy layer-delete route
handler to `remove_layer` (aligning with the sibling handlers' name-the-store-
operation convention and the `shipped-surface-truth` entry), which changes no
collected test identity — `test_delete_layer_mainline` drives the route by
URL. The genuinely dead `GroundPlane.perspective` field (defined, never read
or constructed anywhere in the repository) was removed with it; vulture
ledger rows for both eliminated findings were pruned in the same change.
