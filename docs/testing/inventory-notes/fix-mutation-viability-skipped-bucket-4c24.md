---
inventory-delta:
  tests/: +7
---
# fix-mutation-viability-skipped-bucket-4c24

All seven node IDs are additions to `tests/test_mutation_viability.py`; no
test was removed, renamed or reparameterised, so the net and the gross are
the same number.

**`TestSkippedBucket` (+4).** `mutation_filter_annotations.py` marks
annotation-position mutants `SKIPPED` before `exec`, having proved by AST
span what `mutation_viability.py` otherwise proves by AST comparison. Such a
mutant never ran, so it has no diff to reconstruct, and it used to fall
through to `undetermined` — which keeps it in the denominator. A file was
therefore penalised precisely for having had its unkillable mutants
correctly filtered: `security/task_policy.py` scored 110/209 = 52.6% where
the mutants that actually executed were 110/110. Three of these four fail
against the pre-fix module; the fourth pins the measured `task_policy`
shape itself.

**`TestSkippedInTheHumanReport` (+3).** The `_emit` summary is where most
readers meet the raw-versus-adjusted split, and it was uncovered. Two of
these pin the branch that distinguishes correct behaviour from a bug — a
module *with* the future import has its skipped mutants subtracted, one
*without* does not and must say so rather than let the reader assume
otherwise. The third asserts the subtraction rule is printed unconditionally:
stating it only when something was skipped is how a reader comes to believe
`invalid` and `undetermined` are excluded too.

Diff coverage of `scripts/mutation_viability.py` was 81.8% of 22 changed
lines against a 90% floor, with 385 and 390–392 uncovered. Those are the
lines the second class exercises.
