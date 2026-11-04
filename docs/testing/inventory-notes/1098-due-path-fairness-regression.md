---
inventory-delta:
  packages/maistro-core/tests: +1
---

# Due-path recovery fairness regression (#1098)

Adds one regression to
`packages/maistro-core/tests/graph/durable_runs/test_recovery_wakeup.py`:
`test_wakeup_crosses_an_interleaved_foreign_prefix_longer_than_one_ticks_bound`.
It closes the due-path half of #1098's acceptance: ownership classes are
interleaved (foreign/owned) and then a run of foreign-owned due continuations
longer than one tick's inspection ceiling (`DEFAULT_MAX_INSPECTED`) sits ahead
of the last owned one. With a per-seam `ScanContinuation` and `limit=1`, the
test proves each interleaved owned continuation is reached by walking past the
foreign row ahead of it (per-row cursor advancement), the long foreign prefix
is crossed across bounded ticks without resetting to the top, the owned
continuation behind it is resumed, and no foreign continuation is ever
attempted. Under the pre-fix shape (one globally bounded `list_due` page with
ownership filtered in memory) this test fails, which the due path previously
had no coverage for at all.
