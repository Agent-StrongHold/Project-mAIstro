---
inventory-delta:
  packages/maistro-canvas/tests: +1
---
# auto-735 repair

The Canvas route suite gains one regression case proving the authenticated
principal is forwarded into canonical generation admission. The composition
seam is covered by the existing canonical integration flow after it is wired
through the package-owned runtime builder.
