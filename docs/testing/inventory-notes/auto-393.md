---
inventory-delta:
  packages/maistro-canvas/tests: +60
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

`test_compositor.py` swaps one test in place (zero-scale is now a typed
rejection instead of a silent skip), so its count is unchanged; the net +60
is the new file.
