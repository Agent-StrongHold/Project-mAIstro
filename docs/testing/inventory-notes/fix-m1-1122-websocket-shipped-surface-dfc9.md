---
inventory-delta:
  tests/: +4
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
- An undisposed CLI command fails closed as an unclassified CLI surface.

No tests removed or renamed.
