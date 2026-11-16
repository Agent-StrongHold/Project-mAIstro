# Repair notes — issue #1450 round 6 (container scan grype leg + coverage-gate timeout flake)

Branch `auto-80`, head before this round: `654b773ced78` (develop tip
`f8a2df966` already merged — merge-base HEAD..origin/develop equals
`origin/develop`, no develop conflict remains).

## Root causes of the reported CI failures

Merge-queue evaluation at head `654b773ced78` (security.yml run 43812084107 /
quality.yml run 43812084099, 2026-11-16). Of the 80 check runs at that head,
`Supply chain (pip-audit)` and `sandbox-conformance` PASSED; two failed:

1. **`Container scan + SBOM + cosign`** — job 133115778563. The trivy leg
   passed for all four images; the **grype cross-check failed on
   hive-conductor** (`--fail-on high --only-fixed`): the CPython 3.13.16
   binary itself is flagged Critical **CVE-2026-115557** (fixed 3.13.18, also
   3.12.16/3.14.10) plus Medium CVE-2026-12345 / CVE-2026-114583 (fixed
   3.13.18). Medium CVE-2025-15367 (fixed only in 3.15.0a6) and
   CVE-2026-116566/CVE-2026-103995 (fixed 3.16.0) are below the HIGH
   threshold and stay below it after this fix — no stable fix exists, so no
   triage or pin change can address them. The job died at the first image of
   the grype loop before scanning maistro-engine, whose docker/cli vendor
   tree downloads `github.com/klauspost/compress v1.20.1`; grype's DB gained
   **GO-2026-6865** (HIGH, fixed v1.20.2) for it, so the same loop would have
   failed there next. Per the gate's upgrade-when-a-fix-exists policy, both
   are upgrades, not triage entries.

2. **`Coverage gate (publish-set floor + diff coverage)`** — job
   133120551863. The three coverage producers succeeded and no coverage
   floor or diff threshold regressed: the combine step's root-suite re-run
   failed `tests/test_devskim_scan_scope.py::
   test_no_shipped_source_file_is_excluded_from_the_scan` with
   `Failed: Timeout (>30.0s) from pytest-timeout` (1 failed, 5931 passed).
   The branch touches neither that test nor `.github/workflows/devskim.yml`
   (`git diff origin/develop...HEAD` on both is empty), so this is a latency
   flake, not a scope regression. Structural cause: `_is_scanned` is called
   once per shipped source file and used to re-read and re-parse devskim.yml
   twice per call (~5k files → ~10k YAML parses). Locally that is 7.3s; on a
   loaded 2-core runner inside the serial combine step it crossed 30s.

## Fix

- **Base pin bump (#93/#1152 doctrine):** `python:3.13.16-slim-bookworm`
  `sha256:73aa5fae…` → `python:3.13.18-slim-bookworm`
  `sha256:a5a7017e…` in both `Dockerfile` and
  `packages/hive-conductor/Dockerfile` (builder + runtime-apt stages),
  `scripts/smoke-engine-canvas.sh` control image, the identity version
  asserts in `packages/hive-conductor/Dockerfile` and security.yml's two
  in-image verification steps (3.13.16 → 3.13.18), the support-matrix doc,
  `tests/test_distribution_contract.py`'s two-tag expectation, and the
  `quality/image-pins.json` row re-recorded (recorded 2026-11-16,
  recorded_in #1450, note extended with this round's run/job evidence).
  Digest resolved via `docker buildx imagetools inspect
  python:3.13.18-slim-bookworm` → `sha256:a5a7017efc5969e00ae2b91c8eb06310…
  49ae45c72`; the cp313 coincurve identity contract is unchanged (still
  3.13.x).
- **docker/cli vendored patch:** `go get github.com/klauspost/compress@v1.20.2`
  added to the `dockerclibuild` stage in `Dockerfile` (same
  patch-the-immutable-tag-and-re-vendor policy as the go-jose/x/net patches
  from round 3).
- **Coverage-gate timeout flake:** `tests/test_devskim_scan_scope.py`
  memoizes `_scanner_step` / `_ignore_globs` / `_include_globs`
  (`functools.lru_cache(maxsize=1)`, tuple returns) so the workflow is
  parsed once per pytest process. No assertion changed — the same
  scan-scope invariants are checked, ~40x faster (7.29s → 0.18s locally for
  the sweep test). Test count unchanged (21 in the file), so no inventory
  delta; this note records the repair.

## Evidence (all executed locally at the repaired tree)

- `uv sync --locked --all-extras` → clean; `uv pip freeze` →
  CI-exact `pip-audit --strict --format=json` →
  `pip-audit OK (1 known, all triaged in ALLOWED)`, gate exit 0 (sole
  advisory the reviewed `ecdsa PYSEC-2026-1325` ALLOWED entry) — the
  pip-audit leg is green at this tree, matching the SUCCESS check run at
  head 654b773.
- `docker buildx imagetools inspect python:3.13.18-slim-bookworm` → digest
  matches the new pin row byte-for-byte.
- `scripts/check-image-pins.py` → "9 pinned base/tool image(s) across 11
  Dockerfile(s), all registered"; `scripts/check-image-inventory.py` → ok.
- `uv run pytest tests/test_devskim_scan_scope.py` → 21 passed, sweep test
  0.18s (was 7.29s before memoization, measured at the same tree).
- `tests/test_distribution_contract.py` + `tests/test_pinned_digest_references.py`
  + `tests/test_check_image_lock_reconciliation.py` → 97 passed.
- Rootless conformance lane, CI-exact: image rebuilt from this tree's
  `Dockerfile.sandbox`, loaded into the rootless daemon
  (`unix:///run/user/1000/docker.sock`), memory.max enforcement proof
  printed 67108864 under a 64m limit, then
  `DOCKER_HOST=…rootless… uv run pytest packages/maistro-bootstrap/tests`
  → **306 passed, 3 skipped**.
- `ruff check .` all passed; `ruff format --check .` 3562 files formatted.
- `check-suite-inventory.py --suite packages/maistro-bootstrap/tests` → ok.
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` → RC 0, 1238 reviewed identities = 1238 findings.
- `git diff --numstat origin/develop -- quality/` → only the intended
  branch deltas (ac-state-notes append, image-inventory rows, image-pins
  in-place row edit; image-pins still 9 rows on both sides; vulture and
  ratchet-authorization ledgers have no diff vs develop — no row loss).

## Residual risk

The full `Container scan + SBOM + cosign` job needs GHA buildx cache and
cosign keys; locally the hive-conductor image was rebuilt from this tree and
the grype cross-check re-run against it (see the round-6 result record).
trivy's OS-layer triages in `.trivyignore.yaml` are untouched by this round;
CVE-2025-15367 / CVE-2026-116566 / CVE-2026-103995 (CPython binary, Medium/Low,
fixed only in 3.15.0a6/3.16.0) stay below the grype `--fail-on high`
threshold until upstream ships a stable fix.
