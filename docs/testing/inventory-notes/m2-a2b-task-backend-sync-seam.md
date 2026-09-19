---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---
# M2-A2b task backend sync seam

Adds a production-adapter regression test proving synchronous task reads use
`maistro.http.sync_client` and cannot fall back to a raw `httpx.Client`.
The same shared sync seam now governs Hive's provider activation requests; its
existing happy-path test is re-based onto that seam.
