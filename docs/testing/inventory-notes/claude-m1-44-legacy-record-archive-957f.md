---
inventory-delta:
  packages/maistro-core/tests: +9
---
# claude-m1-44-legacy-record-archive

#44's last criterion — "historical graph executions remain reproducible" — and
the only one that had no test at all. The convergence moved Run, NodeRun and
Attempt identity onto the canonical spine, and `CanonicalDurableRunStore`
refuses a record whose Run the spine has never seen. That refusal is right for
new work and leaves every graph run persisted before #565 with no reader.

**`tests/graph/durable_runs/test_legacy_archive.py` (+9)** reads one back:

- the archived Run reproduces through today's canonical models — workspace,
  project, status and its Graph snapshot;
- so does what it *did*: both NodeRuns with their node ids, ordinals and
  statuses, and one completed Attempt under each. A projection that recovered
  a Run and lost its NodeRuns would satisfy "the record loads" while destroying
  the history the criterion is about;
- the traversal half comes out of the record, since an archived run has no
  `GraphContinuation` row;
- the spine does not know it and does not learn it by being asked — reading
  history must not write it;
- resumption is refused by name rather than quietly re-admitted under a new id,
  because a silent re-admission is two records for one execution and the caller
  could not tell;
- archived runs are findable by status, an unknown run is absent, a missing
  archive raises rather than reading as an empty history (which looks exactly
  like a migration that lost everything), and the read-only guarantee is
  SQLite's `mode=ro` rather than the class's good intentions.

**The fixture is captured, not generated.** `fixtures/pre_convergence_durable_runs.sqlite3`
came from running a two-node graph through `SqliteDurableRunStore` on the code
as it stood at `608f27e`, the commit before #565, and committing the database
byte for byte. A fixture written by today's models would only prove today's
models round-trip themselves — true of any schema, and silent about the
migration. The failure this guards against is a model or validator change that
makes *old* records unloadable, and only a record the old code actually wrote
can catch it.

Four vulture findings are banked: `attempts_for`, `list_run_ids` and `resume`
are `core-public-api-surface` (the archive is exported from
`maistro.graph.durable_runs`, and its callers are operators and downstream
products, not package-local code), and `row_factory` is the usual
sqlite3 attribute assignment.
