---
inventory-delta:
  packages/maistro-core/tests: +5
  packages/hive-conductor/backend/tests: +1
---
# Issue #358 — indexed ephemeral core audit pages

Add two corpus-size cases (100 and 10,000 entries) exercising all optional
user/boundary/denied filter shapes, initial and deep tied-timestamp cursors,
empty scope, exact row identities, and continuation presence. A record-access
budget fails reads that inspect more than `limit + 1` records; it measures work,
not runner speed. The expected answer is computed independently before the
production query. The pre-repair scan must fail this test.

Add one out-of-order append / concurrent insertion test proving that index
maintenance preserves cursor boundaries, filter isolation, and older arrivals.
Existing adapter tests retain max limits, malformed cursors, empty pages,
concurrent newer inserts, and organization isolation.

Add mixed sync-thread/async writer coverage for unique row identities and a
complete cursor walk. Add a real authenticated HTTP convergence test that writes
through Hive's synchronous bridge and async core log, then reads paginated rows
and scoped export. This test caught the bridge's direct `_entries.append` bypass
before it was routed through the shared, lock-protected append seam.

Add explicit scope-conformance coverage for `log_sync`: a second caller's append
with the same request ID cannot mutate the original row or cross org scope.
Register only that ephemeral append API in the public-method contract; all
unknown APIs and by-ID mutation remain rejected.
