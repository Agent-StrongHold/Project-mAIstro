---
inventory-delta:
  tests/: +19
---
# Issue 1136: Literal discovery review regressions

Nineteen new collected cases in
`tests/test_check_execution_lifecycle_review.py` cover distinct class/function
alias identities, nested class fields, lexical helper isolation, supported
Optional/Union/Annotated wrappers and import aliases, metadata exclusion,
named-alias reuse versus extension, cycle termination, new-sibling rejection,
and trusted-base source lookup for ordinary and prefixed flat-app module names.

The three revision-lookup cases create real temporary Git history and verify
that candidate-only aliases are not mistaken for trusted-base evidence.
The existing +15 note remains accurate; no existing tests are removed.

Local validation of the retrieved source subset: 46 passed, 2 repository-census
tests deselected because a full checkout was unavailable. Those two tests remain
unchanged and enabled in repository CI. Running the new regression module
against the verified previous scanner produced 15 failures and 4 passes.
Fresh exact-head repository CI is required before merge.
