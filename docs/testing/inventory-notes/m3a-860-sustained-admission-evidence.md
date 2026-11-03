---
inventory-delta:
  tests/: +9
---

# #860 — sustained admission cannot pass without admitted work

Nine HTTP-worker/accounting/evaluator cases cover empty traffic, all-backpressure,
missing/blank Retry-After, accepted-plus-retryable traffic, server errors, and
kill-window isolation of accepted work and retryable rejections. They feed
MockTransport responses through `one_request_with`, `LoadStats.snapshot`, and the
same admission check used by `main_async`, then check the promotion evaluator.
These are evidence-accounting tests, not a real production soak or physical-work
recovery proof. No canonical execution or rate-limit authority changes.
