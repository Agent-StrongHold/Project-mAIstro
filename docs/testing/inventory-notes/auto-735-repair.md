---
inventory-delta:
  packages/maistro-canvas/tests: +2
---
# auto-735 repair

The Canvas route suite gains one regression case proving the authenticated
principal is forwarded into canonical generation admission. The canonical
integration suite adds one production-router case proving the package-owned
builder admits a Run through the bound runtime instead of accepting an
independent executor.
