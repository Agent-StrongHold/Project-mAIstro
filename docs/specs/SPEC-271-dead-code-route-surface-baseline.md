---
id: SPEC-271
title: "Dead-code scanner baseline and route/model surface classification"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-06-28
substrate:
  - maistro-engine#SPEC-205
related:
  - maistro-engine#SPEC-264
implements: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-271: Dead-Code Route Surface Baseline

## Finding addressed

The third-pass vulture run mixed a true unreachable-code finding in `packages/hive-conductor/backend/routes/dags.py` with expected framework false positives from FastAPI route handlers, Pydantic fields, and dynamic integration surfaces. The unreachable-code finding has been removed, and the vulture baseline now classifies remaining findings by reviewed category while failing on new unreachable code or unclassified findings.

## Design

1. Keep the DAG route failed-response regression test as the guard for the removed unreachable branch.
2. Create a vulture baseline with category rules that include owner and rationale, and report every scanned symbol count under exactly one matched category.
3. Classify findings as one of: framework decorator surface, declarative model field, public extension point, dynamic import surface, planned implementation, or remove/fix.
4. Make new 100%-confidence unreachable-code findings fail CI after the baseline lands.
5. Keep security findings out of this baseline; security remains a separate review.

## Acceptance criteria

- [x] The unreachable duplicate code in the DAG route is removed.
- [x] The DAG route has a regression test for the failed completion response.
- [x] Vulture baseline entries include category, owner, and rationale.
- [x] Route handlers and Pydantic fields are allowlisted only by category, not by broad file suppression.
- [x] New high-confidence unreachable code fails CI.
- [x] The scanner reports zero unclassified or never-allowlisted findings.
