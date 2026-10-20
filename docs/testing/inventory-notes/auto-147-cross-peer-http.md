---
inventory-delta:
  packages/maistro-core/tests: +1
---
# auto-147 cross-peer HTTP

Adds a hermetic end-to-end cross-instance delegation regression. The node uses
the real `GuestPeerManager` and shared HTTP seam, receives a peer task receipt,
and proves the resulting child Run keeps its parent Run/NodeRun links and A2A
receipt provenance.
