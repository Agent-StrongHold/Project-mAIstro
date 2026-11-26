---
inventory-delta:
  packages/maistro-core/tests: +0
---
# 972-extension-quarantine-authority

> **Superseded by the develop-sync merge**: develop landed this feature in the
> M9-G EPIC commit `f0fb5c83db86` ("[EPIC M9-G] Enforce extension isolation,
> permissions, tenancy, and policy governance (#2226)"), which is an ancestor
> of `origin/develop`. The merge of that commit into `auto-972` replaced the
> branch's independent `ExtensionQuarantineAuthority` implementation
> (`packages/maistro-core/src/maistro/extensions/quarantine.py`), its
> `Container.ensure_extension_quarantine_authority` wiring, and its
> acceptance suite (`packages/maistro-core/tests/extensions/
> test_quarantine_authority.py`) with develop's canonical
> `maistro.extensions.quarantine` engine (`ExtensionGovernanceService` and the
> `SandboxViolationBridge`) and develop's own suite. Develop's coverage is
> recorded in `972-extension-quarantine.md`; the removal is recorded in
> `auto-972-develop-sync-resolution.md`.

Original note (the branch's independent implementation, now removed):

Lands the M9-G4 quarantine/health-response authority (`ExtensionQuarantineAuthority`)
— canonical security/health evidence with threshold-driven quarantine or
version disable, the extension structurally unable to write or clear its own
state, in-flight work dispositioned by policy, and an append-only evidence
ledger that re-enable never erases. Forty-three node IDs in
`packages/maistro-core/tests/extensions/test_quarantine_authority.py`, mapped
one test class per issue #972 acceptance criterion
(`TestQuarantineBlocksNewInvocations`, `TestExtensionCannotWriteOrClearItsOwnState`,
`TestThresholdsAndStateDistinction`, `TestInFlightDisposition`,
`TestReenableAndEvidenceRetention`, `TestRaceQuarantineVersusInvocation`,
`TestContainerWiring`, `TestCanonicalVocabulary`,
`TestSuspensionRecordsKeptAfterLift`).

## Why the develop-sync merge adopts develop's engine

Both sides implemented the same issue #972 feature independently: the branch's
`ExtensionQuarantineAuthority` (1063 lines, container-wired) and develop's
`ExtensionGovernanceService` + `SandboxViolationBridge` (canonical engine, not
container-wired). Keeping both would put two competing suspension authorities
in the tree — two paths that can refuse or lift a quarantine — which the
repo's single-authority rule forbids. The resolution follows the established
develop-sync pattern (`971-extension-policy-governance.md`,
`944-develop-sync-merge-resolution.md`): when develop has landed the feature,
the branch's duplicate is superseded by develop's canonical implementation and
the branch's own test module is removed.

## Inventory consequence

The branch's suite contributed +43 node IDs to `packages/maistro-core/tests`.
It is gone in the merged tree, so this note's `inventory-delta` is **+0**
(the original +43 was zeroed by `check-suite-inventory.py --update`). Develop's
suite is accounted for by `972-extension-quarantine.md`. Canonical collection
after the sync returns 17104 node IDs for `packages/maistro-core/tests`, and
`check-suite-inventory.py` exits 0 across all 21 suites.
