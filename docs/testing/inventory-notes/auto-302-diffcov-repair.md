---
inventory-delta:
  packages/maistro-rsi/tests: +9
---
# auto-302-diffcov-repair

Nine tests added to `packages/maistro-rsi/tests` for the #302 CI repair: the
diff-coverage gate failed on changed promotion-boundary lines in
`local_loop.py` and `__main__.py` that no test executed — all of them
fail-closed containment paths.

Six tests in `test_local_loop.py` exercise the uncovered promotion boundary:

- a crashing quarantine scanner is a refusal ("quarantine gate failed"),
  baseline unmoved;
- gate evidence naming a commit the `--ff-only` did not land reports
  not-promoted ("promotion did not land on the baseline") — the baseline is
  the authority on what landed;
- the #110 mechanical path: decisive evidence (composite at the floor) is
  kept with no judge and no review records, pinning the floor as exclusive
  (just-below escalates to judgment and cold-start parks, flagged);
- a judgment-path promotion predicted keep (p >= theta, seeded reviewer
  state) lands and persists its kept-review record only after the merge;
- unavailable judgment machinery parks the candidate
  ("promotion review unavailable") instead of waving it through.

Three tests in the new `test_run_genome_summary.py` pin `__main__.py`'s
genome-summary printing (header/champions/reliability rounding/bench lines,
the empty-population degenerate path) and the `--genome-db` wiring that
prints the summary after the loop runs.
