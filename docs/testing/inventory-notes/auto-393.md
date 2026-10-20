---
inventory-delta:
  packages/maistro-canvas/tests: +88
  packages/maistro-server/tests: +7
---

# #393 Canvas layer scale bounded before image allocation

Adds `packages/maistro-canvas/tests/test_scale_limits.py` (60 node IDs) pinning
the #393 contract that a layer's `scale` can no longer reach `PIL.resize`
unbounded (a `scale=1e6` payload computed a ~10^12-pixel resize target —
memory/CPU denial of service):

- `validate_scale` boundary table + two Hypothesis property tests (arbitrary
  IEEE-754 floats incl. NaN/±inf; arbitrary JSON scalars incl. string-encoded
  `"1e6"`/`"nan"`, bools, null): every input is either a valid finite scale
  inside the server cap or a typed `LayerScaleLimitError` — never a crash,
  never a silent acceptance.
- `scaled_dimensions` / `PixelBudget`: computed resize targets are bounded by
  the server-configured per-side, per-image and cumulative per-request pixel
  caps (`LayerPixelBudgetError`) *before* allocation, including extreme-aspect
  and cumulative multi-layer abuse.
- End-to-end compositor, HTTP route and agent-tool tests: the demonstrated
  payload is rejected before any `Image.resize` call (asserted via a resize
  spy), the error is explicit (typed code / 422), and nothing is persisted.
- Worker-timeout and server-configuration tests: `CompositeTimeoutError`,
  env-var overrides, malformed-override fallback, and Pillow's decompression
  guard pinned to the per-image cap.
- CI-repair round (+13): the composite spec-application surface
  (x/y/scale/rotation/z_index/visible, unknown-layer skip, no-spec render,
  default pixel-budget construction), the upload action (missing source,
  happy path, typed worker failure persisting nothing), and the typed
  422/422/504 rejections through the HTTP composite and export routes
  (including the stored-composite export path, persisting nothing on
  rejection).

`test_compositor.py` swaps one test in place (zero-scale is now a typed
rejection instead of a silent skip), so its count is unchanged; the net +60
is the new file.
- Atomicity repair (+3 in `test_scale_limits.py`): a rejected `transform` no
  longer writes the sibling `x`/`y` fields (validate-then-assign), and a
  composite whose render is rejected mid-flight (pixel budget, worker
  timeout) no longer commits the request's transforms to the live session
  canvas — the specs are applied to a projection and committed only on
  success. The third test pins that a valid scale stores the validated value.
- Deep-review repair (+12 canvas, +7 `maistro-server/tests`): the four
  allocation holes the round-2 review found are closed and pinned —
  `TestScaleValidatedBeforeDecode` (a rejected scale never fetches/decodes:
  `composite()` validates before the store round-trip, `_composite_layers`
  before `Image.open`), `TestDecodedPixelCap` (the `[cap, 2*cap)` window
  where Pillow only *warns* now rejects typed on compositor, tool and
  upload paths, and Pillow's raw `DecompressionBombError` is translated
  into the typed error), `TestRotationBoundingBox`
  (`rotate(expand=True)`'s ~sqrt(2)-area bounding box is computed, capped
  per-side/per-image, and charged to the per-request budget *before* the
  rotation allocates — asserted via a rotate spy), and
  `TestTypedCompositorLimitErrors` in the server suite (publish/export map
  `LAYER_SCALE_OUT_OF_RANGE`/`LAYER_PIXEL_BUDGET_EXCEEDED` to 422 and
  `COMPOSITE_TIMEOUT` to 504 by stable code, matching the canvas routes,
  while an untyped provider failure stays a truthful 502). All ten
  regression-naming tests were demonstrated to fail against the pre-fix
  code before landing.
