---
inventory-delta:
  tests/: +11
---
# claude-issue-653-adr-anchors-resolve-1202

All 11 are added; nothing was removed or merged, so the net is the gross.

`tests/test_ac_state_anchor_resolution.py` gains two classes for #653, which
widens the `ac-modules` anchor gate from specs to ADRs as well.

**`TestBothDocumentKindsAreWalked` (7)** — the new behaviour. An ADR anchor
naming no module is reported; the report labels the kind alongside the file,
criterion and string; a spec finding is still labelled `spec`; the report
refuses to be called for specs alone; an unresolvable ADR anchor fails through
`main` rather than through a helper `main` might not reach; the corpus's 279
ADR anchors all resolve; and a guard asserts the ADR corpus actually carries
anchors, because `_criteria_of` returns `[]` for a document whose key the walk
does not read — a wrong walk would report nothing and read as clean.

**`TestWideningChangedNothingForSpecs` (4)** — AC-6, the half that makes this a
widening rather than a change. A clean ADR corpus does not mask a spec finding
and a clean spec corpus does not mask an ADR one (a report that concatenated
wrongly would drop one direction); an unannotated ADR criterion is not
reported; and a module that is real but baselined unreachable stays out of this
gate on the ADR side too, which is #631's two-failures-stay-apart rule.

Two existing assertions in `TestTheReportAndItsCallSite` changed to pass `[]`
for the ADRs, because `_report_unresolvable_anchors` no longer defaults that
parameter. They test the same thing; the signature moved under them.

Mutation-checked. Reverting the ADR walk kills 4; reading `criteria` instead of
going through `_criteria_of` kills 4; putting one of the 49 corrected anchors
back kills the corpus test by name.
