<!-- Keep it short. The diff explains the what; this explains the why. -->


## Closure

- [ ] This PR closes issue(s): `Closes #N` — one per issue, verified the number is an ISSUE not a PR (missing closure keywords force manual closes with receipts; 4+ occurrences this week)

## Why

## Checks

- [ ] Base branch is `main` (this repository runs single-trunk; [`ADR-095`](../docs/adr/ADR-095-four-tier-branch-model.md)'s four-tier model applies in the development repository)
- [ ] Tests at the right layer per [`ADR-032`](../docs/adr/ADR-032-contracts-as-acceptance-criteria.md); CI green
- [ ] ADR/spec added or status corrected if this changes a decision or contradicts a doc claim
- [ ] This change does not create a new universal execution/scope/event/effect/approval/recovery owner or an incompatible cross-product shared type. Product-local projections of canonical concepts declare `M1 product-local projection: <Concept>` on the owning class.

<!-- Required only when the PR carries the m1-convergence-exception label:
Architecture rationale:
Canonical owner:
Disposition owner:
Retirement/convergence path:
-->
