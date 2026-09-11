---
inventory-delta:
  packages/maistro-core/tests: +3
---
# auto-223 chat Attempt conformance

Adds one parametrized chat execution test to the shared Run spine suite. The
three collected cases drive `ChatAttemptExecutor` against the in-memory,
SQLite and PostgreSQL stores and verify that a successful chat response leaves
one durable NodeRun and Attempt with the bounded outcome, executor id and
handling-agent evidence.
