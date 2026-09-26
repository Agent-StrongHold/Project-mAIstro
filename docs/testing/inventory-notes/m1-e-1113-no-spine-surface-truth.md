---
inventory-delta:
  packages/hive-conductor/backend/tests: +4
---
# M1-E #1113 no-spine surface truth

Adds coverage for the repair of Graph-running support surfaces when Hive has no
canonical Container spine:

- model hill-climbing cannot convert an unavailable run into a cheaper winner;
- optimizer validation returns an explicit `unavailable` result with no
  validated proposals;
- the authorized chat hill-climb tool returns the same degraded capability
  result instead of a generic error;
- a second Hive composition reads a completed registered-DAG Run from the
  shared canonical stores.
