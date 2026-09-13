---
inventory-delta:
  packages/hive-conductor/backend/tests: +5
---
# issue-337-durable-dag-state

The three tests add the missing parity evidence for the node-metrics projection:

- a writer, an already-running replica refreshed from shared rows, and a fresh
  post-restart store read the same observation;
- replaying one canonical Attempt replaces rather than duplicates its metric;
- the bounded projection evicts its oldest row from both memory and durable
  records;
- production history inspection refreshes the shared projection before HTTP
  reads, closing the already-running replica freshness gap without changing
  the accepted direct-store/SSE cache contract.

DAG history, feedback outcomes, and user profiles already had focused parity
suites on this base. The implementation keeps their accepted ADR boundaries:
DAG SSE subscribers remain process-local, feedback without a projection is a
legacy compatibility path, and canonical execution identities are used when a
projection exists.
