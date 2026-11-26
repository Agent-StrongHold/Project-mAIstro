---
inventory-delta:
  tests/: +1
---
# cr2059-devskim-sweep-parse-cache

One added test in `tests/test_devskim_scan_scope.py`
(`test_the_sweep_does_not_reparse_the_workflow_per_source_file`); nothing was
removed or renamed. The sweep test itself is unchanged in what it asserts —
the same shipped-source walk, the same include/ignore classification, with a
byte-identical result set (1,647 sources, 0 excluded, verified against the
pre-change tree).

## Why

The coverage gate (publish-set floor + diff coverage) failed on PR #2059's
head (run 40400026640, job 121853711206) with
`tests/test_devskim_scan_scope.py::test_no_shipped_source_file_is_excluded_from_the_scan
- Failed: Timeout (>30.0s) from pytest-timeout` inside the root-suite
producer (`coverage run --source=scripts -m pytest tests/ --timeout=30`).
The sweep classified every shipped source by calling `_is_scanned`, which
re-read and re-parsed `devskim.yml` per file: 3,294 `yaml.safe_load` calls
for 1,647 files (measured). Locally that was 8.8s; on the hosted runner under
coverage it crossed the 30s per-test budget. A test whose runtime is one
YAML parse per shipped file encodes the machine's speed, exactly the kind of
bound this repo says not to assert.

## The change

`_scanner_step()` (workflow parse) and `_as_regex()` (glob compilation) are
now `lru_cache`d. Behavior-preserving: the parse is read-only and its result
is never mutated; regexes are compiled once per distinct glob.

## The new test

Pins the property structurally, not by wall-clock: across a full sweep it
counts `yaml.safe_load` calls and asserts ≤ 1. Against the old code the same
probe counts 3,294, so the test fails loudly if per-file parsing returns.
