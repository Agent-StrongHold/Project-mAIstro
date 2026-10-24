---
inventory-delta:
  packages/maistro-core/tests: +2
---
# auto-972-quarantine-effective-state

Two node IDs added to `packages/maistro-core/tests/extensions/test_extension_quarantine.py`
(`test_version_re_enable_reports_the_effective_governing_state`,
`test_version_disable_under_a_quarantined_package_reports_the_effective_state`).

## What moved

The M9-G4 governance engine (`packages/maistro-core/src/maistro/extensions/quarantine.py`)
audits the state an identity *actually* has in `GovernanceEvent.state_after` /
`GovernanceDecision.state_after`. Develop's own EPIC commit established that
invariant for `re_enable_package` ("lifting a package quarantine while its
publisher stays quarantined must audit `state_after=QUARANTINED` … the audit row
previously claimed a state the identity did not have"), and the below-threshold
`record()` path already reports the effective state through `_governing`.

The two version-scoped actions still hardcoded their own layer:
`re_enable_version` reported `ACTIVE` and `disable_version` reported `DISABLED`,
even when a package or publisher quarantine still governed the identity. The
audit row then claimed a state the identity did not have — the same defect
develop fixed for the package path, one layer over. Admission was already
refused in both cases (the broader scope wins in `_governing`), so only the
recorded state was untruthful.

Both methods now derive `state_after` from the same `_governing` authority that
admission and in-flight disposition use, so the ledger, the decision and the
admission gate cannot disagree about whether an identity is active.

## Evidence

Both new tests fail against the pre-fix code and pass after it:

- `re_enable_version` under a package quarantine: pre-fix
  `state_after=GovernanceState.ACTIVE` (and `decision.suspended` false) while
  `admit()` refuses with `governing_state=quarantined`; post-fix
  `state_after=QUARANTINED`, `suspended` true, admission still refused, and the
  `version_re_enabled` ledger row records `QUARANTINED`.
- `disable_version` of a sibling version under a package quarantine: pre-fix
  `state_after=GovernanceState.DISABLED` while the identity's governing state
  was `QUARANTINED`; post-fix `state_after=QUARANTINED`.

`uv run pytest packages/maistro-core/tests/extensions/test_extension_quarantine.py -q`
→ 38 passed. `uv run python scripts/check-suite-inventory.py` → 21/21 suites
match (this note's `+2` is the only delta this round records).
