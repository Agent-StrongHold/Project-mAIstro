---
inventory-delta:
  packages/maistro-core/tests: +0
---

Delta note: `+0` — the repair rewrites the body of
`test_empty_registry_exposes_only_uptime` in
`packages/maistro-core/tests/test_metrics.py` (1 test modified, 0 added or
removed), so the collected node-ID count for the suite is unchanged. The
detailed behavior record follows.

# test_metrics teardown robustness (auto-1195 merge validation)

While validating the #1195 develop reconciliation (`6f460442`), the full
`packages/maistro-core` battery surfaced a deterministic teardown error:

```
ERROR at teardown of test_empty_registry_exposes_only_uptime
StopIteration: lambda: next(monotonic_values)
```

`maistro.observability.metrics` imports the global `time` module, so patching
`metrics_module.time.monotonic` patches it for the whole process. The test
scripted exactly two reads (registry creation, `render_prometheus`), but pytest
also times teardown steps after the body finishes; that extra read exhausted
the iterator. The failure reproduced identically at the pre-merge head and on
develop (file unchanged there), so it is environmental test-infra breakage,
not an #1195 behavior change.

## Change

`lambda: next(monotonic_values)` becomes `lambda: next(monotonic_values, 12.34)`:
any harness-initiated read after the scripted pair returns the final scripted
timestamp. The assertion still only depends on the two scripted values
(12.34 - 10.0 = 2.3 s uptime).

## Validation

- `uv run pytest packages/maistro-core/tests/test_metrics.py -q` -> 28 passed,
  0 errors (previously 28 passed, 1 teardown error).
