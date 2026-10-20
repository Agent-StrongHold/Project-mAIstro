---
inventory-delta:
  packages/hive-conductor/backend/tests: +12
---
# issue-337-durable-dag-state

The tests add the missing parity and authorization evidence for the
node-metrics projection and the feedback correlation path:

- a writer, an already-running replica refreshed from shared rows, and a fresh
  post-restart store read the same observation;
- replaying one canonical Attempt replaces rather than duplicates its metric;
- the bounded projection evicts its oldest row from both memory and durable
  records;
- production history inspection refreshes the shared projection before HTTP
  reads, closing the already-running replica freshness gap without changing
  the accepted direct-store/SSE cache contract;
- workspace-scoped reads are fail-closed: a foreign observation is
  indistinguishable from a missing one, and an observation that names no
  Workspace is served to no HTTP reader;
- feedback refuses a missing or foreign run (404), a projection-only run
  without canonical identity (409), and an unknown node (404);
- per-node feedback correlates to the canonical NodeRun and its latest
  Attempt, never a borrowed projection id.

DAG history, feedback outcomes, and user profiles already had focused parity
suites on this base. The implementation keeps their accepted ADR boundaries:
DAG SSE subscribers remain process-local, and canonical execution identities
are required for every accepted feedback write — the projection-free
compatibility path is retired rather than kept as silently uncorrelated
feedback.
