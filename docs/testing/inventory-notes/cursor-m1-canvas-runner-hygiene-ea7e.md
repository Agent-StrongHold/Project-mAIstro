---
inventory-delta:
  packages/maistro-canvas/tests: +1
---
# cursor-m1-canvas-runner-hygiene-ea7e

CONNECT for `maistro_canvas.canvas.runner`: replace composition's
`importlib.import_module` edge with a static `CanvasJobRunner` import so
the reachability graph sees the runner on the `maistro-canvas-worker` /
`build_canvas_runtime` path (#93).

Adds one test pinning the static import. Prunes `canvas-job-runner`
disposition and the reachability baseline row. Matrix ownership drops
the `(unreachable)` annotation on `canvas.runner` (share stays `few`).
