# Repair round 4 (2026-11-16) — Container scan + SBOM + cosign (the named red `security` gate) at `fc3e72918052`

Evidence-first: the failing CI job (133255150383, run 43854493920) died at the
"Trivy scan maistro-engine-research (HIGH/CRITICAL only)" step with three
python-package finding groups, all pinned by this tree's `uv.lock`:

- `pyasn1` 0.6.4 — CVE-2026-119195/196/197
- `pypdf` 6.21.2 — CVE-2026-119203…209 (fixed 6.21.4)
- `soupsieve` 3.0.3 — CVE-2026-126190 (fixed 4.0.0)

All three are reachable **only** through the `browser` extra
(`maistro-core[browser]` → `browser-use` → pypdf / markdownify→beautifulsoup4 /
google-auth→pyasn1-modules→pyasn1), so only the research image installs them;
the engine/hive/rsi exports name none of them (verified by grepping each CI
`uv export` selection).

## What changed (this round)

`uv.lock` (targeted `uv lock --upgrade-package`, each row minimal):

- `pyasn1` 0.6.4 → **0.6.5**, `pypdf` 6.21.2 → **7.1.0**, `soupsieve` 3.0.3 → **4.1.1**
  — clears the three failing groups.
- `oauthlib` 4.0.0 → **4.0.1** — CVE-2026-49272 (HIGH, auth bypass via missing
  device-code validation) appeared in the trivy DB after CI's 11:18Z run; same
  browser-extra chain (`requests-oauthlib` → `google-auth-oauthlib`). Found by
  re-running the CI-exact scan locally, fixed before it could redden the next run.
- `patchright` 1.64.1 → **1.64.4** (bundled node **v24.22.1**, measured from the
  wheel) and `playwright` 1.64.0 → **1.65.2** (bundled node **v26.13.1**,
  measured from the wheel) — grype 0.116.0 `--only-fixed` flagged both drivers'
  node 24.21.0: CVE-2026-111497 (CRITICAL, kev), CVE-2026-105482/105483/106069
  (HIGH). grype never ran in the failed job (it died at the research trivy
  step), so these were never surfaced before this round.
- `temporalio` 1.34.0 → **1.36.1** (+ `nexus-rpc` 1.5.0) — trivy flags the
  `zip` Rust crate 8.6.0 inside temporalio's vendored bridge `Cargo.lock`
  (CVE-2026-115905 CRITICAL / 115907/115908/115909 HIGH, fixed 9.0.5+) in
  maistro-rsi-runner; 1.36.1's bridge locks zip **9.5.1** (measured from the
  wheel). rsi-runner trivy had never been reached in recent failing runs.

Base digest refresh (same doctrine as the #1152/#363 refreshes, anticipated by
the 3.13.18 pin note "research/rsi-runner … whose 3.12.16 is already in this
CVE's fixed list"):

- `python:3.12-slim` index digest `a0f57064…` (2026-10-24, CPython **3.12.15**)
  → `5e2bdb1b…` (resolved 2026-11-16 via `docker buildx imagetools inspect`,
  `org.opencontainers.image.version` **3.12.16-slim-trixie**, created
  2026-11-05) — grype flags CPython 3.12.15 binary CVE-2026-115557 CRITICAL
  (fixed *3.12.16). Applied to every user of the pin: `Dockerfile.research`
  (builder + production-apt), `Dockerfile.rsi-runner` (runtime-apt),
  `packages/hive-conductor/tests/Dockerfile`, `deploy/sbx/template/Dockerfile.tests`,
  and `quality/image-pins.json` (digest/recorded/recorded_in/note, recorded_in
  #1836).

## Local proof (CI-exact), all at this tree

Built locally with `scripts/buildx-build-retry.sh` (same entry point as CI;
`--no-cache-filter` on the same stages CI flushes):

- `maistro-engine-research:pr-2264`: in-image asserts (python 3.12.16;
  pypdf 7.1.0, soupsieve 4.1.1, pyasn1 0.6.5, oauthlib 4.0.1, playwright
  1.65.2, patchright 1.64.4) + functional smoke (soupsieve CSS select,
  markdownify, pypdf write/read round-trip, pyasn1 BER decode) — OK;
  patchright driver node `v24.22.1` in-image; trivy 0.73.0 (HIGH,CRITICAL,
  exit-code 1, ignore-unfixed, `.trivyignore.yaml`) **rc 0**; grype 0.116.0
  (`--fail-on high --only-fixed`) **rc 0**; `check-image-lock-reconciliation`
  **OK** (147 distributions, exactly the locked set).
- `maistro-rsi-runner:pr-2264`: python 3.12.16 + temporalio 1.36.1 import OK;
  trivy **rc 0** (was rc 1 on the zip crate before the bump); grype **rc 0**;
  reconciliation **OK** (220 distributions).
- `maistro-engine:pr-2264`, `hive-conductor:pr-2264` (content unchanged by this
  round — their exports name none of the touched packages): trivy **rc 0**,
  grype **rc 0** with today's feeds.
- Supply chain (pip-audit) job, CI-exact: `uv sync --locked --all-extras`,
  `pip-audit --strict --format=json`, `scripts/pip_audit_gate.py` → **rc 0**
  (only the triaged `ecdsa==0.19.2 PYSEC-2026-1325`).
- Static gates: `check-image-pins` rc 0 (9 pins, 10 Dockerfiles);
  `tests/test_distribution_contract.py` 6 passed (BROWSER_SECURITY_FLOORS
  still satisfied); `check-adr-status-language.py` rc 0; `git diff --check`
  clean; `ruff check .` + `ruff format --check .` clean; vulture CI-exact
  **1238 == 1238** (no ledger edit owed); suite inventory rc 0 (21 suites).
- SPEC-101826 golden vectors (`/tmp/spec_vectors_1836_round.py`, V-1…V-18 +
  resolution order): **43/43 pass**; focused suites (capabilities +
  image-lock-reconciliation + distribution contract): **897 passed, 8 skipped**.

## Not touched, on purpose

- No gate, ledger, ownership or policy change; no `.trivyignore.yaml` entry
  added (every finding was fixed, not suppressed). The existing entries are
  untouched and remain justified.
- `hive-conductor-e2e-ui` (rsi-polling-resilience.spec.ts:574 wall-clock bound)
  and its `integration-scope` cascade: branch-independent latency flake,
  unverified cause — NOT repaired by guessing; left to its own evidence.
- SPEC-101826 stays `status: Proposed`: the ADR owner's explicit acceptance of
  the contract + vectors is the issue's real gate and is not mine to record.

## Infra note

grype/trivy scratch under `/tmp` (tmpfs) filled the device mid-round; only
dead `stereoscope-*` extraction caches (no live grype process owned them) were
removed. Two trivy invocations hit transient "cache may be in use by another
process" lock contention on the shared DB cache and were re-run (one with a
private `--cache-dir`) — all final scan results above are from successful,
complete scans.
