---
inventory-delta:
  tests/: +54
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

## Delta 3 (repair round: gate-exercised refusals and CLI contract)

45 tests added so every refusal path of the gate is exercised, not just the
happy path — the diff-coverage floor found the first version covered only the
accepting arcs (77.9% of changed lines against a 90% floor). The added tests
drive, through the public `build_inventory`/`main` entry points:

- every distinct `InventoryError` refusal in policy validation (surface
  list/id/duplication/descriptor/class/source, dependency-class shape and
  fields, coverage scope, frontend `asset_evidence`, all three `legal`
  section refusals);
- SBOM input refusals (non-CycloneDX, non-list `components`, missing file,
  duplicate bom-ref, identity without bom-ref, surface without policy), plus
  the accepting `components: null` bundle case (Syft's output for a directory
  of unrecognised files — the scan still counts as evidence) and the
  file-component → `not-applicable` provenance path;
- license-evidence extraction forms (expression, value, component-level
  `licenseExpression`, non-dict entries skipped, name@version / name-only
  identity fallbacks) and resolution edge semantics (non-dict entries
  skipped, missing required field, reviewed-on-already-licensed);
- the CLI contract (success writes the inventory and returns 0, unresolved
  licenses fail with the reviewed-resolution message, unreadable/malformed/
  non-object/absent policy, malformed `--sbom`/`--artifact` pairs, unknown
  `--only` surface, `--only` filtering, non-list `reviewed_resolutions`);
- `test_repository_license_policy_validates` pins the committed
  `quality/license-policy.json` against the gate's own schema so a policy
  edit that breaks the inventory gate is a legal-review regression rather
  than a silent pass.

The delta above is the file's total against the develop baseline (the suite
is new on this branch). Coverage of `scripts/check-license-inventory.py`
measured with the CI `--source=scripts` producer: 99% lines, 99% branches;
the only uncovered statement is the `if __name__ == "__main__"` guard.

## Repair-round verification evidence (non-test)

Reproduced locally against the four real `pr-363` images built from this
tree (prior lane round):

- The license-inventory step of `security.yml`'s "Container scan + SBOM +
  cosign" job passes end-to-end: both frontends built (`npm run build`),
  syft 1.49.0 scanned the four images plus the conductor's installed
  `dist/` (via `docker cp` from the final image) and both npm trees, and the
  gate reported `OK: inventoried 8 surface(s), 26706 component(s);
  copyleft=433 (policy=review)`.
- That job's failure on CI is NOT the license step. Trivy v0.73.0 (the job's
  pinned version) reproduced failing on all four images with pre-existing
  HIGH/CRITICAL findings this branch's changes cannot have introduced (it
  touches no Dockerfile, lockfile, or dependency): perl-base ×3 CRITICAL +
  ×4 HIGH and libpcre2 (hive-conductor, debian 12.15), anyio CRITICAL and
  pypdf ×8 HIGH (engine-research), urllib3 ×2 HIGH and docker-CLI Go-stdlib
  ×3 HIGH (engine/research), openssl ×3 HIGH and libpcre2 (rsi-runner, debian
  13.7), and `usr/bin/age`/`age-keygen` Go-stdlib ×3 HIGH each (built with
  the digest-pinned `golang:1.25.13-alpine` stage in
  `packages/hive-conductor/Dockerfile`).
- Two contributing findings about the job's ignore file, recorded for the
  supply-chain owner (no gate changed here): `.trivyignore.yaml`'s two
  purl-scoped suppressions carry `expired_at: 2026-09-30`, already past, and
  trivy silently drops expired entries — re-testing with a future
  `expired_at` suppresses the msgpack/setuptools findings exactly as the
  entries' statements intend. The remaining findings are unsuppressed debt
  needing a reviewed fix (Go toolchain bump for the age stage, base-image /
  lockfile refreshes) or reviewed suppressions; per
  `.github/branch-protection.json` this check is `base_coupled_to: [main]`
  and is not in develop's required set, so it does not block this branch.
- The other CI legs on this head were reproduced and fixed from evidence:
  `workflow-lint` (actionlint/shellcheck SC2086 on the new `--artifact`
  lines in release.yml/security.yml — now quoted), the `test` job
  (`quality/license-policy.json` was unclassified in
  `quality/branch-independence.json` — now a `specification` surface), and
  the Coverage gate (77.9% → 99%, see Delta 3 above).
