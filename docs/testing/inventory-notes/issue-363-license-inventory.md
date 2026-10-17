---
inventory-delta:
  tests/test_check_license_inventory.py: +9
---
# Issue 363 license inventory

`scripts/check-license-inventory.py` builds the license inventory from
final-artifact CycloneDX SBOMs. The test suite covers component/evidence
identity reconciliation, unknown metadata, reviewed resolutions, copyleft
classification and legal policy, missing required surfaces, and malformed SBOM
identities.

## Delta 2 (develop sync + real-image execution round)

Two new tests for resolution specificity:

- `test_more_specific_resolution_overrides_class_wildcard` — a targeted
  copyleft record (`pkg:pypi/example@1.0`, MPL-2.0) overrides a class-level
  `pkg:pypi/example@*` NOASSERTION so copyleft stays visible. This is the
  semantics the real policy relies on: `pkg:cargo/zbus@*`-style MPL-2.0
  entries sit on top of the `pkg:cargo/*` class record for the uv binary's
  embedded crate tree.
- `test_equally_specific_resolutions_remain_ambiguous` — overlapping patterns
  of equal specificity still fail (ambiguous resolution).

Evidence added this round (not tests, but the reason the semantics exist):

- All four final images (`maistro-engine`, `hive-conductor`,
  `maistro-engine-research`, `maistro-rsi-runner`) were built from this tree
  with Docker, scanned with the pinned syft 1.49.0 (sha256 verified), and the
  gate reconciled 26,706 components with 433 copyleft findings surfaced for
  legal review (including pylint's `astroid` LGPL-2.1 in `maistro-rsi-runner`
  — the exact GPL-tooling case the issue opened with).
- `deploy/sbx/build.sh` was exercised end-to-end as an operator would run it:
  both sandbox images built, scanned with the pinned syft, gate reconciled
  61,517 components with 325 copyleft findings, scan ran before any optional
  push.
- `quality/license-policy.json` gained reviewed resolutions grounded in the
  installed wheels' METADATA classifiers, upstream PyPI metadata, and the
  pinned-binary provenance of embedded crate/module trees.
