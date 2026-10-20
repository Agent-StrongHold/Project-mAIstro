---
inventory-delta:
  tests/: +55
---
# Issue 363 license inventory

`scripts/check-license-inventory.py` builds the license inventory from
final-artifact CycloneDX SBOMs. The test suite covers component/evidence
identity reconciliation, unknown metadata, reviewed resolutions, copyleft
classification and legal policy, missing required surfaces, and malformed SBOM
identities.

The 55th root test (initially mis-recorded as +54, caught by the suite
inventory's DRIFT alarm after the develop sync) is
`tests/test_prepull_copy_sources.py::test_every_shipped_copy_from_source_is_covered_by_retry`
— part of this issue's copy-source coverage, counted here where it belongs.

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

## Delta 4 (CI-repair round: the container gate itself)

The merge queue blocks on "Container scan + SBOM + cosign", so this round
fixed the gate's actual failures on the four scanned images. Every finding
was reproduced locally first (trivy 0.73.0 + grype 0.116.0, the job's pinned
versions, fresh vuln DB) and every fix was proven by rebuilding the image and
re-scanning to exit 0:

- **Debian OS debt** (perl-base x3 CRITICAL + x4 HIGH, libpcre2 HIGH on the
  conductor's debian 12.15; libpcre2 + libssl3t64/openssl HIGHs on the
  rsi-runner's debian 13.7; libpcre2 on the engine): the pinned base digests
  froze at their 2026-09-30 build, before the fixed point releases. Fix:
  `apt-get upgrade` layers in the three runtime stages, matching
  Dockerfile.research's existing hardening policy. Research (13.7, already
  upgrading) needed nothing.
- **pip's vendored tree** (msgpack 1.1.2 GHSA-6v7p-g79w-8964, urllib3 2.7.0
  CVE-2026-97687/97689, setuptools 70.3.0 CVE-2025-47273 — reported with
  `FilePath: None` because trivy reads `pip/_vendor/vendor.txt`, not an
  install): present in both the venv's pip and the base interpreter's pip in
  engine/conductor/research. Fix: pip removed from the shipped runtime
  filesystems (venv + system site-packages + console scripts) — a build-time
  tool nothing in the shipped apps invokes. The two now-moot expired entries
  in `.trivyignore.yaml` were removed; the file keeps its shape with a
  `vulnerabilities: []` placeholder.
- **Go stdlib in shipped binaries** (age/age-keygen built on
  `golang:1.25.13-alpine`; docker CLI copied from `docker:29-cli`, embedded
  go1.26.8; CVE-2026-78667/78669/97031, fixed in go1.26.9/1.27.2): no
  released docker:xx-cli or age artifact ships a fixed toolchain (29.1/29.2
  ship older ones — checked). Fix: both binaries now built from their exact
  upstream release tags (age v1.3.1@b8564ad as before; docker/cli
  v29.9.1@dfc520d, verified by `git rev-parse` in-stage, vendor.mod→go.mod
  rename, `-tags grpcnotrace`) on the digest-pinned `golang:1.27.2-alpine` —
  the same patched-toolchain policy the agebuild stage already established.
  `quality/image-pins.json`: golang pin refreshed to 1.27.2 with the three
  consumers; the docker:29-cli pin row removed (nothing references it).
- **CPython binary CVEs** (CVE-2026-19445 CRITICAL + CVE-2026-19553/82049
  HIGH in 3.13.15/3.12.14 — grype-only findings, fixes in 3.13.16/3.12.15):
  both python base pins refreshed (3.13.16-slim-bookworm @a1165e2, 3.12-slim
  @a6e34c5) and the conductor identity contract assertion moved 3.13.15 →
  3.13.16 (Dockerfile build assert + both security.yml live-verify steps +
  the smoke control image + `test_distribution_contract.py`'s tag assertion,
  same test count).
- **research: uv wheel cache + browser-use exact pins** (anyio 4.12.1
  CVE-2026-63374 CRITICAL + pypdf 6.16.2 x8 HIGH): browser-use 0.13.11 — the
  latest upstream — pins `anyio==4.12.1`/`pypdf==6.16.2` exactly, silently
  downgrading the anyio floor the first install put in place; its uv cache
  archives also carry the same stale METADATA plus the anthropic SDK example
  files the secret scanner flags. Fix: a second `uv pip install` re-asserts
  `anyio>=4.14.2`/`pypdf>=6.19.0` with a build-time import assertion, and
  `/root/.cache/uv` is dropped in the same layer.
- **moto fixture secrets** (moto_proxy ca.key/cert.key `private-key` HIGH,
  example AWS key `aws-access-key-id` CRITICAL — moto is the RSI runner's
  AWS-mock dev dependency, shipped by its own wheel): suppressed via the
  ignore file's `secrets:` section, path-scoped to moto's own tree with
  statements and a 2027-01-31 expiry (verified: past expiry re-surfaces the
  findings; path scope keeps any other key blocking).

Evidence on the final repaired images (all local, this tree): trivy exit 0 x4
(HIGH/CRITICAL, ignore-unfixed, the job's ignore file), grype exit 0 x4
(`--fail-on high --only-fixed`), license gate `OK: inventoried 8 surface(s),
26804 component(s); copyleft=433 (policy=review)`, conductor live-verify
`identity=operational python=3.13.16`, observability variant
`observability=importable identity=operational`, engine `import
maistro_server.main` ok with `docker --version` = v29.9.1 dfc520d built from
source, research imports `maistro_server.main, browser_use, anyio, pypdf`
with anyio 4.15.1/pypdf 6.21.1 on python 3.12.15, actionlint+shellcheck clean with CI's exact
flags, and `check-image-pins`/`check-image-inventory`/vulture ledger/suite
inventory/backlog gates all green.

Not changed on purpose: `deploy/sbx/template/preseed/*.tar` are
git-ignored producer artifacts regenerated by `deploy/sbx/build.sh` on the
next operator run (the sbx path carries a license gate, not this vuln gate);
historical spec/inventory-note texts that quote `3.13.15` as point-in-time
evidence stay as written.

## Delta 5 (CI-repair round: the aiohttp vector Delta 4 missed + develop sync)

CI run 39400043294 still failed "Container scan + SBOM + cosign" at
ed15588a84f5 — in the "Trivy scan maistro-engine-research" step, on
**aiohttp 3.14.3** (CVE-2026-111064 missing-initial-request-timeout DoS HIGH
+ GHSA-2g87-pp6c-29x5 unbounded memory/CPU HIGH, both fixed in 3.14.4). Delta
4's browser-use countermeasure re-asserted `anyio`/`pypdf` floors but missed
that browser-use 0.13.11 *also* pins `aiohttp==3.14.3` exactly (checked
upstream: every browser-use release to date pins aiohttp exactly — 0.13.5/0.13.0
pin 3.13.4, 0.12.0 pins 3.13.3 — so no version selection can satisfy both the
pin and the CVE floor). Fix, same pattern as the anyio/pypdf one it sits next
to: the second `uv pip install --system` in `Dockerfile.research` now also
re-asserts `aiohttp>=3.14.4`, the build-time assertion covers it, and the
comment records the CVEs and why the pin cannot be honored.

Develop-sync root cause for the other red gates at ed15588a: the branch was
three commits behind `origin/develop`, and #2228 (9417bb2f4) wires
`maistro.runs.admission_identity` into `maistro.runs.__init__` — without that
commit the contract leaf is an orphan, which is exactly why the reachability
ratchet (168 → 169), `exact-debt-ledger` (provenance trusted-base gate),
`Quality / Reachability`, the three reachability tests in the `test` job, and
the Quality umbrella all failed at once while develop stayed green on the
same scanner versions. `git merge origin/develop` (c2d7209f1) resolved it;
`uv.lock` had already converged to byte-identical content on both sides
(aiohttp 3.14.5 in each), so the merge was conflict-free.

Evidence this round (all local, this tree):

- `scripts/check-reachability.py` rc=0 (168 = baseline),
  `check-reachability-dispositions.py` rc=0, `check-ratchet-provenance.py`
  rc=0 (54 consumers), `check-shipped-surface-truth.py` rc=0,
  `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` rc=0 (1326 reviewed identities ↔ 1326 findings,
  unclassified 0, never_allowlist 0 — no ledger amendment needed),
  reachability test trio 39 passed, `tests/test_check_license_inventory.py`
  + `test_prepull_copy_sources.py` + `test_distribution_contract.py` 62
  passed, maistro-rsi suite 1718 passed + 4 skipped, ruff check/format clean.
- The full containers job reproduced on rebuilt `:pr-363-repair` images:
  research build shows browser-use pulling `aiohttp==3.14.3` then the floor
  install replacing it with `aiohttp==3.14.5` (in-image:
  `aiohttp 3.14.5 | anyio 4.15.1 | pypdf 6.21.1`, `browser_use` imports),
  trivy 0.73.0 exit 0 on all four images, grype 0.116.0 `--fail-on high
  --only-fixed` exit 0 on all four, license gate
  `OK: inventoried 8 surface(s), 25931 component(s); copyleft=423
  (policy=review)`.
- `license-sboms/` and `license-inventory.json` (job-workspace artifacts the
  workflow generates) are now git-ignored so local reproductions cannot leak
  multi-megabyte generated SBOMs into commits.
- `durable-events` failed at ed15588a with `relation "audit_log" does not
  exist` (asyncpg UndefinedTableError) — branch-caused? No: the branch touches
  no events/persistence code, and the same check passed on develop's head
  c2d7209f1 two hours later; recorded as CI/DB-race flake, not repaired here.
- `integration-scope` is the aggregator waiting on the required specialized
  checks; it follows the gates above.
