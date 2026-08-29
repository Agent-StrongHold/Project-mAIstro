---
inventory-delta:
  packages/maistro-core/tests: +3
---

# M1 #327 PostgreSQL session concurrency evidence

This change adds three real-PostgreSQL persistence tests proving that concurrent multi-message appends serialize into unique contiguous sequence numbers, a failed batch commits no prefix, and a normal retention sweep cannot delete fresh concurrent appends.
