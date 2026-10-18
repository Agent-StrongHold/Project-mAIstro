---
inventory-delta:
  packages/maistro-core/tests: +9
  packages/maistro-server/tests: +1
---
# auto-223 chat Attempt conformance

Adds three chat execution tests to the shared Run spine suite. The nine
collected cases drive `ChatAttemptExecutor` against the in-memory, SQLite and
PostgreSQL stores and verify that successful, refused and raised turns leave
the same NodeRun and Attempt lifecycle, including the bounded outcome,
executor id and handling-agent evidence. The server package adds one public
endpoint test proving a completed chat turn's NodeRun is visible through
`GET /v1/runs/{run_id}/node-runs`.
