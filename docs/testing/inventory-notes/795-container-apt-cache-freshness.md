---
inventory-delta:
  packages/maistro-core/tests: +5
---
<!-- Measured by scripts/check-suite-inventory.py --update; see README.md. -->
# 795-container-apt-cache-freshness

Issue #795 CI-repair round: the "Container scan + SBOM + cosign" gate failed
at 0bb7551c563b on maistro-engine carrying `libexpat1 2.5.0-1+deb12u4`
(CVE-2025-59375 / CVE-2026-77214, both HIGH, both fixed in `2.5.0-1+deb12u5`)
in a build whose Dockerfile nobody had touched.

## Root cause (from the failing run's own log, job 120055597651)

The engine image's security-patch layer —
`RUN apt-get update && apt-get install git && apt-get upgrade -y …` — came
back `CACHED` from the GHA build cache (`#25 CACHED` in the log). An apt
layer's cache key (pinned base digest + instruction text) never changes, so
once cached it replays whatever the Debian security mirror served when it was
first built; `apt-get upgrade` never re-runs to pick up later advisories. The
trivy DB, freshly updated at scan time, knew the fixed version; the image did
not contain it. The same structure exists in all four scanned images
(`Dockerfile`, `Dockerfile.research`, `Dockerfile.rsi-runner`,
`packages/hive-conductor/Dockerfile`); the other two Debian images' trivy
steps never ran in the aborted job.

## Fix

Each Debian runtime's security-patch layer moves into its own named stage
(`runtime-apt` / `production-apt`) and every `security.yml` containers-job
build passes `--no-cache-filter <stage>`, so the OS patch state is
re-consulted from the security mirror on every gated build while the
venv/Go/npm layers stay cached. `release.yml` builds cold (no
`--cache-from`) and needs no flag.

## This change's own delta

`packages/maistro-core/tests` **+5** —
`fitness/test_container_apt_stage_cache_freshness.py`:

- **+4** (parametrized over the four governed Dockerfiles) — the
  security-patch layer lives in the expected named `*-apt` stage, that stage
  actually runs `apt-get update` + `apt-get upgrade`, and a later `FROM`
  consumes the stage (otherwise the re-run would build layers nothing
  ships).
- **+1** — every `buildx-build-retry.sh` build in the `containers` job gates
  an image whose Dockerfile appears above, and passes
  `--no-cache-filter` naming that image's stage. Verified to fail when the
  engine's flag is stripped and pass when present.

## Local evidence (2026-10-22, buildx v0.37.2 / BuildKit v0.26.2, trivy 0.73.0)

- Warm rebuild **without** the flag: `[runtime-apt 2/2] RUN apt-get …` →
  `CACHED` (the defect, reproduced).
- Warm rebuild **with** `--no-cache-filter runtime-apt`: the stage
  re-executes; shipped `maistro-engine` carries
  `libexpat1 2.5.0-1+deb12u5`.
- Trivy with the gate's exact flags (`--severity HIGH,CRITICAL --exit-code 1
  --ignore-unfixed`, checked-in ignore list) on all four rebuilt images:
  `maistro-engine`, `maistro-rsi-runner`, `maistro-engine-research`,
  `hive-conductor` — all exit 0. Grype v0.116.0 `--only-fixed --fail-on
  high` on `maistro-engine`: exit 0 (two Medium findings only).
