---
inventory-delta:
  packages/maistro-core/tests: +1
---
# auto-147-6ac7

Adds a cross-instance resume regression proving the delegated child completes
through a yielded and completed canonical Attempt rather than direct Run
terminalization. The existing delegation receipt note remains the provenance
for the earlier receipt-validation case.
