---
inventory-delta:
  packages/maistro-core/tests: +28
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

Two existing conformance gates caught the schema addition and were satisfied,
not bypassed: `test_retention_reference_inventory` required
`canonical_run_eval_scores` in the purge inventory (a `run_id`-bearing table
the purge must account for), so `retention_scope` gained the table and its
policy row — eval evidence is execution state, deleted with the Run, not
attribution history to preserve.
