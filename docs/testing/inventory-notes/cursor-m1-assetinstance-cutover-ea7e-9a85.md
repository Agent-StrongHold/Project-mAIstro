---
inventory-delta:
  packages/maistro-canvas/tests: +2
  packages/maistro-server/tests: +2
---
# cursor-m1-assetinstance-cutover-ea7e-9a85

CONNECT proof for ADR-044 AssetInstance modules (#2311).

Adds two tests in `test_asset_instance_connect.py`:

- the composition `_ASSET_INSTANCE_CONNECT` tuple roots every former
  `canvas-assetinstance` disposition module (store, compositor, executor,
  routes factory, tool);
- `build_asset_instance_surface` binds an `AssetTool` and a `/v2/canvas`
  asset router (definitions/instances) without colliding with LayerRecord
  design paths.

Adds two coverage arcs in `test_main.py` for `_wire_canvas_assetinstance`:

- idempotent once `canvas_asset_tool` is bound (second call keeps the same
  tool instance);
- remount skip when `canvas_asset_router_mounted` is already True but the
  tool is still absent (covers the early-return branch that previously
  left `main.py:202` uncovered).

LayerRecord `PgCanvasStore` and `canvas.tool` RETIRE stay untouched; runner
compose start is deferred. Reachability baseline drops the five asset
modules; the CONNECT disposition group is pruned.
