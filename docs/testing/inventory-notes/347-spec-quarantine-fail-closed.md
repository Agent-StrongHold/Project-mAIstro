---
inventory-delta:
  packages/maistro-rsi/tests: +5
---

# 347 reconcile the RSI specification with fail-closed quarantine behavior

Five new tests, one new file — all documentation-conformance additions, no
behavioral changes and no removals/renames:

- `test_spec_conformance.py` (+5, new): pins SPEC.md §3's selfbranch-5 wording
  to the production gate's semantics. No sentence in the spec may offer an
  absent/missing-check escape hatch (the "absent **or** cleared" connective
  that production code never had); the selfbranch-5 row must conjoin presence,
  execution against the diff that ships, and a cleared verdict, enumerate
  absence among the refusals, and supersede the fail-open wording with
  rationale; and the code side must keep the exact fail-closed conjunction
  (`quarantine_verdict is not None and quarantine_verdict.cleared`) with no
  `is None or` disjunction. The assertions check the gate's *meaning* — what
  it conjoins and denies — not keyword presence, so reverting either the spec
  connective or the code conjunction fails the suite.

Behavior for the non-present evidence states (missing check, uncleared
verdict, cleared verdict) was already proven in `test_selfbranch.py`
(`test_no_quarantine_check_means_no_pr`,
`test_pr_blocked_when_quarantine_check_does_not_clear`,
`test_pr_opened_when_quarantine_check_clears`), so this change adds zero
behavioral tests and touches no production code.
