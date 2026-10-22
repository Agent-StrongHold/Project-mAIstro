---
inventory-delta:
  packages/maistro-evolve/tests: +13
---
# Issue #852 mutation killers for the benchmark verdict path

Adds `packages/maistro-evolve/tests/benchmarks/test_verdict_mutation_killers.py`
(13 tests) pinning the #852 verdict-integrity invariants at the mutation level:
each test asserts the production function's honest outcome first (so any
mutation of the production verdict path that flips that outcome fails the
suite) and then demonstrates the named mutant is distinguishable from it.

Mutants killed, per #852 acceptance:

- **always-pass / ignored-assertion / spoofed-marker** on
  `sandbox_exec._grade_case` — wrong results, dropped comparisons, and
  candidate-printed `PASS` all stay failures; plus an end-to-end
  `run_swebench` run proving the score at the benchmark boundary tracks the
  real grader (always-pass mutant ⇒ 1.0 vs honest 0.0).
- **inverted predicate / permissive unknown rule** on IFEval
  `_evaluate_rule` — unknown rule types contribute 0.0, not 0.5.
- **positive floor / substring word-match** on `scoring.judge_score` —
  malformed output 0.0 (the historical 0.3 floor exactly met GAIA's 0.30
  hard gate), `incorrect` 0.0.
- **empty-body candidate vs hard gate** end-to-end: a genome whose judge
  answers garbage scores below the `proxy_gaia` 0.30 gate and is rejected by
  `fitness._check_hard_gate`; under the historical floor it passed exactly.
- **prose-mention** on `tau_bench._score_tool_usage` — negation prose is
  0.0, a mention-matching mutant is 1.0.
- **metadata leak** — IFEval redacted rule descriptions and SWE-bench
  failure metadata are asserted free of hidden expected values/rubric text.

Net collected node-ID delta: **+13** (new file, no parametrization).
