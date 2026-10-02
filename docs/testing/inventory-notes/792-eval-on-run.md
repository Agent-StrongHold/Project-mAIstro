---
inventory-delta:
  packages/maistro-core/tests: +45
---
<!-- Measured by scripts/check-suite-inventory.py --update; see README.md. -->
# 792-eval-on-run

Issue #792 (M7-A3): eval scores become first-class evidence on the canonical
`Run`/`NodeRun`/`Attempt` spine instead of a sidecar. The suite grows a
`runs/test_eval_on_run.py` module that drives the new `RunEvalScore` record,
the append-only store contract, and the `eval_summary`/`open_re_eval_attempt`
seams across all three backends through the shared `spine` fixture.

What the tests pin, mapped to the issue's acceptance list:

- A planted failing dimension writes a durable record onto the producing Run,
  and the record names the Goal revision, Rubric revision, NodeRun and Attempt
  whose evidence it scored (read back through `get_eval_score` and
  `list_eval_scores`, not through the caller's copy).
- A passing and a failing dimension coexist on one Run; the summary reports
  `complete` without `passed` and names the failing dimension.
- Re-evaluation opens a new Attempt on the same NodeRun (`open_re_eval_attempt`),
  refuses a NodeRun that is not on the Run, refuses while a live Attempt is in
  flight, and leaves the failed record queryable after the retry supersedes it.
- "Eval complete" is derived only from persisted store records: an unscored Run
  is incomplete, a score held in a sidecar dict (the DesignProject/UI-state
  shape the contract forbids) is invisible to it, a different Rubric revision
  answers for nothing, and only persisting records completes it.
- The store refuses an eval record whose Run/NodeRun/Attempt triple is not one
  connected spine fragment, refuses duplicate `eval_id`s, and takes eval
  evidence with the Run when the Run is deleted.
- Model-level judge rules: deterministic scoring names no judge; model-judge
  and human records must name an agreeing judge.

The repair round added `runs/test_eval_on_run_pg_internals.py` (+11): the
PostgreSQL eval statements drove no SQL in the no-services coverage leg — the
`spine` fixture's PG cases skip without a server, so `pg_store.py`'s eval
paths measured at 23.5% and the per-file diff-coverage gate failed. Following
the `test_pg_store_internals.py` seam, a stand-in pool routes by statement
shape: the insert's column list and payload, every spine-guard refusal before
any INSERT, the table-only read paths, and the deletion order (`delete_run`
and the retention purge both take the eval rows before the spine rows they
name, batch-shaped `ANY($1::text[])`). Constraint enforcement and JSONB
behaviour stay with the PG-gated conformance leg; what the no-services leg
now proves is that the statements themselves are made, in order, with the
right columns.

Two existing conformance gates caught the schema addition and were satisfied,
not bypassed: `test_retention_reference_inventory` required
`canonical_run_eval_scores` in the purge inventory (a `run_id`-bearing table
the purge must account for), so `retention_scope` gained the table and its
policy row — eval evidence is execution state, deleted with the Run, not
attribution history to preserve.

Repair round (CI gates): the M7-A14 product-boundary tripwire
(`test_no_competing_execution_lifecycle_name`) scans production source for
competing lifecycle names, and this module's own docstring named the forbidden
token — reworded to describe the prohibition instead of uttering it. The
radon CC ratchet flagged `eval_summary` at grade C, so the projections were
extracted (`_validate_dimensions`, `_row_matches`, `_latest_by_dimension`),
leaving every block in the module at grade B or better. Two refusal behaviors
the extraction surfaced as uncovered branch arcs gained their negative tests:
a summary over zero dimensions, and a summary asking twice for one dimension,
each refused with `ValueError` — completeness over a vacuous dimension set
would otherwise read `complete` without any evidence existing.

Repair round (develop sync): develop's `047_capability_binding_revocations`
claimed the same revision number while this branch was open, so the eval
migration re-parented onto it — and when develop's own
`048_canvas_job_retry_backoff` (#398) then claimed that number too, the eval
migration re-parented onto *that* as `049` — the renumbering this chain
performs on every develop collision. Proving the chain on a live PostgreSQL 18
server then caught the migration assuming a fresh database: a bare
`create_table` fails the stamp-back adoption test with `DuplicateTable`, so
049 now uses `IF NOT EXISTS` like 046/047. The chain-level guards were
tightened to match: `test_migration_chain` pins `canonical_run_eval_scores`
in `EXPECTED_TABLES` (a live-catalog set equality, so an unapplied or dropped
eval table fails CI), and the effect-index suite asserts the single linear
head is `049`. The eval
store/validator identities are referenced in `_vulture_whitelist.py` (external
consumers, implicit Pydantic invocation) so the per-identity vulture ledger
stays exact without banking them as debt.
