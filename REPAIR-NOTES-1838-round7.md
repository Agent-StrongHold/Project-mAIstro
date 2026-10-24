# REPAIR-NOTES-1838 round 7 — containers gate: libbrotli1 HIGH in maistro-rsi-runner

Lane L1838, issue #1838 (Decision: Select Biscuit verification adapter).
Branch `auto-1838`; base `4de7e906d9dc` (= `origin/develop`, no sync conflict);
starting head `75ccdf3080d8` (round-6 commit, 72 of 73 checks green there).

## Incoming evidence (CI run 40089575072, job 120859324681, at `75ccdf3080d8`)

`Container scan + SBOM + cosign` was the only failing check of 73. Failing
step: **"Trivy scan maistro-rsi-runner (HIGH/CRITICAL only)"** (log fetched
with `gh run view 40089575072 --log-failed`). The scan's own table:

- `libbrotli1 1.1.0-2+b7` (Debian OS package) — CVE-2026-111497, HIGH,
  status **fixed**, Fixed Version **1.1.0-2+deb13u1** ("brotli: Out-of-Bounds
  Write in Google Brotli Decoder").
- Everything else in the image: 0 findings (debian 13.7, python-pkg METADATA
  incl. pypdf 6.21.2 from round 6, rustbinary uv, temporalio Cargo.lock,
  moto text rows).

The step ran with `exit-code: 1` on `HIGH,CRITICAL`, so that single row is the
whole failure. Steps 12–14 (hive-conductor, maistro-engine,
maistro-engine-research Trivy) passed at the same head.

## Root cause (evidence, not guesswork)

`Dockerfile.rsi-runner` installs `curl` in its `runtime-apt` stage
(`apt-get update && apt-get upgrade -y && apt-get install -y
--no-install-recommends git curl build-essential`); curl pulls
`libcurl4t64 -> libbrotli1`. security.yml force-rebuilds that stage on every
candidate (`--no-cache-filter runtime-apt`, the #795 mechanism), so the
installed version always reflects the Debian mirror at build time (11:35Z).
The advisory's fixed package `1.1.0-2+deb13u1` was not yet what that stage's
`apt-get` saw then; it is now:

- `docker run --rm python:3.12-slim@sha256:a6e34c…` (the exact pinned base):
  `apt-cache policy libbrotli1` → Candidate **1.1.0-2+deb13u1** from
  `http://deb.debian.org/debian-security trixie-security/main` (version table
  ranks it above `1.1.0-2+b7` from trixie/main).

This is the publish-lag class the #795 comment documents; the gate is designed
to self-heal it by re-consulting the mirror on every candidate. `Dockerfile.research`
shares the same trixie base but explicitly removed curl/wget, which is why its
scan passed while rsi-runner's failed.

## Repair

**None required in the repository.** No source, lock, Dockerfile, gate, or
ledger change addresses a mirror-state race; a cosmetic diff would only
re-trigger CI. What the failing step needs is a rebuild after the mirror
caught up — proven locally below. `ignore-unfixed` is already set, so an
`.trivyignore.yaml` entry would be both wrong (the fix exists) and a gate
weakening.

## Post-repair evidence (all commands executed this round)

- **Rebuilt `maistro-rsi-runner:pr-2269-r7`** with the CI build shape
  (`docker buildx build --load -f Dockerfile.rsi-runner --no-cache-filter
  runtime-apt .`): **exit 0**.
- In-image: `cat /etc/debian_version` → 13.7;
  `dpkg -l libbrotli1` → **1.1.0-2+deb13u1** — the exact Fixed Version the CI
  table named; `apt-cache policy` inside confirms it installed from
  trixie-security.
- **Trivy 0.73.0** (CI-pinned version) with CI-exact flags
  `--severity HIGH,CRITICAL --exit-code 1 --ignore-unfixed --ignorefile
  .trivyignore.yaml --scanners vuln,secret` on that image: **exit 0** — the
  exact failing step, now green. (Local Trivy DB is older than CI's fresh DB,
  so a pass here is the conservative direction.)
- **Grype 0.116.0** (CI-pinned) cross-check leg (step 16, never reached in
  CI): `grype maistro-rsi-runner:pr-2269-r7 --fail-on high --only-fixed` →
  **exit 0** (worst severity present: Medium, fixed-version rows only).
- The other three images force-rebuild their own apt stages (`--no-cache-filter`)
  and passed the identical Trivy scans at this exact head hours ago; the only
  in-flight advisory (trixie brotli) does not reach them (deb12 bases for
  hive-conductor/maistro-engine; research has no libbrotli1).
- Vulture per-identity ledger, exact CI/lane-brief args
  (`check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'`): 1302 reviewed identities → 1302 findings, **exit 0**.
  No ledger amendment required or made (zero source change).
- Issue deterministic acceptance: `uv run python
  scripts/check-adr-status-language.py` → `ok: 0 baselined body-status
  contradiction(s)`; `git diff --check` clean.
- Driver deterministic checks at this head (job 7b9aa987…/check-*.log):
  `uv sync --locked --extra dev`, `uv run ruff check .`,
  `uv run ruff format --check .` — all returncode 0.

## Scope notes

- This round repairs the CI gate only. It does not advance issue #1838's
  actual decision gate: the Biscuit verification-adapter contract
  (`docs/adr/ADR-101826-2a63-biscuit-verification-adapter.md`) still requires
  the named owner's explicit review/acceptance before downstream leaves
  unblock. Unresolved decisions stay visibly open.
- Residual risk (inherent to the gate, not this repair): a future advisory
  whose fix is not yet in the mirror at build time will fail the gate again;
  the #795 `--no-cache-filter` design already minimizes that window. The
  merge-queue's fresh Trivy DB could also surface rows a local DB does not
  know yet.
