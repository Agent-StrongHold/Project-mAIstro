---
inventory-delta:
  packages/maistro-rsi/tests: +0
---
# 880 M8-A: execution Hypothesis state machine leaf #881

This change adds the execution Hypothesis state machine for leaf #881 of epic #880.
It includes:

1. A new formal model: `formal/models/test_execution_lifecycle.py` that defines a
   Hypothesis state machine for the Run lifecycle transitions.

2. An update to the research note: `docs/research/880-advanced-verification-assurance.md`
   to document the experiment conducted for leaf #881, including the evidence and
   a disposition of WATCH.

3. An update to the assurance matrix harness: `packages/maistro-rsi/tests/test_m8a_assurance_baseline_research.py`
   to add a technique row for leaf #881 and to update the test
   `test_ranking_is_deterministic_across_repeated_calls` to use the ALL_CANDIDATES
   constant (which includes the technique row) for deterministic ranking checks.

The change does not add new test cases (node IDs) to the test suite, hence the
inventory-delta of 0 for the test file. The new model file is not a test file and
is not counted in the test inventory.
