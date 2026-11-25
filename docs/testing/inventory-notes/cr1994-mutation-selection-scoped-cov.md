---
inventory-delta:
  tests/: +4
---
# cr1994-mutation-selection-scoped-cov

Two additions in `tests/test_mutation_select_tests.py`; nothing removed. They
pin the root cause of the #1994 CI mutation-gate failure: the selector's
pytest argv carried pytest-cov's bare `--cov` ("record everything") alongside
its own `--cov=<dir>`, and the bare flag wins — so a test inside the scope
that imports a scratch module and deletes it before the run ends (the
extension lifecycle proof does exactly this) left the coverage data file
referencing a vanished path, and `coverage json --show-contexts` died with
"No source for code" before any selection could be produced. The gate never
reached the mutants; the debt was the tooling, not governance.

**`TestTheMeasuredScopeIsTheDeclaredSource::test_the_pytest_run_is_scoped_and_never_records_everything`.**
Asserts the selector's own argv contract: no bare `--cov`, exactly one
scoped `--cov=<source dir>`, and `coverage json` carries `--ignore-errors`.
Fails against the pre-fix argv, which passes both the bare flag and omits
the ignore.

**`TestTheMeasuredScopeIsTheDeclaredSource::test_an_ephemeral_module_deleted_by_the_suite_does_not_break_selection`.**
The real failure, end to end: a real pytest run whose suite imports a
scratch module and `rmtree`s it mid-run. Under the old argv `coverage json`
red with "No source for code"; under the fixed argv selection completes and
still attributes the killing test. `--ignore-errors` cannot mask a lost
critical source: a report with no entry for the target file still fails
`_coverage_file_entry`.

## PR-gate budget repair round (merge of origin/develop c9636e99f1 + mutation.yml cap)

The selection-scoping fix above removed the bare-`--cov` crash, but the gate
still starved: run 45645094537 at PR head 5de7d17254 was killed with
"The job has exceeded the maximum execution time of 45m0s" 25m into
`mutation_pr_gate.py`, inside `select()` — and the step log shows zero
selection output before the cancel. Selection for this PR's one critical
overlap, `privilege.py`, re-runs the whole core suite under coverage
(~30m on CI; run 45574782108 step 08:16:44Z→08:46:57Z), because the
production dispatch (`resolve_script_tests(...) or resolve_package_tests(...)`,
mutation_critical.py) widens privilege.py to bare `packages/maistro-core/tests`
— no `tests/maistro/test_privilege.py` mirror exists. Other PRs' mutation runs
finish in ~15-25m because their critical overlaps resolve to narrow scopes.

Repair, evidence-backed and non-weakening (pass/fail logic, critical list,
fail-closed behaviors untouched):

- `.github/workflows/mutation.yml` pr-gate `timeout-minutes: 45` → `150`,
  with the measured numbers cited in place. 150 = widest-scope selection
  (~30m) + collection + a nightly-shard-scale mutation phase (packets get
  60m each) + cold-runner overhead, with headroom so the required producer
  emits a verdict instead of a permanent CANCELLED (`gates-ran` stayed red
  because it never observed a completed mutation run on this PR).
- `tests/test_mutation_targets.py` (+2, class
  `TestPrGateBudgetCoversTheWidestMappedScope`):
  `test_at_least_one_critical_source_widens_to_a_whole_suite_directory` pins
  the widening assumption through the production dispatch (fails if a mirror
  ever de-widens privilege.py, telling the author to re-measure the floor),
  and `test_the_pr_gate_budget_is_not_starved_below_the_measured_floor`
  parses the shipped workflow and fails against the 45m cap that cancelled
  #1994's gate (verified: the predicate fails on the pre-repair file at
  merge commit 2ce345573a, passes at 150).

Develop sync: origin/develop tip `c9636e99f1` (abandoned-Attempt recovery
activation) merged conflict-free; `quality/` numstat vs origin/develop shows
only this branch's two intended files and the vulture multiset row count is
identical (15 = 15). Gates at the merged head: ruff check + format clean,
root + server inventory gates ok, principal-identity ratchet "4 tolerated →
0 current, none new", mutation governance validate ok, issue test paths
(privilege, principal-identity fitness, server auth) 71 passed.
