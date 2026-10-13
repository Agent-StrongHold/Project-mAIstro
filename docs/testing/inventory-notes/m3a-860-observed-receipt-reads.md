---
inventory-delta:
  tests/: +7
---

# #860 — receipt load must read observed admissions

Seven collected cases exercise the soak HTTP worker and counters:

- The production task router, real canonical admission spine and two separate
  queues demonstrate 202 admission followed by 200 on the admitting replica and
  404 on its peer. The driver must use the observed task identity and must not
  hide the peer's process-local receipt gap by pinning reads to a replica.
- Five malformed/missing task identity cases must not invent lookup paths.
- Empty admission state records status 0 (no HTTP request); the recent receipt
  population stays bounded to 500; actual 503 read responses remain observable.

Before the driver repair, the production-router regression failed with 404
instead of 200 on the admitting replica. No background runner, model call or
PostgreSQL is used: these tests prove the workload contract, not exact-RC soak
acceptance, durable receipt visibility or physical-work recovery.
