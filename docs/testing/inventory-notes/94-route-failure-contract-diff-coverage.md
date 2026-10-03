---
inventory-delta:
  packages/maistro-server/tests: +11
---

# #94 Route failure contract for governed Canvas publish/export

Closes the last diff-coverage gap on the #94 governed export surface:
`maistro_server/api/canvas.py` measured 82.8% of its changed lines (17
uncovered), below the 90%-lines per-file floor, because only the happy paths
and two failure branches of the route's failure-mapping contract were
exercised. The uncovered lines were exactly the truthful-failure semantics the
issue demands, so the fix is evidence, not cosmetics —
`TestRouteFailureContract` pins each mapping:

- no `supported_formats` declaration → the route invents no refusal; the
  governed capability's own `EXPORT_FORMAT_UNSUPPORTED` refusal is what
  surfaces as the machine-readable 422 (route validation is a seam, not the
  authority);
- explicit `app.state.canvas_exports` shadows the exporter's store; with
  neither store the history endpoint is a truthful 501;
- compositor `HTTPException` passes through unchanged; a compositor crash and
  a composite-persistence failure each surface as truthful 502s naming the
  underlying cause — never fake success;
- `EXPORTER_DEPENDENCY_MISSING` (e.g. python-pptx absent) → 501 with the
  machine-readable code; an invocation-shaped `ExportFailed` → 502 carrying
  `invocation_id` / `invocation_status` for audit;
- the publish route maps provider failures identically to the export route;
- an unknown export version id is a 404, not a silent empty download.

Net: +11 collected node IDs on `packages/maistro-server/tests`. Locally
proven at measurement: `check-diff-coverage.py` against the candidate base
(c5e070d97) reports every measured #94 file at or above 90% lines / 80%
branch arcs.
