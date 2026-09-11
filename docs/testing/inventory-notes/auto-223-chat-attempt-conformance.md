---
inventory-delta:
  packages/maistro-core/tests: +9
---
# auto-223 chat Attempt conformance

Adds three chat execution tests to the shared Run spine suite. The nine
collected cases drive `ChatAttemptExecutor` against the in-memory, SQLite and
PostgreSQL stores and verify that successful, refused and raised turns leave
the same NodeRun and Attempt lifecycle, including the bounded outcome,
executor id and handling-agent evidence.
