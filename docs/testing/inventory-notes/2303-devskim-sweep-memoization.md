# DevSkim scope sweep memoization (#2303 CI repair)

No suite-count delta: every test keeps its name and its assertions; only the
helpers' redundant recomputation was removed. No `inventory-delta` block is
recorded because no count moved.

## What changed and why

`tests/test_devskim_scan_scope.py::test_no_shipped_source_file_is_excluded_from_the_scan`
timed out at the coverage gate's 30s per-test cap on the #2303 merge-queue
evaluation (CI run job 133033373463, 2026-11-16): the worker was sampled inside
`yaml` compose recursion. The test's assertions were never the problem — the
sweep evaluates `_is_scanned` against all 1,646 shipped source paths, and every
call re-read and re-parsed `.github/workflows/devskim.yml` twice (once per glob
list, `_scanner_step()` per `_ignore_globs()` and `_include_globs()`) plus
recompiled every glob regex per path: ~3,300 redundant YAML parses per sweep,
measured at 8.5s of the file's 8.9s local runtime. Under a loaded runner that
crosses the cap; the file passed all along (excluded=0 on every run, including
the timed-out one, which had produced no assertion failure).

The fix is memoization only: `functools.cache` on the four constant helpers
(`_scanner_step`, `_ignore_globs`, `_include_globs`, `_as_regex`). The swept
tree walk and every assertion are byte-identical.

## Measured effect

- File suite: 21 passed, 8.88s → 3.24s locally.
- The sweep test alone: 8.5s → 0.16s call time, restoring real headroom under
  the 30s cap (a 100x-slower environment still fits).
- Full root suite re-run at this head: `tests/` 5,910 passed / 139 skipped;
  `packages/maistro-core/tests` 17,196 passed / 1,232 skipped / 7 xfailed.

The pip-audit-advisory refresh carried by the same PR is recorded in
CHANGELOG's `Dependencies` section, not here — it moves no test either.
