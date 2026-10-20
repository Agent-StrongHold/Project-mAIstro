---
inventory-delta:
  packages/maistro-evolve/tests: +4
---

# 384-repair-responder-fallback-arcs

CI-repair round for #384: the diff-coverage gate measured the four responder
closures in `benchmarks/calibration.py` at 75% of changed branch arcs against
the 80% floor — the fallback reply each closure returns when a runner sends a
message matching no fixture query was never executed (`calibration.py:164`,
`:190`, `:208`, `:226`).

## What changed

`TestResponderFallbacksAreTotal` in
`packages/maistro-evolve/tests/benchmarks/test_adversarial_calibration.py`:
one parametrized case per scorer. It wraps the real runner (`run_bfcl`,
`run_tau_bench`, `run_gaia`, `run_ragas`) so the candidate's `llm_call` sees
every known fixture query scrubbed from the outgoing user turns, then asserts
the closure's safe default reply actually came back (`"I am not sure…"`,
`"I cannot proceed."`) and the calibration report still completes. The
scrubbing exercises the closures' real matching logic — no runner internals
are guessed at.

No production code changed in this round for these arcs; the tests only
execute what was already there.
