---
inventory-delta:
  packages/maistro-evolve/tests: +69
---
# Issue #852 structured-only tool-use scoring (tau-bench, BFCL)

`benchmarks/tau_bench.py` and `benchmarks/bfcl.py` now score structured,
observed calls only:

- tau-bench `_extract_tool_calls_from_response` keeps only JSON call objects
  (`name`/`function`/`action`); the prose regexes ("call X", "invoke X",
  `tool_call: X`) are removed. `_score_tool_usage` computes recall/precision
  over that structured set only; the `mentioned_tools` substring path — which
  scored "I cannot invoke refund_order" identically to an invocation — is
  gone. `_simulate_turns` no longer fabricates "Success" tool results for
  prose mentions.
- BFCL `_extract_tool_call` is JSON-only (the `call name(args...)` prose
  parser is removed); the 0.25 prose-name fallback is removed; a missing
  parameter scores 0.0 (the 0.5 response-text-substring fallback is removed);
  non-numeric observed values earn 0.0 (the substring-coincidence branch is
  removed). A response with no structured call can no longer reach BFCL's
  0.20 hard gate.

Test deltas: `tests/benchmarks/test_bfcl.py` and
`tests/benchmarks/test_tau_bench.py` rewritten to the structured contract
(+69 tests across both), each including the adversarial cases that used to
score: negation prose, name concatenation in prose, prose call syntax, and
prose-only conversations asserting an exact 0.0 benchmark score. Structural
positives (JSON objects/lists, key fallbacks, precision clamping, turn
simulation with real structured calls) keep equivalent coverage to before;
no test was deleted without a structured replacement.
