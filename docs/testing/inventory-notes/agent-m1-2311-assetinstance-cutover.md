---
inventory-delta:
  packages/maistro-canvas/tests: -11
  packages/maistro-server/tests: +17
---
# agent-m1-2311-assetinstance-cutover

#2311 ADR-045 cutover slice: RETIRE `maistro_canvas.canvas.tool`, start
`CanvasJobRunner` in the server composition.

Canvas **-11**: the retired tool's dispatch-surface tests left with the
module (the `execute_canvas` scale/spec/upload/rotation classes in
`test_scale_limits.py`, 21 tests); the shared `limits.py` coverage they
leaned on stays through the compositor and route classes. Added
`test_asset_instance_parity.py` (10 tests): the structural parity contract
that authorized the retirement — legacy action-set → AssetTool counterpart
coverage, back-to-front z ordering (occlusion order + store listing),
append-only history round-trip, sheet revision bump, TEXT-kind round-trip.

Server **+17**: `test_canvas_runtime.py` covers the composition module that
starts the runner in-process — governed image client (canonical-context
refusal, unregistered-Binding refusal, governed call shape with stable
effect key, truthful-unsupported refine), fail-closed model registry,
warden verdict mapping, blob-store adapter, and start/stop through
`build_canvas_runtime` with the image Binding registered — plus two
`test_main.py` lifespan tests pinning the start/skip decision (durable spine
+ wired store → started; either missing → truthful logged skip).
