---
inventory-delta:
  tests/: +5
---

# Required PostgreSQL matrix contexts

Five added collected cases protect the merge queue from a skipped matrix that
reports one unexpanded name instead of its two required concrete check names:

- Four path-scope cases cover docs-only, Hive evolution, migrations, and shared
  dependencies. The classifier must remain truthful, while the PostgreSQL job
  and its steps cannot be disabled by that scope result.
- One case preserves both PostgreSQL versions, their exact required display
  names, real pgvector services, failure propagation, migration round trips,
  persistence/container suites, and the non-skippable Workspace PostgreSQL leg.

The existing all-specialized-jobs wiring case is renamed to describe the matrix
exception. It retains every non-matrix guard assertion and replaces the old
PostgreSQL scope guard expectation with the stronger unconditional-matrix
requirement. No pytest skip/xfail marker or source suppression is introduced.
The classifier, required-check policy, and gates-ran evaluator are unchanged.
