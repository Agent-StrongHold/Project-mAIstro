# auto-80 round 6: coverage-gate timeout flake repair (devskim scan-scope sweep)

## What happened

`Coverage gate (publish-set floor + diff coverage)` failed at head
`654b773ced78` (quality.yml run 43812084099, job 133120551863, 2026-11-16):
`tests/test_devskim_scan_scope.py::test_no_shipped_source_file_is_excluded_from_the_scan`
died with `Failed: Timeout (>30.0s) from pytest-timeout` inside the combine
step's root-suite re-run (1 failed, 5931 passed). No coverage floor or diff
threshold moved; the three producer jobs succeeded.

## Why it is a latency flake, not a scope regression

The branch changes neither `tests/test_devskim_scan_scope.py` nor
`.github/workflows/devskim.yml` (both have an empty
`git diff origin/develop...HEAD`). The test's structural cost was the
problem: `_is_scanned` runs once per shipped source file and each call
re-read and re-parsed `devskim.yml` twice (~5k files → ~10k YAML parses).
Measured locally at the pre-repair tree: 7.29s for the sweep test alone; the
coverage-gate runner is a loaded 2-core machine that had just run several
suites serially, so the same work crossed the 30s pytest-timeout there.

## The repair

`_scanner_step`, `_ignore_globs`, `_include_globs` are now memoized with
`functools.lru_cache(maxsize=1)` (returns tuples). The workflow is a module
constant within a pytest process, so the cache cannot stale. Every assertion
is unchanged; the sweep dropped to 0.18s locally (~40x), and the whole file
still reports 21 tests.

inventory-delta:
  tests: +0
