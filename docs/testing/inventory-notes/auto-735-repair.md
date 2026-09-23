---
inventory-delta:
  packages/maistro-canvas/tests: +2
---
# auto-735 repair

The Canvas route suite gains one regression case proving the authenticated
principal is forwarded into canonical generation admission. The canonical
integration suite adds a production-router case proving the package-owned
builder starts its worker on application startup, completes the receipt, and
persists the resulting NodeRun/Attempt through the bound runtime instead of
accepting an independent executor.

Reachability boundary: the package-owned builder now owns worker startup once
an application mounts its router. The shipped `maistro-server` app still
mounts only its separate `/v2/canvas` CRUD proxy; wiring that server boundary
to this generation runtime is outside the Canvas-only collision boundary and
remains a deferred integration seam.
