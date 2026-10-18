---
inventory-delta:
  tests/: +243
---
# Independently retryable Quality and SAST checks (#1357)

This recovers the CI split from current develop without importing the historical
PR's unrelated runtime, migration or test reversions. The original PR remains a
history record. The change creates 37 Quality leaf jobs and three SAST scanner
jobs, with the existing required check names retained as fail-closed summaries.
No required context, live ruleset, permission, trigger or ratchet floor changes.

Collected root tests increase from 5,210 on develop
`6c739f054f99db5547c1e12d96ea6c6467232a7d` to 5,453:

- 96 Quality contract cases preserve the exact baseline validation step content,
  trusted-base selection, proof profiles and explicit summary dependencies.
- 66 SAST cases preserve scanner versions, scopes, severities, history ranges,
  independent execution and actual summary refusal for unsuccessful evidence.
- Eight added Ruff mutations protect the required-summary dependency while all
  96 prior ownership/event-profile cases remain.
- 72 existing parametrized ratchet-base cases now exercise the new Quality jobs.
- One existing PostgreSQL health-check case covers the separate Hypothesis
  service.

No test is removed. The existing Pyright workflow assertion follows its moved
job. The Quality and SAST preservation checks both reject the pre-split baseline;
mutation tests also reject missing commands, weaker conditions, detached
dependencies and absent service/migration prerequisites. The summary helper's
focused coverage is 95% (the CLI entry line is additionally exercised in separate
processes).

Both service-backed leaves retain a migrated PostgreSQL 18 database. The
acceptance leaf retains age and age-keygen; the full Quality formal suite retains
its original timeout and environment. The three coverage producers and combined
verdict are unchanged. The only removed validation is an identical second
credential-authority invocation. Existing Ruff/Pyright deduplication is retained;
distinct mypy, formal and dependency-audit profiles remain separate. Coverage
collector and Vulture ownership changes belong to their existing work.

Independent review compared the preservation manifest against the actual
baseline, checked every moved command, and confirmed merge-group discovery sees
all 40 leaves and both required summaries. This establishes the definitions and
aggregation behavior; exact-head GitHub Actions still needs to verify execution
on runners. Each independent job repeats setup, so no overall cost or elapsed-time
improvement is claimed.

## Refresh after analyzer provenance (#2142)

The proposal is refreshed onto develop
`c0839cae7b96f1e9192650030bc0831268ec0e80`. All 35 files from the analyzer-version
change are retained byte-for-byte, including its required implementation identity,
failure cases and 28 added tests. No workflow command or summary dependency needed
to change. Root collection is now 5,481, preserving this proposal's independent
delta of +243. The already-landed authorization ledger is unchanged.

The publication refresh onto `c2a22e55db71efa7f75a4e2f07dd063d34ae7eb2` also
preserves #2146's required `cross-product-parity` context, its dispatch-only
strict workflow and its complete test contracts. Generated check documents
retain that new gate: 74 PR-visible checks, 19 required on develop and 31 on
main. The root inventory is 5,484; this proposal's +243 delta is unchanged.
