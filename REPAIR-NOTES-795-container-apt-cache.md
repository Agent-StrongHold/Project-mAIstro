# Issue 795 repair round: Container scan + SBOM + cosign (apt layer cache staleness)

Round head: 0bb7551c563b (start) → this commit. Scope: the single failing CI
check at the round head — `Container scan + SBOM + cosign` (job 120055597651,
run 39844926472). Every other check at that commit was green.

## Root cause — read from the failing job's own log, not guessed

- Failing step: `Trivy scan maistro-engine (HIGH/CRITICAL only)`
  (`##[error]Process completed with exit code 1`, log line 4785).
- Findings (image `maistro-engine:pr-2252`, debian 12.15):
  `libexpat1` **CVE-2025-59375** and **CVE-2026-77214**, both HIGH, both
  `fixed` in `2.5.0-1+deb12u5`, installed `2.5.0-1+deb12u4`.
- Mechanism, log lines 1899–1900: the image's security-patch layer —
  `[stage-2 3/12] RUN apt-get update && apt-get install git && apt-get
  upgrade -y …` — reports **`CACHED`**. An apt layer's cache key (pinned base
  digest + instruction text) never changes, so the GHA build cache
  (`--cache-from type=gha,scope=engine`) replayed a mirror state that
  predates the `deb12u5` security update; `apt-get upgrade` never re-ran.
  The trivy DB, refreshed at scan time, knew the fix; the image did not
  contain it. Nothing in the repo changed between the last green container
  run and this red one — the advisory moved, the image could not.
- The Debian security mirror serves `2.5.0-1+deb12u5` today (verified:
  `apt-cache policy libexpat1` in `debian:bookworm-slim`, candidate
  `2.5.0-1+deb12u5` from `bookworm-security`), so this is not an
  unfixed-CVE allowlist question. `.trivyignore.yaml` was not touched.

## Fix

Each Debian runtime's security-patch layer moves into its own named stage,
and the gating build bypasses the layer cache for exactly that stage:

- `Dockerfile`: `FROM … AS runtime-apt` (apt layer) → `FROM runtime-apt`.
- `Dockerfile.research`: same split as `production-apt`.
- `Dockerfile.rsi-runner`: same split as `runtime-apt`.
- `packages/hive-conductor/Dockerfile`: same split as `runtime-apt`.
- `.github/workflows/security.yml` `containers` job: all five build steps
  (conductor, conductor-observability, engine, research, rsi-runner) pass
  `--no-cache-filter <stage>`. Only the apt stage re-runs; venv/Go/npm
  layers stay cached. `release.yml` builds cold (no `--cache-from`), so it
  needs no flag — release images were never affected.

## Local proof (2026-10-22, buildx v0.37.2 / BuildKit v0.26.2, trivy 0.73.0, grype v0.116.0)

- Defect reproduced: warm rebuild *without* the flag →
  `#9 [runtime-apt 2/2] RUN apt-get …` → `CACHED`.
- Fix proven: warm rebuild *with* `--no-cache-filter runtime-apt` → stage
  re-executes; shipped `maistro-engine` reports
  `libexpat1 2.5.0-1+deb12u5`.
- Trivy with CI's exact flags (`--severity HIGH,CRITICAL --exit-code 1
  --ignore-unfixed`, checked-in ignore list): `maistro-engine`,
  `maistro-rsi-runner`, `maistro-engine-research`, `hive-conductor` — all
  **exit 0** (rsi-runner/research are debian 13 bases with libexpat
  `2.9.0-1~deb13u1`, not affected; `libexpat1` is not installed in
  hive-conductor at all).
- Grype `--only-fixed --fail-on high` on `maistro-engine`: **exit 0** (two
  Medium python-binary findings only, below the gate severity).
- Structural gates after the edits: `check-image-pins.py`,
  `check-image-inventory.py`, `check-workflow-inventory.py`,
  `check-doc-links.py`, `ruff check .`, `ruff format --check .` — all pass.
- Lane regression battery: 80 passed, 5 skipped
  (M7-A6 proof + lineage + rubric + eval-consumer tripwire + the new fence);
  both suite-inventory gates pass with the +5 delta recorded in
  `docs/testing/inventory-notes/795-container-apt-cache-freshness.md`.

## Regression fence

`packages/maistro-core/tests/fitness/test_container_apt_stage_cache_freshness.py`
(+5 node IDs): the security-patch layer must live in the named, consumed
`*-apt` stage of each governed Dockerfile, and every containers-job build of
those images must pass `--no-cache-filter` naming it. Verified to fail when
the engine's flag is stripped from security.yml and pass when present.

## Residual risks

- `hive-conductor-observability` (same Dockerfile, `INSTALL_OBSERVABILITY=1`)
  was not built locally; it shares the verified `runtime-apt` stage and
  differs only in pybuild-stage extras.
- The four grype scans and the license/SBOM steps of the job run after the
  trivy steps and were not executed locally end-to-end; engine grype was
  proven clean, and the license surface is untouched by this change.
