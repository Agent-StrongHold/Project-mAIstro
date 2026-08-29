---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
  packages/maistro-core/tests: +33
---
# claude-m1-44-canonical-durable-store

`DurableRunStore` stops being a second system of record and becomes an
interface over the canonical spine (#44, ADR-082826-d9f5). Two suites.

**`tests/graph/durable_runs/test_canonical_durable_store.py` (+6)** —
`CanonicalDurableRunStore` writes a record's two halves to the two stores that
own them and assembles reads from both:

- a Run executed through it reads back with the same NodeRun and Attempt
  identities the walk produced, assembled from canonical rows rather than from
  a document;
- deleting nothing and asking the spine directly finds the whole execution
  history there, because that is now the only copy;
- a record whose Run the spine has never seen is refused rather than given a
  second identity — the thing an adapter would have done instead;
- a paused HITL frontier is answered and resumed through the projection, over
  an in-memory continuation store and over a SQLite one, because the
  continuation is the half that has to survive a restart;
- an unknown run is absent rather than an empty record.

**`tests/graph/durable_runs/test_continuation_conformance.py` (+27)** — one
contract, run against all three continuation backends, because the continuation
is the half of a durable graph run the canonical spine does not hold and so the
half a restart loses if any one backend disagrees.

The error arms are the point, and they were the gap. Nine assertions --
round trip, absent run, create collision, version advance, update of a run that
was never created, a version that did not advance (older *and* equal), and both
listings with and without the project filter and under limits -- times memory,
SQLite and PostgreSQL. A fence that is a read-then-write in one store and a SQL
predicate in another cannot be checked by testing one of them.

`packages/maistro-core/tests/conftest.py` adds `graph_continuations` to the
PostgreSQL scratch-table truncation for the reason #563 added `node_templates`:
rows that survive between runs mask a regression that stops writes happening.

Running it against a real server is what found the defect it now covers.
`PgGraphContinuationStore.get` read its JSONB column with
`model_validate_json`, which needs text -- but whether a JSONB column arrives
as text or as a dict depends on how the caller built the pool, and
`maistro.persistence.get_pool` registers a codec that hands back a dict. Every
read through a production-shaped pool would have raised. It uses
`runs.evidence_json.decode_payload` now, the answer this repository had already
written down for exactly this.

**`packages/hive-conductor/backend/tests/test_dag_agents.py` (+1)** — the
defect at the surface that had it: a DAG the Conductor runs is findable on the
canonical spine, with its NodeRuns and Attempts. The module-level
`InMemoryDurableRunStore` this replaces produced a run_id the audit trail named
and nothing could fetch — not `GET /v1/runs/{id}`, not retention, not another
replica resuming it.
