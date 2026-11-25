---
inventory-delta:
  tests/: +2
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
