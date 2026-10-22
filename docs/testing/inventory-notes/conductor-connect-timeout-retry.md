---
inventory-delta:
  packages/maistro-core/tests: +1
---
# conductor-connect-timeout-retry

+1 test in `packages/maistro-core/tests/agents/test_conductor.py`:
`TestIsRetryable::test_connect_timeout_is_retryable`. httpx 0.28.x
`ConnectTimeout` is not a `TimeoutError` subclass, and `_is_retryable()`
only retried `ConnectError` — connect timeouts aborted conductor calls
instead of retrying. The new test pins the widened retryable tuple; no
tests were removed or renamed.
