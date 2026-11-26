---
inventory-delta:
  tests/: +1
  packages/maistro-core/tests: +0
  packages/hive-conductor/backend/tests: +0
---

# DevSkim scan-scope sweep parses its configuration once per process (#2304 CI repair)

The Coverage gate's `combine` producer (quality job 121855755737 on this branch,
job 128649305503 on the develop tip — same files byte-for-byte) timed out in
`tests/test_devskim_scan_scope.py::test_no_shipped_source_file_is_excluded_from_the_scan`:
the sweep asks `_is_scanned` once per shipped source file (~1.6k on this tree),
and the glob getters re-read and re-parsed `.github/workflows/devskim.yml` on
every call (~3.3k YAML parses, 7.5s of a 9.4s local test), crossing the 30s
`pytest-timeout` budget on CI's 2-core runners under coverage tracing. The
getters are now `lru_cache`d (assertions unchanged), and a structural regression
test pins the parse-once contract without any wall-clock bound: with the caching
stripped, the new test fails (no `cache_clear`, parse count asserted at 1 per
getter). `tests/` therefore collects one more test; no other suite moved.
