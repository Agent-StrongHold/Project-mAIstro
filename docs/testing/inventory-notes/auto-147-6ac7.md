---
inventory-delta:
  packages/maistro-core/tests: +1
---
# auto-147-6ac7

Adds a cross-instance resume regression proving the delegated child completes
through a yielded and completed canonical Attempt rather than direct Run
terminalization. It also proves an inline subgraph remains request context on
an opaque child node because the A2A transport sends only the text task; the
child never claims evidence for work that was not transmitted. The existing
delegation receipt note remains the provenance for the earlier receipt-
validation case.
