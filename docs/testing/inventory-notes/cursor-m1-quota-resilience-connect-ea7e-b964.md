---
inventory-delta:
  packages/maistro-core/tests: +12
---
# cursor-m1-quota-resilience-connect-ea7e-b964

Diff-coverage and CONNECT closers for #2318 / PR #2330.

- `+1` earlier: `test_record_runs_maybe_reconcile_when_verifier_installed` on the
  Invocation recorder path.
- `+2`: `default_invocation_quota_verifier` idle-without-key / OpenRouter-when-
  keyed (covers the `OPENROUTER_API_KEY` branch at recorder.py:70).
- `+1`: NodeRun stage-delay floor when READ `get_delay` exceeds classifier
  backoff (graph/node.py:533).
- `+8`: gateway resilience helpers — max_tokens cap/omit, 429 coordinator
  record/raise, context-probe overflow/success-clear, adapter non-object
  normalize reject (`test_llm_gateway_resilience_connect.py`).
