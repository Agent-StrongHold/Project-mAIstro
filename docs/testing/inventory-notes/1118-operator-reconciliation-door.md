---
inventory-delta:
  packages/hive-conductor/backend/tests: +52
  packages/maistro-core/tests: +43
---

# Scoped operator Invocation reconciliation

Fifty-two focused HTTP cases exercise the actual router and authorization
middleware with SQLite Invocation state and quota reservations. They cover
APPLIED replay, NOT_APPLIED reattempt, INDETERMINATE holds, active dispatch,
stale forms and concurrent evidence, bounded database cursor pages, canonical Container composition,
revoked policy at ordinary reattempt, unreadable persisted scope, explicit Project grants/ancestor denies,
legacy unscoped records, no actor/source spoofing, secret-safe errors, bounded
bodies/pages, and durable audit history. Partial quota failure is retried through
the public HTTP entry after re-reading the accepted revision.

The same suite drives RunExecutionService: an eligible waiting NodeRun receives
Attempt ordinal 2, while a terminal Run remains closed after effect settlement.
No provider status endpoint, terminal-Run reset or automatic permission grant is
introduced. See docs/api/invocation-reconciliation.md for authority and remaining
continuation boundaries.

Two memory/SQLite cases verify scope, staleness, tie-breaking cursor order and
SQL-side limits before deserialization, including an unreadable foreign record.
A native PostgreSQL counterpart is collected by the unchanged quota PG producer,
including a non-UTC database session and naive UTC legacy timestamps.

Eight cases drive the actual main.app middleware stack without its lifespan.
They verify fixed/chunked request caps before version JSON parsing, secret-safe
Accept/query/body negotiation errors, and successful equivalent operation for
all three supported selectors. A core compatibility test rejects a global-only
store rather than falling back to unbounded discovery.

Thirty-nine core service cases independently exercise the actual memory/SQLite
stores, canonical Workspace/Project authorization, inherited denies, revocation,
missing/foreign/legacy/unreadable records, bounded cursor discovery, and governed
revision-fenced settlement. The core producer measures this authority directly:
Hive's separately scoped coverage producer cannot supply core service coverage.
Stale forms and real store compare-and-swap conflicts preserve the winning row
without reporting rejected operator evidence as accepted.
