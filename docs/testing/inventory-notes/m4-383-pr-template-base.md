---
inventory-delta:
  tests/: +13
---
# m4-383 — PR template requires the canonical develop base

#383 made the PR template name `develop` as the normal base (it told every
author to target `main`, contradicting CONTRIBUTING, ADR-095 and the actual
branch flow) and gave CI a branch-policy job: `scripts/check-pr-base.py` runs
on every pull_request — develop passes, main passes only with the `release`
label (the authorized promotion), topic branches pass as stacked bases,
everything else fails with the correction.

The +13 node IDs are all in `tests/test_check_pr_base.py` (new):

- Template: names `develop` as the base (and not `main`), documents the
  release-labelled promotion exception, states stacked-PR retargeting, and
  points at ADR-095 (4 tests).
- Gate: develop clean; main without the label fails with the correction;
  main with the label passes; stacked topic bases pass; the retired
  `integration`, the undocumented `feature/*` spelling, and bare names all
  fail; topic prefixes are read from the policy file, not a copy; the
  workflow's argument shape works end to end (9 tests).
