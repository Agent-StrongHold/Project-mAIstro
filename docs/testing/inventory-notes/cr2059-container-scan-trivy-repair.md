---
inventory-delta:
  tests/: +5
---
# cr2059-container-scan-trivy-repair

Repair round for #2059 on `fix/vulture-single-owner-1357` (start head `e8abf304d`).

The recorded red job was "Container scan + SBOM + cosign" (run 43804955428,
job 133093476827). Its log shows `npm audit fix` text, but that text is an
informational notice from a successful `npm ci`; it is not the failing step.
The failing step is the Trivy gate (`exit-code: 1`, HIGH/CRITICAL) on
`maistro-engine:pr-2059`, which reported two HIGH findings in the
source-built `usr/local/bin/docker` binary:

- CVE-2026-116587 `github.com/go-jose/go-jose/v4` v4.1.5 -> fixed 4.1.6
- CVE-2026-78661 `golang.org/x/net` v0.60.0 -> fixed 0.62.0

Both modules come from docker/cli's vendored module set. Fix: the docker CLI
source-build stage in `Dockerfile` and `Dockerfile.research` now runs
`go get` for both fixed releases, then `go mod vendor` (`go get` alone leaves
`vendor/modules.txt` inconsistent: "inconsistent vendoring").

Also tracked: `Dockerfile.research` failed Trivy on four `uv.lock` Python pins
with fixes available: oauthlib 4.0.0 -> 4.0.1 (CVE-2026-49272), pyasn1 0.6.4 ->
0.6.5 (CVE-2026-119194..119197), pypdf 6.21.2 -> 6.21.4 (CVE-2026-119203..119205),
soupsieve 3.0.3 -> 4.1.1 (CVE-2026-126190; uv picked the latest satisfying the
fixed floor). Lock moved with `uv lock --upgrade-package`; `uv lock --check` passes.

New test: `tests/test_docker_cli_vendored_advisory_floors.py` (+5). It asserts
both Dockerfiles raise the two modules in the docker CLI stage and re-sync
`vendor/` after the upgrade. Verified: passes on the fixed files, fails on
the pre-fix `HEAD` Dockerfiles for the intended reason.

Local proof (CI-equivalent Trivy args, `--ignore-unfixed --exit-code 1
--severity HIGH,CRITICAL --ignorefile .trivyignore.yaml`):
hive-conductor exit 0; maistro-engine exit 0 (0 findings);
maistro-engine-research exit 0. Reconciliation gate
`check-image-lock-reconciliation.py` exit 0 for engine and research images.

Not fixed here: `maistro-rsi-runner` still reports CVE-2026-115905 (CRITICAL)
and CVE-2026-115907/08/09 (HIGH) against `zip` 8.6.0. The match is a Rust
`Cargo.lock` shipped inside the `temporalio` wheel
(`.venv/lib/python3.12/site-packages/temporalio/bridge/Cargo.lock`), not an
installed Python package, and no triage entry exists for it. Left UNRESOLVED
for a human scope decision (ignore-file triage vs. upstream temporalio bump).
