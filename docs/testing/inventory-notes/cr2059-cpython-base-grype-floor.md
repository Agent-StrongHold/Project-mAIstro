---
inventory-delta:
  tests/: +14
---
# cr2059-cpython-base-grype-floor

Repair round for #2059 on `fix/vulture-single-owner-1357` (start head
`2da04e5d`).

The recorded red job was again "Container scan + SBOM + cosign" (run
43844074725, job 133219714506), at the head that already carried the Trivy
docker-CLI vendor fix and the temporalio floor bump. Fetched the job log
(read-only `gh api .../jobs/133219714506/logs`): every image build and all
four Trivy steps succeeded; the failing step is the **Grype scan
(cross-check)**, which aborts on the first loop iteration:

- CVE-2026-115557 (CRITICAL) in the CPython **3.13.16** *binary* shipped in
  `hive-conductor:pr-2059`, fixed in 3.13.18 (also 3.12.16/3.14.10).

The earlier npm-audit log lines that misdirected the previous round are the
tail of the successful build steps; grype exits 2 on threshold findings, not
on the npm notice.

## The change

- `python:3.13.16-slim-bookworm@73aa5fae…` →
  `python:3.13.18-slim-bookworm@a5a7017e…` in `Dockerfile` (builder +
  runtime-apt) and `packages/hive-conductor/Dockerfile` (pybuild +
  runtime-apt); the pin row re-recorded in `quality/image-pins.json`;
  `scripts/smoke-engine-canvas.sh` CONTROL_IMAGE follows the registry (held
  closed by `tests/test_pinned_digest_references.py`).
- `python:3.12-slim@a0f57064…` (resolved 3.12.15) → `@5e2bdb1b…` (tag head,
  verified to resolve 3.12.16) in `Dockerfile.research`,
  `Dockerfile.rsi-runner`, `packages/hive-conductor/tests/Dockerfile`,
  `deploy/sbx/template/Dockerfile.tests`. Proactive: the grype loop stops at
  its first failing image, so the research/RSI images never reported, but
  their pinned 3.12.15 binaries carry the same CRITICAL.
- security.yml docker-run asserts `(3, 13, 16)` → `(3, 13, 18)` (both Verify
  steps); `tests/test_distribution_contract.py` pin updated;
  `docs/security/CONDUCTOR-IDENTITY-SUPPORT-MATRIX.md` and the
  security-scan skill doc refreshed.

## Local proof

grype v0.116.0 (CI's exact release, checksum-verified) with CI's flags
`--fail-on high --only-fixed`, current DB:

- `python@73aa5fae…` (3.13.16): **exit 2** — CVE-2026-115557 CRITICAL
  (binary) reproduced; matches the CI table exactly.
- `python@a5a7017e…` (3.13.18): **exit 0** — zero HIGH/CRITICAL findings.
- `python@a0f57064…` (3.12.15): **exit 2** — same CRITICAL binary finding.
- `python@5e2bdb1b…` (3.12.16): python-binary finding gone; residual zlib1g
  deb HIGHs are patched by the `apt-get upgrade` in the research/rsi
  security-patch stages on every candidate (established #93 mechanism).

Identity contract: `docker run` of the new 3.13.18 digest prints
`Python 3.13.18`; coincurve 21.0.0 keeps publishing cp313 wheels, so the
pin's reason for being an exact patch tag is unchanged.

## The new tests

`tests/test_cpython_base_grype_floor.py` (+14 node IDs: 1 floor case, 1
assert-equivalence case, 2 parametrized 3.13-Dockerfile cases, 4
parametrized 3.12-Dockerfile cases, 6 parametrized retired-digest cases): the 3.13 pin stays at the
grype floor; security.yml's version asserts equal the pinned patch (the
forgotten-assert drift class); both 3.13 Dockerfiles and all four 3.12
Dockerfiles reference the registry rows verbatim; no Dockerfile keeps the
retired vulnerable digest. All fail against the pre-fix tree for the
intended reason (verified by running the assertions against
`git show HEAD:` content).
