---
inventory-delta:
  tests/: +5
---
# fix-m1-1122-websocket-shipped-surface-dfc9

Four new tests in `test_shipped_surface_truth.py` for #1122:

- `discover_backend_surfaces` finds a `@router.websocket(...)` route and
  reports it with the synthetic method `WEBSOCKET`, alongside an ordinary
  `@router.get(...)` route that must NOT be discovered (GET stays outside
  this gate's scope).
- A discriminatory fixture: an undisposed WebSocket route fails closed as
  an unclassified backend surface, the same as an undisposed mutating HTTP
  route already does.
- A Typer command and argparse subcommand are discovered as `CLI` surfaces.
- A published PEP 621 `project.scripts` entrypoint is discovered even when its
  module has only a standalone argparse parser, and an undisposed entrypoint
  fails closed as an unclassified CLI surface.
- An undisposed CLI command fails closed as an unclassified CLI surface.

No tests removed or renamed.
