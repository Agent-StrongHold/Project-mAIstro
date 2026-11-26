---
inventory-delta:
  packages/maistro-canvas/tests: +1
  packages/maistro-server/tests: +1
---

# #94 Canvas public-surface declaration guard

Repairs the exact-debt-ledger CI failure introduced by the governed
publish/export work: `list_design_exports` and `get_design_export` were new
`@router` handlers in `packages/maistro-server/src/maistro_server/api/canvas.py`
that vulture flags (FastAPI registers handlers from decorators, which static
import scanning cannot see), so they surfaced as unbanked `fastapi-route-handler`
debt against the trusted base, while the develop merge had simultaneously made
four recorded identities (`export_canvas`, `exports`, `formats` ×2) stale.

The fix declares canvas.py's handlers in the module's `__all__` — the same
statement a2a.py makes for the same reason — and prunes the now-unflagged
canvas.py rows plus the four stale rows from `quality/vulture-baseline.json`.

It also lands the recovered composite-pixels fix in
`maistro_canvas/canvas/publishing.py`: `_page_from` now carries the pinned
composite PNG into visible image layers (the committed code set `image_png=None`
with a "substituted below" comment but no substitution existed, so HTML/PPTX
exports silently dropped image pixels — a fake-success defect). A new provider
test pins the behavior.

- Added `TestPublicSurfaceDeclaration.test_all_covers_every_route_handler`:
  AST-scans canvas.py for `@router`-decorated functions and fails with an
  actionable message if any handler is missing from `__all__`, so the next
  handler cannot silently re-enter the dead-code ratchet.
- Added `test_html_export_embeds_image_layers_from_composite`: visible image
  layers must render as `<img>` carrying the base64 pinned composite PNG.

Net: +1 collected node ID on `packages/maistro-canvas/tests` and +1 on
`packages/maistro-server/tests`.
