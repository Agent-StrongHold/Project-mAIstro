---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
  packages/maistro-core/tests: +6
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

**`packages/hive-conductor/backend/tests/test_dag_agents.py` (+1)** — the
defect at the surface that had it: a DAG the Conductor runs is findable on the
canonical spine, with its NodeRuns and Attempts. The module-level
`InMemoryDurableRunStore` this replaces produced a run_id the audit trail named
and nothing could fetch — not `GET /v1/runs/{id}`, not retention, not another
replica resuming it.
